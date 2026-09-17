"""Troubleshooting contracts: evidence, uncertainty, precedence and CLI access."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner
from agent.diagnostics import diagnose_failure
from agent.main import app
from tests.fixture_support import materialize


class DiagnosticTests(unittest.TestCase):
    def test_catalog_actions_have_evidence_impact_and_verification(self):
        cases = [
            ("startup", "Host port 3000 is already in use.", "port_conflict"),
            ("startup", "Required environment variable APP_GREETING is missing", "missing_environment"),
            ("build", "npm error EUSAGE package-lock.json out of sync", "dependency_installation"),
            ("services", "connect ECONNREFUSED db:5432", "connection_failure"),
            ("docker_engine", "Cannot connect to the Docker daemon", "docker_unavailable"),
            ("host", "Executable is missing or cannot be started.", "docker_unavailable"),
            ("build", "no space left on device", "docker_storage"),
            ("services", "Bundler::GemNotFound", "ruby_dependencies"),
        ]
        for phase, error, expected in cases:
            with self.subTest(expected=expected):
                diagnosis = diagnose_failure({"success": False, "phase": phase, "error": error})
                self.assertEqual(diagnosis["type"], expected)
                self.assertEqual(diagnosis["evidence"], [{"source": "error", "excerpt": error}])
                for key in ("symptoms", "likely_causes", "suggested_actions", "expected_impact", "verification", "confidence", "uncertainty"):
                    self.assertTrue(diagnosis[key], key)
                self.assertFalse(diagnosis["automatic_repair"])

    def test_success_has_no_diagnosis(self):
        self.assertIsNone(diagnose_failure({"success": True, "logs": "connection refused"}))

    def test_successful_command_warning_is_not_evidence(self):
        diagnosis = diagnose_failure({"success": False, "phase": "application", "results": [
            {"success": True, "stdout": "npm error connection refused"}], "error": "unrecognized fault"})
        self.assertEqual(diagnosis["type"], "unknown")
        self.assertEqual(diagnosis["confidence"], "low")
        self.assertEqual(diagnosis["evidence"][0]["excerpt"], "unrecognized fault")

    def test_missing_configuration_is_not_inferred_from_generic_env_mention(self):
        self.assertEqual(diagnose_failure({"success": False, "logs": "environment variable loaded"})["type"], "unknown")

    def test_build_errors_are_not_inferred_from_runtime_package_manager_text(self):
        self.assertEqual(diagnose_failure({"success": False, "phase": "services", "logs": "npm error command failed"})["type"], "unknown")

    def test_failed_command_evidence_has_source(self):
        diagnosis = diagnose_failure({"success": False, "phase": "build", "results": [
            {"success": False, "stderr": "npm error ERESOLVE unable to resolve dependency tree"}]})
        self.assertEqual(diagnosis["type"], "dependency_installation")
        self.assertEqual(diagnosis["evidence"][0]["source"], "results[0].stderr")
        self.assertEqual(diagnosis["confidence"], "medium")

    def test_cleanup_failure_takes_priority_over_original_failure_logs(self):
        diagnosis = diagnose_failure({"success": False, "phase": "cleanup", "cleanup": {"status": "failed"},
                                      "logs": "port is already allocated"})
        self.assertEqual(diagnosis["type"], "cleanup_failure")
        self.assertIn("project label", diagnosis["suggested_actions"][0])

    def test_authentication_uses_http_status_evidence(self):
        for status in (401, 403):
            diagnosis = diagnose_failure({"success": False, "phase": "application", "application_check": {"status_code": status}})
            self.assertEqual(diagnosis["type"], "http_authentication")
            self.assertEqual(diagnosis["evidence"][0]["excerpt"], str(status))

    def test_probe_connection_error_does_not_invent_dependency_failure(self):
        diagnosis = diagnose_failure({"success": False, "phase": "application", "application_check": {"error": "Connection refused"}})
        self.assertEqual(diagnosis["type"], "unknown")

    def test_large_unknown_evidence_is_bounded_and_does_not_become_actions(self):
        diagnosis = diagnose_failure({"success": False, "logs": "run destructive command " * 10000})
        self.assertEqual(diagnosis["type"], "unknown")
        self.assertLessEqual(len(diagnosis["evidence"][0]["excerpt"]), 500)
        self.assertNotIn("destructive command", diagnosis["suggested_actions"][0])

    def test_cli_summary_verbose_and_json_preserve_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = materialize("existing-compose", Path(directory) / "app")
            report = {"success": False, "phase": "startup", "error": "Host port 3000 is already in use.",
                      "logs": "detail-only-marker", "results": []}
            for flag in ([], ["--verbose"], ["--json"], ["--json", "--verbose"]):
                with self.subTest(flag=flag), patch("agent.main.validate_docker", return_value=dict(report)):
                    result = CliRunner().invoke(app, ["validate", str(repo), "--run", *flag])
                self.assertEqual(result.exit_code, 1, result.output)
                if "--json" in flag:
                    self.assertEqual(json.loads(result.output)["diagnosis"]["type"], "port_conflict")
                else:
                    self.assertIn("Action:", result.output)
                    self.assertIn("Verify:", result.output)
                    self.assertEqual("detail-only-marker" in result.output, "--verbose" in flag)

    def test_missing_environment_preflight_diagnosis_without_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = materialize("missing-env", Path(directory) / "app")
            with patch("agent.main.validate_docker") as docker:
                result = CliRunner().invoke(app, ["validate", str(repo), "--run", "--json"])
            docker.assert_not_called()
            self.assertEqual(result.exit_code, 1)
            report = json.loads(result.output)
            self.assertEqual(report["phase"], "eligibility")
            self.assertEqual(report["diagnosis"]["type"], "missing_environment")
            self.assertIn("APP_GREETING", report["diagnosis"]["evidence"][0]["excerpt"])

    def test_runtime_project_identifier_is_not_repository_analysis(self):
        diagnosis = diagnose_failure({"success": False, "project": "devops-validation-123", "error": "Host port 3000 is already in use."})
        self.assertEqual(diagnosis["type"], "port_conflict")

    def test_generic_npm_script_failure_does_not_claim_installation_failure(self):
        diagnosis = diagnose_failure({"success": False, "phase": "build", "logs": "npm error command failed: npm run build"})
        self.assertEqual(diagnosis["type"], "unknown")
