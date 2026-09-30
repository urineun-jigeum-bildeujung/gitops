"""Offline tests of the service bootstrap gate; never contact a cluster."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RecoveryGateTests(unittest.TestCase):
    def invoke(self, phase="ready", failed_store="", redis_ready="1"):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "kubectl"
            binary.write_text("""#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if 'configmap' in args:
    print(os.environ['TEST_PHASE'])
elif 'wait' in args:
    if os.environ['TEST_FAILED_STORE'] and os.environ['TEST_FAILED_STORE'] in args:
        sys.exit(1)
elif 'statefulset' in args:
    print(os.environ['TEST_REDIS_READY'])
else:
    sys.exit(2)
""")
            binary.chmod(0o755)
            return subprocess.run(["bash", str(ROOT / "scripts/verify-stateful-recovery.sh")],
                                  env=dict(os.environ, PATH=directory + ":" + os.environ["PATH"],
                                           TEST_PHASE=phase, TEST_FAILED_STORE=failed_store, TEST_REDIS_READY=redis_ready),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

    def test_partial_restore_blocks_bootstrap(self):
        self.assertNotEqual(self.invoke(phase="restoring").returncode, 0)

    def test_unready_store_blocks_bootstrap(self):
        self.assertNotEqual(self.invoke(failed_store="kafka/pet-subscription-kafka").returncode, 0)
        self.assertNotEqual(self.invoke(redis_ready="0").returncode, 0)

    def test_ready_cohort_allows_bootstrap(self):
        self.assertEqual(self.invoke().returncode, 0)


if __name__ == "__main__":
    unittest.main()
