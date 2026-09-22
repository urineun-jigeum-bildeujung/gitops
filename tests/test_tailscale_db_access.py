import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_all(path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


class TailscaleDatabaseAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.operator_app = load_all(
            ROOT / "platform/40-tailscale-operator/application.yaml")[0]
        cls.oauth = load_all(
            ROOT / "platform/91-external-secrets-config/manifests/tailscale-operator-oauth.yaml")[0]
        resources = load_all(
            ROOT / "platform/70-tailscale-db-access/manifests/db-access.yaml")
        cls.proxy_class = next(doc for doc in resources if doc["kind"] == "ProxyClass")
        cls.service = next(doc for doc in resources if doc["kind"] == "Service")

    def test_sync_order_is_secret_then_operator_then_service(self):
        external_secrets_app = load_all(
            ROOT / "platform/91-external-secrets-config/application.yaml")[0]
        access_app = load_all(
            ROOT / "platform/70-tailscale-db-access/application.yaml")[0]
        waves = [int(app["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])
                 for app in (external_secrets_app, self.operator_app, access_app)]
        self.assertEqual(waves, [3, 4, 5])

    def test_operator_uses_precreated_secret_and_expected_tags(self):
        source = self.operator_app["spec"]["source"]
        self.assertEqual(source["repoURL"], "https://pkgs.tailscale.com/helmcharts")
        self.assertEqual(source["targetRevision"], "1.102.4")
        values = yaml.safe_load(source["helm"]["values"])
        self.assertNotIn("oauth", values)
        self.assertEqual(values["operatorConfig"]["defaultTags"], ["tag:k8s-operator"])
        self.assertEqual(values["proxyConfig"]["defaultTags"], "tag:k8s")
        self.assertEqual(values["apiServerProxyConfig"]["mode"], "false")

    def test_external_secret_matches_official_chart_keys(self):
        self.assertEqual(self.oauth["metadata"]["namespace"], "tailscale")
        self.assertEqual(self.oauth["spec"]["target"]["name"], "operator-oauth")
        self.assertEqual({item["secretKey"] for item in self.oauth["spec"]["data"]},
                         {"client_id", "client_secret"})
        for item in self.oauth["spec"]["data"]:
            self.assertEqual(item["remoteRef"]["key"],
                             "petflow/tailscale/kubernetes-operator-oauth")
            self.assertEqual(item["remoteRef"]["property"], item["secretKey"])

    def test_service_targets_only_cnpg_primary_through_tailscale(self):
        self.assertEqual(self.service["metadata"]["namespace"], "database")
        self.assertEqual(self.service["spec"]["type"], "LoadBalancer")
        self.assertEqual(self.service["spec"]["loadBalancerClass"], "tailscale")
        self.assertEqual(self.service["spec"]["selector"], {
            "cnpg.io/cluster": "petflow-db",
            "cnpg.io/instanceRole": "primary",
        })
        self.assertEqual(self.service["spec"]["ports"], [{
            "name": "postgres", "protocol": "TCP", "port": 5432, "targetPort": 5432,
        }])
        self.assertEqual(self.service["metadata"]["labels"]["tailscale.com/proxy-class"],
                         self.proxy_class["metadata"]["name"])

    def test_proxy_class_supplies_network_policy_identity(self):
        labels = self.proxy_class["spec"]["statefulSet"]["pod"]["labels"]
        self.assertEqual(labels, {
            "app.kubernetes.io/name": "tailscale-db-proxy",
            "app.kubernetes.io/instance": "petflow-dev-db",
        })


if __name__ == "__main__":
    unittest.main()
