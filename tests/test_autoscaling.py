import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/generic-service"
VALUES = ROOT.parent / "gitops-value/values/dev/services"


def render(service, settings=None):
    command = [
        "helm", "template", f"dev-{service}", str(CHART),
        "--namespace", service, "-f", str(VALUES / service / "values.yaml"),
    ]
    for setting in settings or []:
        command.extend(["--set", setting])
    output = subprocess.check_output(command, text=True)
    return [document for document in yaml.safe_load_all(output) if document]


def by_kind(documents, kind):
    return [document for document in documents if document["kind"] == kind]


class AutoscalingTests(unittest.TestCase):
    def test_existing_hpas_and_pdbs_are_adopted_with_exact_names(self):
        for service in ["auth-service", "member-service", "product-service", "review-service"]:
            documents = render(service)
            hpa = by_kind(documents, "HorizontalPodAutoscaler")[0]
            pdb = by_kind(documents, "PodDisruptionBudget")[0]
            workload = next(d for d in documents if d["kind"] in {"Deployment", "Rollout"}
                            and d["metadata"]["name"] == "generic-service")

            self.assertEqual(hpa["metadata"]["name"], f"{service}-hpa")
            self.assertEqual(hpa["spec"]["minReplicas"], 2)
            self.assertEqual(hpa["spec"]["maxReplicas"], 3)
            self.assertEqual(hpa["spec"]["metrics"][0]["resource"]["target"]["averageUtilization"], 60)
            self.assertEqual(hpa["spec"]["scaleTargetRef"]["kind"],
                             "Rollout" if service == "auth-service" else "Deployment")
            self.assertNotIn("replicas", workload["spec"])
            self.assertEqual(pdb["metadata"]["name"], f"{service}-pdb")
            self.assertEqual(pdb["spec"]["maxUnavailable"], 1)
            self.assertEqual(pdb["spec"]["selector"]["matchLabels"],
                             {"app.kubernetes.io/name": "generic-service"})

    def test_payment_has_single_keda_owner_with_cpu_and_verified_kafka_trigger(self):
        documents = render("payment-service")
        self.assertEqual(by_kind(documents, "HorizontalPodAutoscaler"), [])
        scaled_object = by_kind(documents, "ScaledObject")[0]
        authentication = by_kind(documents, "TriggerAuthentication")[0]
        workload = by_kind(documents, "Rollout")[0]

        self.assertNotIn("replicas", workload["spec"])
        self.assertEqual(scaled_object["metadata"]["name"], "payment-service-scaler")
        self.assertEqual(scaled_object["spec"]["scaleTargetRef"]["kind"], "Rollout")
        self.assertEqual((scaled_object["spec"]["minReplicaCount"],
                          scaled_object["spec"]["maxReplicaCount"]), (1, 3))
        triggers = {trigger["type"]: trigger for trigger in scaled_object["spec"]["triggers"]}
        self.assertEqual(set(triggers), {"cpu", "kafka"})
        self.assertEqual(triggers["kafka"]["metadata"], {
            "bootstrapServers": "pet-subscription-kafka-kafka-bootstrap.kafka.svc:9093",
            "consumerGroup": "payment-service.refund-consumer",
            "topic": "order.item-cancelled",
            "lagThreshold": "10",
            "offsetResetPolicy": "earliest",
            "tls": "enable",
            "sasl": "scram_sha512",
        })
        self.assertEqual(triggers["kafka"]["authenticationRef"]["name"],
                         "payment-service-kafka-auth")
        self.assertEqual(authentication["metadata"]["name"], "payment-service-kafka-auth")
        self.assertEqual(
            {(ref["parameter"], ref["name"], ref["key"])
             for ref in authentication["spec"]["secretTargetRef"]},
            {("username", "kafka-credentials", "username"),
             ("password", "kafka-credentials", "password"),
             ("ca", "kafka-credentials", "ca.crt")},
        )

    def test_legacy_enabled_maps_to_hpa_and_invalid_mode_fails(self):
        output = subprocess.check_output([
            "helm", "template", "legacy", str(CHART),
            "--set", "image.repository=test", "--set", "image.tag=test",
            "--set", "autoscaling.enabled=true",
        ], text=True)
        documents = [document for document in yaml.safe_load_all(output) if document]
        self.assertEqual(len(by_kind(documents, "HorizontalPodAutoscaler")), 1)

        result = subprocess.run([
            "helm", "template", "invalid", str(CHART),
            "--set", "image.repository=test", "--set", "image.tag=test",
            "--set", "autoscaling.mode=both",
        ], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("autoscaling.mode must be one of", result.stderr)


if __name__ == "__main__":
    unittest.main()
