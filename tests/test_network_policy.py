# Helm 렌더링과 양방향 NetworkPolicy 규칙의 정적 검증. 실제 CNI 집행 검증은 배포 후 수행.
import ipaddress
import subprocess
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/generic-service"
VALUES = ROOT.parent / "gitops-value/values/dev/services"
API_PORTS = {"auth-service": 8443, "member-service": 8443, "order-service": 8443,
             "product-service": 8080, "payment-service": 8080,
             "review-service": 8080, "notification-service": 8080}
CALLERS = {"auth-service": "member-service", "member-service": "auth-service",
           "product-service": "order-service", "order-service": "payment-service"}
DB_CLIENTS = set(API_PORTS)
REDIS_CLIENTS = {"auth-service", "order-service"}
KAFKA_CLIENTS = {"product-service", "order-service", "payment-service"}
EXTERNAL_CLIENTS = {"auth-service", "payment-service", "member-service", "review-service", "order-service", "web"}


def read_yaml(path):
    with path.open() as stream:
        return [x for x in yaml.safe_load_all(stream) if x]


def render(namespace="test", values=None, settings=None):
    command = ["helm", "template", "dev-" + namespace, str(CHART), "-n", namespace]
    if values:
        command += ["-f", str(values)]
    for setting in settings or []:
        command += ["--set", setting]
    return [x for x in yaml.safe_load_all(
        subprocess.check_output(command, universal_newlines=True)) if x]


def policies(documents):
    return [x for x in documents if x["kind"] == "NetworkPolicy"]


def labels_match(selector, labels):
    return all(labels.get(k) == v for k, v in selector.get("matchLabels", {}).items())


def service_labels(service):
    return {"app.kubernetes.io/name": "generic-service",
            "app.kubernetes.io/instance": "dev-" + service}


def labels(name, instance):
    return {"app.kubernetes.io/name": name, "app.kubernetes.io/instance": instance}


PROM = labels("prometheus", "kube-prometheus-stack-prometheus")
GRAFANA = labels("grafana", "kube-prometheus-stack")
ALLOY = labels("alloy", "alloy")
TEMPO = labels("tempo", "tempo")
DB = {"cnpg.io/cluster": "petflow-db", "cnpg.io/instanceRole": "primary"}
REDIS = dict(labels("redis", "redis"), **{"app.kubernetes.io/component": "master"})
KAFKA = {"strimzi.io/cluster": "pet-subscription-kafka",
         "strimzi.io/name": "pet-subscription-kafka-kafka",
         "strimzi.io/kind": "Kafka", "strimzi.io/broker-role": "true"}


def loki(component):
    result = labels("loki", "loki")
    result["app.kubernetes.io/component"] = component
    return result


def peer_matches(peer, policy_ns, namespace, pod_labels, ip):
    if "ipBlock" in peer:
        if not ip:
            return False
        address = ipaddress.ip_address(ip)
        block = peer["ipBlock"]
        return address in ipaddress.ip_network(block["cidr"]) and not any(
            address in ipaddress.ip_network(cidr) for cidr in block.get("except", []))
    if "namespaceSelector" in peer:
        if not labels_match(peer["namespaceSelector"], {"kubernetes.io/metadata.name": namespace}):
            return False
    elif namespace != policy_ns:
        return False
    return labels_match(peer.get("podSelector", {}), pod_labels)


def permits(policy, namespace, pod_labels, port, direction="ingress", protocol="TCP", ip=None):
    key = "from" if direction == "ingress" else "to"
    for rule in policy["spec"].get(direction, []):
        if "ports" in rule and not any(p["port"] == port and
                p.get("protocol", "TCP") == protocol for p in rule["ports"]):
            continue
        if key not in rule or any(peer_matches(peer, policy["metadata"]["namespace"],
                namespace, pod_labels, ip) for peer in rule[key]):
            return True
    return False


class NetworkPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rendered = {s: render(s, VALUES / s / "values.yaml") for s in list(API_PORTS) + ["web"]}
        cls.service_policies = {s: next(p for p in policies(docs)
            if p["metadata"]["name"] == "generic-service") for s, docs in cls.rendered.items()}
        cls.db = read_yaml(ROOT / "platform/60-cnpg-cluster/manifests/networkpolicy.yaml")[0]
        app = read_yaml(ROOT / "platform/40-redis/application.yaml")[0]
        cls.redis_values = yaml.safe_load(app["spec"]["source"]["helm"]["values"])
        cls.redis = cls.redis_values["extraDeploy"][0]
        cls.kafka = next(x for x in read_yaml(ROOT / "platform/50-kafka-cluster/manifests/kafka.yaml")
                         if x["kind"] == "Kafka")
        cls.obs = {p["metadata"]["name"]: p for p in read_yaml(
            ROOT / "platform/92-network-policies/manifests/observability.yaml")}

    def test_disabled_defaults_and_empty_allowances(self):
        self.assertEqual(policies(render()), [])
        policy = policies(render(settings=["networkPolicy.enabled=true"]))[0]
        self.assertEqual(policy["spec"]["ingress"], [])
        self.assertEqual(policy["spec"]["egress"], [])

    def test_namespace_default_deny_and_exact_service_selectors(self):
        for s, docs in self.rendered.items():
            self.assertEqual(len(policies(docs)), 3 if s in EXTERNAL_CLIENTS else 2)
            policy = self.service_policies[s]
            self.assertEqual(policy["metadata"]["namespace"], s)
            self.assertEqual(policy["spec"]["podSelector"]["matchLabels"], service_labels(s))
            self.assertEqual(policy["spec"]["policyTypes"], ["Ingress", "Egress"])
            baseline = next(p for p in policies(docs) if not p["spec"]["podSelector"])
            self.assertEqual(baseline["spec"], {"podSelector": {}, "policyTypes": ["Ingress", "Egress"],
                                              "ingress": [], "egress": []})
            # 둘 다 workload wave 0 이전에 적용해 기존 CrashLoop가 기본 차단을 지연시키지 않는다.
            self.assertEqual(policy["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-2")
            self.assertEqual(baseline["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-1")

    def test_gateway_only_uses_exact_identity_and_api_port(self):
        for s, port in API_PORTS.items():
            policy = self.service_policies[s]
            self.assertTrue(permits(policy, "api-gateway", service_labels("api-gateway"), port))
            self.assertFalse(permits(policy, "api-gateway", service_labels("unrelated"), port))
            self.assertFalse(permits(policy, "unrelated", service_labels("api-gateway"), port))
            self.assertFalse(permits(policy, "api-gateway", service_labels("api-gateway"), 5432))

    def test_direct_api_graph_matches_both_ends_not_transitive(self):
        for target, port in API_PORTS.items():
            for caller in API_PORTS:
                expected = CALLERS.get(target) == caller
                self.assertEqual(permits(self.service_policies[target], caller, service_labels(caller), port), expected)
                self.assertEqual(permits(self.service_policies[caller], target, service_labels(target), port, "egress"), expected)

    def test_dns_tcp_udp_only_to_coredns(self):
        for policy in self.service_policies.values():
            for protocol in ["TCP", "UDP"]:
                self.assertTrue(permits(policy, "kube-system", {"k8s-app": "kube-dns"}, 53, "egress", protocol))
                self.assertFalse(permits(policy, "kube-system", {"k8s-app": "other"}, 53, "egress", protocol))
                self.assertFalse(permits(policy, "web", {"k8s-app": "kube-dns"}, 53, "egress", protocol))

    def test_database_and_redis_clients_match_both_ends(self):
        for s, policy in self.service_policies.items():
            self.assertEqual(permits(policy, "database", DB, 5432, "egress"), s in DB_CLIENTS)
            self.assertEqual(permits(self.db, s, service_labels(s), 5432), s in DB_CLIENTS)
            self.assertEqual(permits(policy, "redis", REDIS, 6379, "egress"), s in REDIS_CLIENTS)
            self.assertEqual(permits(self.redis, s, service_labels(s), 6379), s in REDIS_CLIENTS)
        # A broad pre-existing policy cannot remain: permissions are additive.
        self.assertFalse(self.redis_values["networkPolicy"]["enabled"])

    def test_kafka_generated_listener_policies_are_restricted_at_source(self):
        for listener in self.kafka["spec"]["kafka"]["listeners"]:
            self.assertIn(listener["port"], [9092, 9093])
            self.assertEqual(len(listener["networkPolicyPeers"]), 3)
            synthetic = {"metadata": {"namespace": "kafka"}, "spec": {"ingress": [
                {"from": listener["networkPolicyPeers"], "ports": [{"port": listener["port"]}]}]}}
            for s, policy in self.service_policies.items():
                expected = s in KAFKA_CLIENTS
                self.assertEqual(permits(synthetic, s, service_labels(s), listener["port"]), expected)
                self.assertEqual(permits(policy, "kafka", KAFKA, listener["port"], "egress"), expected)
            self.assertFalse(permits(synthetic, "product-service", service_labels("wrong"), listener["port"]))

    def test_public_egress_cannot_bypass_private_or_link_local_restrictions(self):
        for s, policy in self.service_policies.items():
            for address in ["10.0.4.5", "172.20.10.10", "192.168.1.1", "100.73.67.72", "169.254.169.254"]:
                self.assertFalse(permits(policy, "unknown", {}, 443, "egress", ip=address))
            # Application Pods cannot reach public IPs directly, including HTTPS.
            for port in [80, 443, 9999]:
                self.assertFalse(permits(policy, "external", {}, port, "egress", ip="203.0.113.10"))
            self.assertEqual(permits(policy, "kube-system", {}, 80, "egress", ip="169.254.170.23"),
                             s in {"member-service", "review-service", "order-service"})
            self.assertFalse(permits(policy, "kube-system", {}, 443, "egress", ip="169.254.170.23"))

    def test_external_proxy_is_service_specific_and_cannot_reach_private_ips(self):
        for s, docs in self.rendered.items():
            app = self.service_policies[s]
            proxy_labels = labels("egress-proxy", "dev-" + s)
            self.assertEqual(permits(app, s, proxy_labels, 3128, "egress"), s in EXTERNAL_CLIENTS)
            self.assertFalse(permits(app, "unrelated", proxy_labels, 3128, "egress"))
            if s not in EXTERNAL_CLIENTS:
                continue
            proxy = next(p for p in policies(docs) if p["metadata"]["name"].endswith("-egress-proxy"))
            self.assertTrue(permits(proxy, s, service_labels(s), 3128))
            self.assertFalse(permits(proxy, s, service_labels("unrelated"), 3128))
            self.assertFalse(permits(proxy, "unrelated", service_labels(s), 3128))
            self.assertTrue(permits(proxy, "external", {}, 443, "egress", ip="203.0.113.10"))
            self.assertFalse(permits(proxy, "external", {}, 80, "egress", ip="203.0.113.10"))
            for address in ["10.0.4.5", "172.20.10.10", "100.73.67.72", "169.254.169.254"]:
                self.assertFalse(permits(proxy, "unknown", {}, 443, "egress", ip=address))
            config = next(d["data"]["squid.conf"] for d in docs if d["kind"] == "ConfigMap"
                          and "squid.conf" in d.get("data", {}))
            expected = {
                "auth-service": ["kauth.kakao.com", "kapi.kakao.com", "www.googleapis.com"],
                "payment-service": ["api.tosspayments.com"],
                "member-service": ["petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com"],
                "review-service": ["petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com"],
                "order-service": ["petflow-dev-uploads.s3.ap-northeast-2.amazonaws.com"],
                "web": ["business.juso.go.kr", "image.leechs.shop"],
            }[s]
            self.assertIn("acl allowed_domains dstdomain -n " + " ".join(expected) + "\n", config)
            self.assertIn("http_access deny !CONNECT", config)
            self.assertIn("http_access deny !tls_port", config)
            self.assertIn("http_access deny !allowed_domains", config)
            workload = next(d for d in docs if d["kind"] in ["Deployment", "Rollout"]
                            and d["metadata"]["name"] == "generic-service")
            env = {e["name"]: e.get("value") for e in workload["spec"]["template"]["spec"]["containers"][0]["env"]}
            if s == "web":
                self.assertEqual(env["NODE_OPTIONS"], "--use-env-proxy")
                self.assertNotIn("NODE_USE_ENV_PROXY", env)
                self.assertIn("generic-service-egress.web.svc.cluster.local:3128", env["HTTPS_PROXY"])
            else:
                self.assertIn("-Dhttps.proxyHost=generic-service-egress." + s, env["JAVA_TOOL_OPTIONS"])
                self.assertIn("169.254.170.23", env["JAVA_TOOL_OPTIONS"])

    def test_proxy_env_is_present_in_rollouts_and_batch_jobs(self):
        for setting in ["canary.enabled=true", "blueGreen.enabled=true"]:
            docs = render("auth-service", VALUES / "auth-service/values.yaml", [setting])
            rollout = next(d for d in docs if d["kind"] == "Rollout")
            env = rollout["spec"]["template"]["spec"]["containers"][0]["env"]
            self.assertTrue(any(e["name"] == "JAVA_TOOL_OPTIONS" for e in env))
        # No ordinary env: the proxy env must still form a valid YAML list.
        docs = render(settings=["networkPolicy.enabled=true", "networkPolicy.namespaceDefaultDeny=true",
            "externalEgress.enabled=true", "externalEgress.allowedDomains[0]=example.com",
            "cronJobs[0].name=check", "cronJobs[0].schedule=0 * * * *"])
        job = next(d for d in docs if d["kind"] == "CronJob")
        env = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["env"]
        self.assertEqual([e["name"] for e in env], ["JAVA_TOOL_OPTIONS"])

    def test_proxy_rejects_wildcards_and_missing_isolation(self):
        base = ["helm", "template", "check", str(CHART), "--set", "externalEgress.enabled=true"]
        for settings in [[], ["networkPolicy.enabled=true", "networkPolicy.namespaceDefaultDeny=true",
                "externalEgress.allowedDomains[0]=*.amazonaws.com"],
                ["networkPolicy.enabled=true", "networkPolicy.namespaceDefaultDeny=true",
                 "externalEgress.allowedDomains[0]=1.2.3.4"]]:
            cmd = base + [arg for setting in settings for arg in ["--set", setting]]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            self.assertNotEqual(result.returncode, 0)

    def test_metrics_logs_traces_queries_and_rollouts(self):
        for s in API_PORTS:
            self.assertTrue(permits(self.service_policies[s], "observability", PROM, 8080))
            self.assertFalse(permits(self.service_policies[s], "observability", GRAFANA, 8080))
            self.assertTrue(permits(self.service_policies[s], "observability", TEMPO, 4318, "egress"))
            self.assertTrue(permits(self.obs["tempo-ingress"], s, service_labels(s), 4318))
        self.assertTrue(permits(self.db, "observability", PROM, 9187))
        for source, target, port in [
            (ALLOY, "loki-gateway-ingress", 8080), (ALLOY, "tempo-ingress", 4317),
            (GRAFANA, "loki-gateway-ingress", 8080), (GRAFANA, "tempo-ingress", 3200),
            (GRAFANA, "prometheus-ingress", 9090), (loki("gateway"), "loki-ingress", 3100),
            (loki("canary"), "loki-gateway-ingress", 8080), (PROM, "alloy-ingress", 12345),
            (PROM, "loki-canary-ingress", 3500), (PROM, "loki-ingress", 3100),
        ]:
            self.assertTrue(permits(self.obs[target], "observability", source, port))
        self.assertTrue(permits(self.obs["prometheus-ingress"], "argo-rollouts",
                               labels("argo-rollouts", "argo-rollouts"), 9090))
        for policy in self.obs.values():
            self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])
            self.assertFalse(permits(policy, "unrelated", {}, 4318))
        self.assertFalse(permits(self.obs["tempo-ingress"], "auth-service", service_labels("wrong"), 4318))

    def test_alb_paths_and_web_to_future_gateway(self):
        web = self.service_policies["web"]
        for address in ["10.0.0.10", "10.0.1.10"]:
            self.assertTrue(permits(web, "external", {}, 3000, ip=address))
            self.assertTrue(permits(self.obs["alloy-ingress"], "external", {}, 12347, ip=address))
            self.assertTrue(permits(self.obs["grafana-ingress"], "external", {}, 3000, ip=address))
            self.assertFalse(permits(self.obs["prometheus-ingress"], "external", {}, 9090, ip=address))
        self.assertFalse(permits(web, "external", {}, 3000, ip="10.0.4.10"))
        for address in ["10.0.4.10", "10.0.8.10"]:
            self.assertFalse(permits(self.obs["grafana-ingress"], "external", {}, 3000, ip=address))
            self.assertFalse(permits(self.obs["prometheus-ingress"], "external", {}, 9090, ip=address))
        self.assertTrue(permits(web, "api-gateway", service_labels("api-gateway"), 8080, "egress"))

    def test_database_replication_and_operator(self):
        self.assertTrue(permits(self.db, "database", DB, 5432))
        for port in [5432, 8000]:
            self.assertTrue(permits(self.db, "cnpg-system", labels("cloudnative-pg", "cnpg"), port))
            self.assertFalse(permits(self.db, "web", labels("cloudnative-pg", "cnpg"), port))

    def test_policy_matches_deployment_and_rollout_pods(self):
        for settings in [[], ["canary.enabled=true"], ["blueGreen.enabled=true"]]:
            docs = render("product-service", VALUES / "product-service/values.yaml", settings)
            policy = next(p for p in policies(docs) if p["metadata"]["name"] == "generic-service")
            workload = next(x for x in docs if x["kind"] in ["Deployment", "Rollout"])
            self.assertTrue(labels_match(policy["spec"]["podSelector"],
                                         workload["spec"]["template"]["metadata"]["labels"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
