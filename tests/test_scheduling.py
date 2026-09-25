import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/generic-service"


def render(extra_values=None):
    values = {
        "image": {"repository": "test", "tag": "latest"},
        "replicaCount": 2,
    }
    values.update(extra_values or {})
    output = subprocess.check_output(
        ["helm", "template", "test", str(CHART), "-n", "test", "-f", "-"],
        input=yaml.safe_dump(values),
        text=True,
    )
    return [document for document in yaml.safe_load_all(output) if document]


def workload(documents):
    return next(document for document in documents
                if document["kind"] in {"Deployment", "Rollout"})


class SchedulingTest(unittest.TestCase):

    def test_default_omits_affinity(self):
        pod_spec = workload(render())["spec"]["template"]["spec"]
        self.assertNotIn("affinity", pod_spec)

    def test_affinity_is_rendered_for_deployment_and_rollout(self):
        affinity = {
            "podAntiAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": [{
                    "labelSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "generic-service",
                            "app.kubernetes.io/instance": "dev-api-gateway",
                        },
                    },
                    "topologyKey": "kubernetes.io/hostname",
                }],
            },
        }
        for rollout_values in ({}, {"canary": {"enabled": True}}):
            values = {"affinity": affinity, **rollout_values}
            pod_spec = workload(render(values))["spec"]["template"]["spec"]
            self.assertEqual(pod_spec["affinity"], affinity)


    def test_canary_analysis_handles_no_traffic(self):
        documents = render({"canary": {"enabled": True, "analysis": {"enabled": True}}})
        analysis = next(document for document in documents
                        if document["kind"] == "AnalysisTemplate")
        query = analysis["spec"]["metrics"][0]["provider"]["prometheus"]["query"]
        self.assertIn("or vector(0)", query)
        self.assertIn("clamp_min", query)


if __name__ == "__main__":
    unittest.main()
