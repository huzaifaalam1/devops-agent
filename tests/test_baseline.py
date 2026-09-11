"""Release-facing checks. Expected failures name known gaps, not accepted behavior."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from agent.diagnostics import diagnose_failure
from agent.scanner import scan_repo
from agent.detector import detect_stack
from agent.validator import check_application_url, validate_docker
from tests.fixture_support import CASES, materialize

ROOT = Path(__file__).resolve().parents[1]


def cli(command, repo, *options):
    # Real CLI process, bounded externally because production commands lack timeouts.
    env = dict(os.environ, NO_COLOR="1", TERM="dumb", COLUMNS="160")
    return subprocess.run(
        [sys.executable, "-m", "agent.main", command, str(repo), *options],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=20,
    )


def contents(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class RepositoryBaseline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="devops-baseline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, case):
        return materialize(case, self.root / case)

    def assert_refused_without_changes(self, case):
        repo = self.fixture(case)
        before = contents(repo)
        result = cli("dockerize", repo, "--apply")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(contents(repo), before)

    def test_s1_analysis_identifies_next_without_mutating_repo(self):
        repo = self.fixture("minimal")
        before = contents(repo)
        result = cli("analyze", repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Next.js app", result.stdout)
        self.assertIn("npm run dev", result.stdout)
        self.assertEqual(contents(repo), before)

    def test_s2_existing_setup_preserved(self):
        repo = self.fixture("existing-compose")
        before = contents(repo)
        result = cli("dockerize", repo, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(contents(repo), before)

    def test_s6_unknown_stack_refused(self):
        self.assert_refused_without_changes("unsupported")

    def test_database_dependency_identified(self):
        repo = self.fixture("database")
        self.assertIn("PostgreSQL", detect_stack(scan_repo(str(repo)))["services"])

    def test_gap01_no_env_app_does_not_require_env_file(self):
        """G01 / S1,S3: generated setup must not invent an environment prerequisite."""
        repo = self.fixture("minimal")
        result = cli("dockerize", repo, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("env_file:", (repo / "docker-compose.yml").read_text())

    def test_gap02_missing_env_blocked_before_generation(self):
        """G02 / S3: required variable names must be identified before startup."""
        repo = self.fixture("missing-env")
        before = contents(repo)
        result = cli("dockerize", repo, "--apply")
        self.assertIn("APP_GREETING", result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(contents(repo), before)

    def test_gap03_database_generation_outside_scope(self):
        """G03 / S6: database-backed generation is outside the first release."""
        self.assert_refused_without_changes("database")

    def test_gap04_incompatible_runtime_refused(self):
        """G04 / S6: Node 18-only metadata is incompatible with Node 22 setup."""
        self.assert_refused_without_changes("incompatible-runtime")

    def test_gap05_missing_lockfile_refused(self):
        """G05 / S6: the initial scope requires an npm lockfile."""
        self.assert_refused_without_changes("missing-lockfile")

    def test_gap06_yarn_refused(self):
        """G06 / S6: do not generate npm setup for a declared yarn project."""
        self.assert_refused_without_changes("yarn")

    def test_gap07_multi_component_requires_selection(self):
        """G07 / S7: ambiguous app roots must not receive an app-less Compose file."""
        self.assert_refused_without_changes("multi-component")

    def test_gap08_partial_setup_reported_as_incomplete(self):
        """G08 / S8: a Dockerfile alone must not be a successful setup outcome."""
        self.assert_refused_without_changes("partial-docker")


class FixtureIntegrity(unittest.TestCase):
    def test_manifest_covers_all_release_scenarios(self):
        self.assertEqual({case["scenario"] for case in CASES}, {f"S{i}" for i in range(1, 9)})

    def test_materialized_lockfiles_match_declared_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            for case in CASES:
                repo = materialize(case["id"], Path(directory) / case["id"])
                for lock_path in repo.rglob("package-lock.json"):
                    with self.subTest(case=case["id"], path=lock_path.name):
                        package = json.loads(lock_path.with_name("package.json").read_text())
                        lock = json.loads(lock_path.read_text())
                        self.assertEqual(package["dependencies"], lock["packages"][""]["dependencies"])
                        for name, version in package["dependencies"].items():
                            self.assertEqual(lock["packages"][f"node_modules/{name}"]["version"], version)


class HttpBaseline(unittest.TestCase):
    """Real loopback HTTP checks, no Docker and no external network requests."""

    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                code = {"/ready": 200, "/broken": 500, "/redirect": 302, "/get-only": 405}[self.path]
                self.send_response(code)
                if code == 302:
                    self.send_header("Location", "/ready")
                self.end_headers()

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"fixture-ready")

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_http_success(self):
        self.assertTrue(check_application_url(self.url + "/ready")["healthy"])

    def test_s4_http_500_is_failure(self):
        result = check_application_url(self.url + "/broken")
        self.assertFalse(result["healthy"])
        self.assertEqual(result["status_code"], 500)

    def test_redirect_is_not_claimed_as_ready(self):
        result = check_application_url(self.url + "/redirect")
        self.assertFalse(result["healthy"])
        self.assertEqual(result["redirect_url"], "/ready")

    def test_head_405_falls_back_to_get(self):
        self.assertTrue(check_application_url(self.url + "/get-only")["healthy"])


class FailureBaseline(unittest.TestCase):
    """Synthetic command responses exercise error handling without touching workloads."""

    def test_s4_docker_unavailable_is_failure(self):
        result = {"command": "docker compose config", "success": False,
                  "returncode": 1, "stdout": "", "stderr": "Cannot connect to the Docker daemon"}
        with tempfile.TemporaryDirectory() as repo, patch("agent.validator.run_command", return_value=result):
            validation = validate_docker(repo)
        self.assertFalse(validation["success"])
        self.assertEqual(validation["phase"], "docker_engine")

    def test_s4_startup_failure_is_not_success(self):
        def command(args, cwd):
            failed = "up" in args
            return {"command": " ".join(args), "success": not failed,
                    "returncode": 1 if failed else 0, "stdout": "",
                    "stderr": "Intentional startup failure" if failed else ""}
        with tempfile.TemporaryDirectory() as repo, patch("agent.validator.run_command", side_effect=command):
            validation = validate_docker(repo, run=True)
        self.assertFalse(validation["success"])
        self.assertEqual(validation["phase"], "startup")

    def test_known_error_patterns_produce_actionable_diagnoses(self):
        for evidence, category in (
            ("Required environment variable APP_GREETING is missing", "missing_environment"),
            ("port is already allocated", "port_conflict"),
            ("connection refused", "connection_failure"),
            ("Bundler::GemNotFound", "ruby_dependencies"),
        ):
            with self.subTest(category=category):
                result = diagnose_failure({"success": False, "logs": evidence})
                self.assertEqual(result["type"], category)
                self.assertTrue(result["suggested_actions"])

    def test_s5_conflict_declined_does_not_stop_another_project(self):
        # Exercise the actual CLI confirmation path with fabricated Docker responses.
        from typer.testing import CliRunner
        from agent.main import app
        failed = {"success": False, "phase": "startup", "logs": "port is already allocated",
                  "results": [{"command": "docker compose up -d", "stdout": "",
                               "stderr": "Bind for 0.0.0.0:3000 failed: port is already allocated"}]}
        conflict = {"container_name": "unrelated-app", "project_name": "unrelated"}
        with tempfile.TemporaryDirectory() as directory:
            repo = materialize("port-conflict", Path(directory) / "app")
            with patch("agent.main.validate_docker", return_value=failed), \
                 patch("agent.main.find_compose_project_using_port", return_value=conflict), \
                 patch("agent.main.bring_down_compose_project") as stop:
                result = CliRunner().invoke(app, ["validate", str(repo), "--run"], input="n\n")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("Bring down", result.output)
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
