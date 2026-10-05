"""Check automatic preparation and manual execution boundaries together."""
from pathlib import Path
import copy
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return yaml.safe_load((ROOT / path).read_text())


class RepurchaseGitOpsTests(unittest.TestCase):
    def render_shadow(self, tag=None, publication_id=None):
        values = yaml.safe_load((ROOT.parent / "gitops-value/values/dev/services/repurchase/values.yaml").read_text())
        if tag:
            values["image"]["tag"] = tag
        if publication_id:
            for env in values["manualJobs"][0]["podSpec"]["containers"][0]["env"]:
                if env["name"] == "REPURCHASE_PUBLICATION_ID":
                    env["value"] = publication_id
        output = subprocess.check_output([
            "helm", "template", "dev-repurchase", str(ROOT / "charts/generic-service"),
            "-n", "repurchase", "-f", "-"], input=yaml.safe_dump(values), universal_newlines=True)
        docs = [doc for doc in yaml.safe_load_all(output) if doc]
        jobs = [doc for doc in docs if doc["kind"] == "Job"]
        self.assertEqual(len(jobs), 1)
        self.assertFalse(any(doc["kind"] in ("CronJob", "Rollout") for doc in docs))
        self.assertFalse(any(doc["kind"] == "Deployment" and doc["metadata"]["name"] != "generic-service-egress" for doc in docs))
        return jobs[0]

    def test_shadow_uses_one_image_for_batch_and_model_verification(self):
        job = self.render_shadow(tag="new-commit")
        pod = job["spec"]["template"]["spec"]
        batch = pod["containers"][0]
        verify = next(c for c in pod["initContainers"] if c["name"] == "verify-model")
        self.assertEqual(batch["image"], verify["image"])
        self.assertTrue(batch["image"].endswith(":new-commit"))
        for container in pod["containers"] + pod["initContainers"]:
            names = [env["name"] for env in container["env"]]
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
                self.assertEqual(names.count(name), 1)
        old = read("platform/60-cnpg-cluster/manifests/repurchase-shadow-run.yaml")
        for container in old["spec"]["template"]["spec"]["initContainers"][:2]:
            rendered = next(c for c in pod["initContainers"] if c["name"] == container["name"])
            self.assertEqual(rendered["image"], container["image"])
            self.assertEqual(rendered["args"], container["args"])

    def test_new_image_or_execution_id_creates_a_new_suspended_job(self):
        first = self.render_shadow()
        self.assertEqual(first["metadata"]["name"], self.render_shadow()["metadata"]["name"])
        for changed in (self.render_shadow(tag="next-commit"),
                        self.render_shadow(publication_id="next-approved-run")):
            self.assertNotEqual(first["metadata"]["name"], changed["metadata"]["name"])
            self.assertLessEqual(len(changed["metadata"]["name"]), 63)
            self.assertTrue(changed["spec"]["suspend"])
            self.assertEqual(changed["spec"]["backoffLimit"], 0)
            self.assertNotIn("ttlSecondsAfterFinished", changed["spec"])
            self.assertEqual(changed["metadata"]["annotations"]["argocd.argoproj.io/sync-options"], "Prune=false")
        appset = read("applications/appset.yaml")
        rules = appset["spec"]["template"]["spec"]["ignoreDifferences"]
        self.assertIn({"group": "batch", "kind": "Job", "jqPathExpressions": [
            'select(.metadata.labels["petflow.io/manual-job"] == "true") | .spec.suspend']}, rules)

    def test_original_shadow_contract_is_preserved_with_frozen_execution_values(self):
        old = copy.deepcopy(read("platform/60-cnpg-cluster/manifests/repurchase-shadow-run.yaml")["spec"]["template"]["spec"])
        config = read("platform/60-cnpg-cluster/manifests/repurchase-shadow-run-config.yaml")["data"]
        for container in old["containers"]:
            for env in container["env"]:
                if "configMapKeyRef" in env.get("valueFrom", {}):
                    env["value"] = config[env.pop("valueFrom")["configMapKeyRef"]["key"]]
        new = self.render_shadow()["spec"]["template"]["spec"]
        for pod in (old, new):
            for container in pod["containers"] + pod["initContainers"]:
                container.pop("imagePullPolicy", None)
                container["env"].sort(key=lambda e: e["name"])
        self.assertEqual(old, new)

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
