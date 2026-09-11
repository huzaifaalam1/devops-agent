"""Evidence and mutation-boundary regressions for step 3."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.detector import detect_stack
from agent.scanner import scan_repo
from agent.understanding import node22_support
from tests.fixture_support import materialize
from tests.test_baseline import ROOT, cli, contents


class UnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="devops-understanding-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = materialize("minimal", self.root / "app")

    def analysis(self):
        return detect_stack(scan_repo(str(self.repo)))

    def codes(self):
        return {b["code"] for b in self.analysis()["project"]["blockers"]}

    def package(self, change):
        path = self.repo / "package.json"
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))
        lockpath = self.repo / "package-lock.json"
        lock = json.loads(lockpath.read_text())
        for key in ("dependencies", "devDependencies", "optionalDependencies", "engines"):
            lock["packages"][""][key] = data.get(key, {})
        lockpath.write_text(json.dumps(lock))

    def test_eligible_project_has_sourced_findings_and_separate_unknowns(self):
        project = self.analysis()["project"]
        self.assertEqual(project["eligibility"], "eligible")
        self.assertTrue(project["unknowns"])
        self.assertTrue(project["assumptions"])
        for finding in project["findings"]:
            self.assertIn(finding["certainty"], {"confirmed", "inferred"})
            self.assertTrue((self.repo / finding["evidence"][0]["path"]).is_file())

    def test_json_interface_reports_blockers_without_values(self):
        (self.repo / ".env.example").write_text("REQUIRED=\n")
        (self.repo / ".env").write_text("PRIVATE_VALUE=never-print-this\n")
        result = subprocess.run([sys.executable, "-m", "agent.main", "analyze", str(self.repo), "--json"],
                                cwd=ROOT, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["analysis"]["project"]["eligibility"], "needs_input")
        self.assertNotIn("never-print-this", result.stdout)
        for blocker in report["analysis"]["project"]["blockers"]:
            self.assertTrue(blocker["next_action"])
            self.assertTrue(blocker["evidence"])

    def test_description_is_not_dependency_evidence(self):
        self.package(lambda p: (p["dependencies"].pop("next"), p.update(description='next vue pg redis aws-sdk')))
        result = self.analysis()
        self.assertNotIn("Next.js app", result["detected"])
        self.assertNotIn("Vue app", result["detected"])
        self.assertEqual(result["services"], [])

    def test_malformed_and_duplicate_json_are_actionable_without_mutation(self):
        for content in ('{"private": "do-not-echo",', '{"dependencies": {}, "dependencies": {}}', '[]'):
            with self.subTest(content=content):
                (self.repo / "package.json").write_text(content)
                before = contents(self.repo)
                result = cli("dockerize", self.repo, "--apply")
                self.assertEqual(result.returncode, 1)
                self.assertIn("invalid_metadata", result.stdout)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("do-not-echo", result.stdout + result.stderr)
                self.assertEqual(contents(self.repo), before)

    def test_bad_dependency_shape_is_a_blocker(self):
        self.package(lambda p: p.update(dependencies=[]))
        self.assertIn("invalid_dependencies", self.codes())

    def test_conflicting_lockfiles_require_input(self):
        (self.repo / "yarn.lock").write_text("# presence conflicts with npm\n")
        self.assertIn("package_manager", self.codes())
        self.assertEqual(self.analysis()["project"]["eligibility"], "needs_input")

    def test_stale_lockfile_blocks_generation(self):
        lockpath = self.repo / "package-lock.json"
        lock = json.loads(lockpath.read_text())
        lock["packages"][""]["dependencies"]["next"] = "0.0.0"
        lockpath.write_text(json.dumps(lock))
        self.assertIn("lockfile_mismatch", self.codes())
        self.assertNotEqual(cli("dockerize", self.repo, "--apply").returncode, 0)

    def test_startup_and_port_uncertainty_block_generation(self):
        for script in ("node server.js", "next dev --port 4000", "next dev && echo done", "next dev --hostname 127.0.0.1"):
            with self.subTest(script=script):
                self.package(lambda p: p.update(scripts={"dev": script}))
                before = contents(self.repo)
                self.assertNotEqual(cli("dockerize", self.repo, "--apply").returncode, 0)
                self.assertEqual(contents(self.repo), before)

    def test_missing_engine_requires_clarification(self):
        self.package(lambda p: p.pop("engines"))
        self.assertIn("unknown_runtime", self.codes())

    def test_runtime_file_conflict_is_surfaced(self):
        (self.repo / ".nvmrc").write_text("18\n")
        self.assertIn("runtime_conflict", self.codes())

    def test_environment_precedence_and_quoted_empty_values(self):
        (self.repo / ".env.example").write_text("APP_GREETING=\n")
        (self.repo / ".env").write_text("APP_GREETING=lower-priority\n")
        (self.repo / ".env.local").write_text('APP_GREETING="" # deliberately blank\n')
        self.assertIn("environment_missing", self.codes())
        (self.repo / ".env.local").write_text('APP_GREETING="private-value" # provided\n')
        result = self.analysis()["project"]
        self.assertEqual(result["eligibility"], "eligible")
        self.assertNotIn("private-value", json.dumps(result))

    def test_config_guard_without_example_is_inferred_and_blocked(self):
        (self.repo / "next.config.mjs").write_text('if (!process.env.TOKEN) { throw new Error("missing"); }\nexport default {};')
        self.assertIn("environment_guard", self.codes())
        findings = self.analysis()["project"]["findings"]
        self.assertTrue(any(f["name"] == "referenced_variable" and f["certainty"] == "inferred" for f in findings))

    def test_configuration_is_never_executed(self):
        (self.repo / "next.config.mjs").write_text('throw new Error("must-not-execute");')
        result = cli("analyze", self.repo)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("must-not-execute", result.stdout + result.stderr)

    def test_dynamic_environment_is_unknown(self):
        (self.repo / "next.config.mjs").write_text('const key = "TOKEN"; export default { x: process.env[key] };')
        self.assertIn("dynamic_environment", self.codes())

    def test_docker_runtime_conflict_and_multiple_variants(self):
        (self.repo / "Dockerfile").write_text("FROM node:18\n")
        (self.repo / "compose.yaml").write_text("services: {}\n")
        self.assertIn("docker_runtime_conflict", self.codes())
        (self.repo / "compose.mac.yaml").write_text("services: {}\n")
        self.assertIn("compose_selection", self.codes())

    def test_filename_mentions_do_not_count_as_infrastructure(self):
        (self.repo / "compose-notes.md").write_text("notes")
        (self.repo / "Dockerfile.backup.txt").write_text("notes")
        self.assertEqual(scan_repo(str(self.repo))["compose_files"], [])
        self.assertEqual(scan_repo(str(self.repo))["dockerfiles"], [])

    def test_nested_application_is_reported_with_concrete_next_action(self):
        nested = materialize("minimal", self.repo / "apps" / "web")
        project = self.analysis()["project"]
        self.assertIn("apps/web", project["application_candidates"])
        self.assertTrue(any("apps/web" in b["next_action"] for b in project["blockers"]))
        self.assertEqual(detect_stack(scan_repo(str(nested)))["project"]["eligibility"], "eligible")

    def test_scan_prunes_dependencies_and_does_not_follow_directory_symlinks(self):
        materialize("minimal", self.repo / "node_modules" / "fake")
        external = materialize("minimal", self.root / "external")
        (self.repo / "linked").symlink_to(external, target_is_directory=True)
        self.assertEqual(scan_repo(str(self.repo))["components"], [])

    def test_external_manifest_symlink_is_blocked(self):
        outside = self.root / "private.json"
        outside.write_text('{"private": "not-to-be-read"}')
        (self.repo / "package.json").unlink()
        (self.repo / "package.json").symlink_to(outside)
        result = cli("dockerize", self.repo, "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside", result.stdout)
        self.assertNotIn("not-to-be-read", result.stdout + result.stderr)

    def test_invalid_path_is_clean_cli_error(self):
        result = cli("analyze", self.root / "absent")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_runtime_validation_cannot_bypass_eligibility(self):
        from agent.main import app
        from typer.testing import CliRunner
        self.package(lambda p: p.update(packageManager="yarn@1.22.22"))
        with patch("agent.main.validate_docker") as execute:
            result = CliRunner().invoke(app, ["validate", str(self.repo), "--run"])
        self.assertEqual(result.exit_code, 1)
        execute.assert_not_called()

    def test_config_only_validation_remains_available_for_analysis_only_stacks(self):
        from agent.main import app
        from typer.testing import CliRunner
        (self.repo / "compose.yaml").write_text("services: {}\n")
        self.package(lambda p: p.update(packageManager="yarn@1.22.22"))
        outcome = {"success": True, "phase": "config", "results": []}
        with patch("agent.main.validate_docker", return_value=outcome) as execute:
            result = CliRunner().invoke(app, ["validate", str(self.repo)])
        self.assertEqual(result.exit_code, 0, result.output)
        execute.assert_called_once()


class RuntimeRangeTests(unittest.TestCase):
    def test_common_full_node22_ranges(self):
        for spec in ("22.x", "22", "^22.0.0", ">=20.9.0", ">=20 <23", "*"):
            with self.subTest(spec=spec):
                self.assertEqual(node22_support(spec), "compatible")

    def test_outside_or_unresolved_ranges(self):
        for spec in ("18.x", "^20.0.0", ">=24", "<22"):
            with self.subTest(spec=spec):
                self.assertEqual(node22_support(spec), "incompatible")
        for spec in ("22.14.0", "^22.1.0", "latest", "20 || 22", ">=22.1.0", None):
            with self.subTest(spec=spec):
                self.assertEqual(node22_support(spec), "unknown")
