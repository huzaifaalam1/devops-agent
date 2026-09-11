import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.docker_generator import propose_docker_files, apply_docker_proposal
from tests.fixture_support import materialize
from tests.test_baseline import cli, contents


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="devops-proposal-")
        self.addCleanup(self.temp.cleanup)
        self.repo = materialize("minimal", Path(self.temp.name) / "app")

    def test_default_cli_is_read_only_and_shows_diff(self):
        before = contents(self.repo)
        result = cli("dockerize", self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("+++ b/Dockerfile", result.stdout)
        self.assertIn("npm ci", result.stdout)
        self.assertIn("Preview only", result.stdout)
        self.assertEqual(before, contents(self.repo))

    def test_json_preview_can_be_applied_with_reviewed_id(self):
        preview = cli("dockerize", self.repo, "--json")
        plan = json.loads(preview.stdout)
        self.assertEqual(plan["status"], "ready")
        result = cli("dockerize", self.repo, "--apply", "--expect", plan["id"], "--json")
        self.assertEqual(result.returncode, 0, result.stdout)
        applied = json.loads(result.stdout)["applied"]
        self.assertEqual(set(applied["created"]), {"Dockerfile", "docker-compose.yml", ".dockerignore"})
        for change in plan["changes"]:
            self.assertEqual((self.repo / change["path"]).read_text(), change["content"])

    def test_repeat_application_is_noop(self):
        apply_docker_proposal(propose_docker_files(self.repo))
        before = contents(self.repo)
        result = cli("dockerize", self.repo, "--apply", "--json")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "unchanged")
        self.assertEqual(before, contents(self.repo))

    def test_lockfile_is_preserved_and_npm_ci_includes_dev_dependencies(self):
        before = (self.repo / "package-lock.json").read_bytes()
        apply_docker_proposal(propose_docker_files(self.repo))
        self.assertEqual(before, (self.repo / "package-lock.json").read_bytes())
        dockerfile = (self.repo / "Dockerfile").read_text()
        self.assertIn("npm ci --include=dev", dockerfile)
        self.assertNotIn("npm install", dockerfile)
        self.assertIn('CMD ["npm", "run", "dev"]', dockerfile)
        self.assertIn("127.0.0.1:3000:3000", (self.repo / "docker-compose.yml").read_text())

    def test_dotenv_values_are_not_in_proposal_and_precedence_files_are_mounted(self):
        (self.repo / ".env.example").write_text("TOKEN=\n")
        (self.repo / ".env").write_text("TOKEN=secret-base\n")
        (self.repo / ".env.local").write_text("TOKEN=secret-override\n")
        plan = propose_docker_files(self.repo)
        self.assertEqual(plan["status"], "ready")
        encoded = json.dumps(plan)
        self.assertNotIn("secret-base", encoded)
        self.assertNotIn("secret-override", encoded)
        compose = next(c["content"] for c in plan["changes"] if c["path"] == "docker-compose.yml")
        self.assertIn("target: /app/.env.local", compose)
        self.assertIn("target: /app/.env", compose)
        self.assertIn("create_host_path: false", compose)
        self.assertNotIn("env_file:", compose)
        self.assertNotIn(".env.example", compose)
        apply_docker_proposal(plan)
        self.assertEqual((self.repo / ".env.local").read_text(), "TOKEN=secret-override\n")

    def test_existing_ignore_rules_have_reviewed_append_only_update(self):
        original = "custom-directory\n!.env\n"
        (self.repo / ".dockerignore").write_text(original)
        plan = propose_docker_files(self.repo)
        change = next(c for c in plan["changes"] if c["path"] == ".dockerignore")
        self.assertEqual(change["operation"], "update")
        self.assertTrue(change["content"].startswith(original))
        self.assertIn("+.env.*", change["diff"])
        self.assertEqual((self.repo / ".dockerignore").read_text(), original)
        apply_docker_proposal(plan)
        self.assertEqual((self.repo / ".dockerignore").read_text(), change["content"])

    def test_stale_input_and_tampered_proposal_are_rejected(self):
        plan = propose_docker_files(self.repo)
        (self.repo / "package.json").write_text((self.repo / "package.json").read_text() + "\n")
        with self.assertRaises(ValueError):
            apply_docker_proposal(plan)
        self.assertFalse((self.repo / "Dockerfile").exists())
        plan = propose_docker_files(self.repo)
        plan["changes"][0]["content"] = "FROM unwanted\n"
        with self.assertRaises(ValueError):
            apply_docker_proposal(plan)

    def test_new_target_or_changed_ignore_file_prevents_apply(self):
        plan = propose_docker_files(self.repo)
        (self.repo / ".dockerignore").write_text("user-change\n")
        with self.assertRaises(ValueError):
            apply_docker_proposal(plan)
        self.assertEqual((self.repo / ".dockerignore").read_text(), "user-change\n")
        self.assertFalse((self.repo / "Dockerfile").exists())

    def test_partial_setup_is_blocked_with_next_action(self):
        (self.repo / "Dockerfile").write_text("FROM node:22\n")
        before = contents(self.repo)
        plan = propose_docker_files(self.repo)
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(any(b["code"] == "partial_setup" and b["next_action"] for b in plan["blockers"]))
        self.assertEqual(before, contents(self.repo))

    def test_existing_complete_setup_is_preserved_without_previewing_its_contents(self):
        (self.repo / "Dockerfile").write_text("FROM node:22\n# private-marker\n")
        (self.repo / "compose.yaml").write_text("services: {}\n")
        plan = propose_docker_files(self.repo)
        self.assertEqual(plan["status"], "unchanged")
        self.assertEqual(plan["changes"], [])
        self.assertNotIn("private-marker", json.dumps(plan))

    def test_failed_write_removes_only_files_created_by_this_apply(self):
        plan = propose_docker_files(self.repo)
        before = contents(self.repo)
        original = Path.open
        def fail_second(path, *args, **kwargs):
            if path.name == "docker-compose.yml" and args and args[0] == "x":
                raise OSError("simulated disk full")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", fail_second):
            with self.assertRaises(OSError):
                apply_docker_proposal(plan)
        self.assertEqual(before, contents(self.repo))

    def test_dangling_target_symlink_is_not_followed(self):
        target = Path(self.temp.name) / "outside"
        (self.repo / ".dockerignore").symlink_to(target)
        self.assertEqual(propose_docker_files(self.repo)["status"], "blocked")
        self.assertFalse(target.exists())

    def test_custom_npm_config_is_not_silently_baked_into_image(self):
        (self.repo / ".npmrc").write_text("//registry.example/:_authToken=never-print\n")
        plan = propose_docker_files(self.repo)
        self.assertEqual(plan["status"], "blocked")
        self.assertNotIn("never-print", json.dumps(plan))
