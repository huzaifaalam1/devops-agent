"""Run the offline suite and optionally retain machine-readable evidence."""

import argparse
import importlib.metadata
import hashlib
import json
import platform
import re
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tests import test_baseline


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = []

    def addSuccess(self, test):
        self.passed.append(test.id())
        super().addSuccess(test)

    def addExpectedFailure(self, test, error):
        # A broken fixture/import/command is an error, not evidence of a known gap.
        if not issubclass(error[0], AssertionError):
            self.addError(test, error)
        else:
            super().addExpectedFailure(test, error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_baseline)
    result = unittest.TextTestRunner(verbosity=2, resultclass=Results).run(suite)
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "agent_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "agent_tracked_diff": subprocess.check_output(["git", "diff", "HEAD", "--", "agent"], text=True),
        "python": platform.python_version(), "platform": platform.platform(),
        "dependencies": {name: importlib.metadata.version(name) for name in ("typer", "rich", "requests")},
        "tests_run": result.testsRun,
        "passed": result.passed,
        "known_gaps": [{"test": test.id(), "evidence": trace} for test, trace in result.expectedFailures],
        "unexpected_failures": [{"test": test.id(), "evidence": trace} for test, trace in result.failures + result.errors],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "baseline_matches": result.wasSuccessful(),
        "release_ready": False,
        "coverage_limit": "CLI analysis/generation, local HTTP, and simulated Docker errors. Not an end-to-end Docker acceptance run.",
    }
    root = Path(__file__).resolve().parents[1]
    report["fixture_and_test_sha256"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "tests").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(report, indent=2).replace(str(root), "<repo>")
        encoded = re.sub(r"/(?:private/)?var/folders/[^\s\"']+/devops-baseline-[^/\s\"']+", "<temporary-fixture>", encoded)
        args.output.write_text(encoded + "\n")
    print(f"\n{len(result.passed)} passing; {len(result.expectedFailures)} known gaps; release_ready={report['release_ready']}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
