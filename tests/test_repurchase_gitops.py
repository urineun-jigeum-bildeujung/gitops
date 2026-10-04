"""Check automatic preparation and manual execution boundaries together."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return yaml.safe_load((ROOT / path).read_text())


class RepurchaseGitOpsTests(unittest.TestCase):
    def test_manual_execution_is_preserved_after_suspended_creation(self):
        job = read("platform/60-cnpg-cluster/manifests/repurchase-shadow-run.yaml")
        app = read("platform/60-cnpg-cluster/application.yaml")
        self.assertTrue(job["spec"]["suspend"])
        self.assertNotIn("ttlSecondsAfterFinished", job["spec"])
        self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/ignore-healthcheck"], "true")
        self.assertEqual(app["spec"]["ignoreDifferences"], [{
            "group": "batch", "kind": "Job", "name": job["metadata"]["name"],
            "namespace": "repurchase", "jsonPointers": ["/spec/suspend"]}])
        self.assertIn("RespectIgnoreDifferences=true", app["spec"]["syncPolicy"]["syncOptions"])

    def test_job_environment_references_are_created_by_platform(self):
        job = read("platform/60-cnpg-cluster/manifests/repurchase-shadow-run.yaml")
        config = read("platform/60-cnpg-cluster/manifests/repurchase-shadow-run-config.yaml")
        secret = read("platform/91-external-secrets-config/manifests/app-bindings-repurchase-shadow.yaml")
        spec = job["spec"]["template"]["spec"]
        self.assertEqual(spec["serviceAccountName"], "generic-service")
        for env in spec["containers"][0]["env"]:
            source = env.get("valueFrom", {})
            if "configMapKeyRef" in source:
                ref = source["configMapKeyRef"]
                self.assertEqual(ref["name"], config["metadata"]["name"])
                self.assertTrue(config["data"][ref["key"]])
            if "secretKeyRef" in source:
                ref = source["secretKeyRef"]
                self.assertEqual(ref["name"], secret["spec"]["target"]["name"])
                self.assertIn(ref["key"], secret["spec"]["target"]["template"]["data"])
        self.assertTrue(spec["containers"][0]["volumeMounts"][0]["readOnly"])

    def test_validation_and_retry_jobs_are_outside_automatic_sync(self):
        for name in ("repurchase-contract-check", "repurchase-model-access-check", "repurchase-shadow-run-retry"):
            self.assertEqual(read("operations/" + name + ".yaml")["kind"], "Job")
        values = yaml.safe_load((ROOT.parent / "gitops-value/values/dev/services/repurchase/values.yaml").read_text())
        self.assertEqual(values["cronJobs"], [])


if __name__ == "__main__":
    unittest.main()
