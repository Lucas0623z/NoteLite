"""Save credential-free results of the real HTTP integration suite."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checks = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.checks.append({"test": test.id(), "status": "passed"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.checks.append({"test": test.id(), "status": "failed"})

    def addError(self, test, err):
        super().addError(test, err)
        self.checks.append({"test": test.id(), "status": "error"})


if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(directory), pattern="test_account_service.py")
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    report = {"verifiedAt": datetime.now(timezone.utc).isoformat(), "status": "passed" if result.wasSuccessful() else "failed", "testCount": result.testsRun, "checks": result.checks, "method": "real_loopback_http_sqlite_and_uuid_audio_files", "productionDeploymentVerified": False, "realListeningEngineConnected": False, "testData": "synthetic_accounts_and_generated_wav_no_production_credentials", "sourceSha256": hashlib.sha256((directory / "account_service.py").read_bytes()).hexdigest()}
    (directory / "account-regression-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    sys.exit(0 if result.wasSuccessful() else 1)
