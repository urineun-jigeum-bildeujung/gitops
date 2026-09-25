import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/generic-service"


def render(extra_values=None):
    values = {"image": {"repository": "test", "tag": "latest"}}
    values.update(extra_values or {})
    output = subprocess.check_output(
        ["helm", "template", "test", str(CHART), "-n", "test", "-f", "-"],
        input=yaml.safe_dump(values),
        text=True,
    )
    return [document for document in yaml.safe_load_all(output) if document]


def kinds(documents):
    return [document["kind"] for document in documents]


def cronjob(documents):
    return next(document for document in documents if document["kind"] == "CronJob")


class BatchWorkloadTest(unittest.TestCase):

    def test_default_keeps_deployment_and_service(self):
        rendered = kinds(render())
        self.assertIn("Deployment", rendered)
        self.assertIn("Service", rendered)

    def test_disabled_workload_renders_no_deployment_rollout_or_service(self):
        for rollout_values in ({}, {"canary": {"enabled": True}},
                               {"blueGreen": {"enabled": True}}):
            values = {
                "deployment": {"enabled": False},
                "service": {"enabled": False},
                "metrics": {"enabled": False},
                "cronJobs": [{"name": "daily", "schedule": "0 3 * * *"}],
                **rollout_values,
            }
            rendered = kinds(render(values))
            for kind in ("Deployment", "Rollout", "Service"):
                self.assertNotIn(kind, rendered)
            self.assertIn("CronJob", rendered)

    def test_cronjob_optional_fields_are_omitted_by_default(self):
        job = cronjob(render({"cronJobs": [{"name": "daily", "schedule": "0 3 * * *"}]}))
        for key in ("timeZone", "startingDeadlineSeconds",
                    "successfulJobsHistoryLimit", "failedJobsHistoryLimit"):
            self.assertNotIn(key, job["spec"])
        job_spec = job["spec"]["jobTemplate"]["spec"]
        for key in ("backoffLimit", "activeDeadlineSeconds", "ttlSecondsAfterFinished"):
            self.assertNotIn(key, job_spec)

    def test_cronjob_job_controls_are_rendered_including_zero(self):
        job = cronjob(render({"cronJobs": [{
            "name": "daily",
            "schedule": "0 3 * * *",
            "timeZone": "Asia/Seoul",
            "startingDeadlineSeconds": 600,
            "successfulJobsHistoryLimit": 0,
            "failedJobsHistoryLimit": 3,
            "backoffLimit": 0,
            "activeDeadlineSeconds": 7200,
            "ttlSecondsAfterFinished": 0,
            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
            "volumes": [{"name": "tmp", "emptyDir": {}}],
        }]}))
        spec = job["spec"]
        self.assertEqual(spec["timeZone"], "Asia/Seoul")
        self.assertEqual(spec["startingDeadlineSeconds"], 600)
        self.assertEqual(spec["successfulJobsHistoryLimit"], 0)
        self.assertEqual(spec["failedJobsHistoryLimit"], 3)
        job_spec = spec["jobTemplate"]["spec"]
        self.assertEqual(job_spec["backoffLimit"], 0)
        self.assertEqual(job_spec["activeDeadlineSeconds"], 7200)
        self.assertEqual(job_spec["ttlSecondsAfterFinished"], 0)
        pod_spec = job_spec["template"]["spec"]
        self.assertEqual(pod_spec["volumes"], [{"name": "tmp", "emptyDir": {}}])
        self.assertEqual(pod_spec["containers"][0]["volumeMounts"],
                         [{"name": "tmp", "mountPath": "/tmp"}])

    def test_cronjob_inherits_global_affinity_unless_overridden(self):
        global_affinity = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
            "nodeSelectorTerms": [{"matchExpressions": [
                {"key": "pool", "operator": "In", "values": ["batch"]}]}]}}}
        inherited = cronjob(render({
            "affinity": global_affinity,
            "cronJobs": [{"name": "daily", "schedule": "0 3 * * *"}],
        }))
        pod_spec = inherited["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        self.assertEqual(pod_spec["affinity"], global_affinity)

        override = {"podAntiAffinity": {}}
        overridden = cronjob(render({
            "affinity": global_affinity,
            "cronJobs": [{"name": "daily", "schedule": "0 3 * * *", "affinity": override}],
        }))
        pod_spec = overridden["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        self.assertEqual(pod_spec["affinity"], override)


if __name__ == "__main__":
    unittest.main()
