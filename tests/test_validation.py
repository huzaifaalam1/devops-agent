"""Lifecycle contracts with explicit Docker boundary fakes and real HTTP tests."""

import copy
import json
import sys
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.validator import run_command, validate_docker, service_snapshot


class DockerFixture:
    def __init__(self):
        self.calls = []
        self.project = None
        self.started = False
        self.fail_up = False
        self.fail_down = False
        self.failed_inspect = False
        self.cancel_up = False
        self.state = "running"
        self.health = None
        self.wrong_owner = False
        self.swapped = False
        self.inspections = 0
        self.config = {"services": {"app": {"image": "fixture:local", "ports": [{"target": 8080, "published": "0", "protocol": "tcp"}]}}}

    def __call__(self, command, repo, timeout=30):
        self.calls.append(command)
        if "-p" in command:
            self.project = command[command.index("-p") + 1]
        result = {"command": " ".join(command), "success": True, "stdout": "", "stderr": "", "returncode": 0}
        if "config" in command:
            result["stdout"] = json.dumps(self.config)
        elif command[1:3] == ["context", "inspect"]:
            result["stdout"] = '"unix:///fixture/docker.sock"'
        elif "up" in command:
            self.started = True
            if self.cancel_up:
                raise KeyboardInterrupt
            if self.fail_up:
                result.update(success=False, returncode=1, stderr="port is already allocated")
        elif "down" in command:
            if self.fail_down:
                result.update(success=False, returncode=1, stderr="cleanup failed")
            else:
                self.started = False
        elif "ps" in command:
            result["stdout"] = "container-1\n" if self.started else ""
        elif command[1] == "inspect":
            self.inspections += 1
            if self.failed_inspect:
                result.update(success=False, returncode=1, stderr="cannot inspect")
            else:
                state = {"Status": self.state, "Running": self.state == "running"}
                if self.health:
                    state["Health"] = {"Status": self.health}
                result["stdout"] = json.dumps([{
                    "Id": "container-2" if self.swapped and self.inspections > 1 else "container-1",
                    "Config": {"Labels": {"com.docker.compose.project": "someone-else" if self.wrong_owner else self.project,
                                           "com.docker.compose.service": "app"}},
                    "State": state, "RestartCount": 0,
                    "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49152"}]}},
                }])
        elif "logs" in command:
            result["stdout"] = "fixture startup evidence"
        return result


def healthy(url, **kwargs):
    return {"url": url, "healthy": True, "reachable": True, "status_code": 200,
            "redirect_url": None, "error": None}


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.docker = DockerFixture()

    def validate(self, **kwargs):
        with patch("agent.validator.run_command", side_effect=self.docker), patch("agent.validator.check_application_url", side_effect=healthy):
            return validate_docker(str(self.repo), run=True, timeout=3, readiness_timeout=.4, **kwargs)

    def test_owned_port_discovery_and_verified_cleanup(self):
        result = self.validate()
        self.assertTrue(result["success"], result)
        self.assertEqual(result["application_check"]["url"], "http://127.0.0.1:49152/")
        self.assertEqual(result["application_check"]["container_id"], "container-1")
        self.assertEqual(result["environment_state"], "stopped")
        self.assertEqual(result["cleanup"]["status"], "complete")
        self.assertGreaterEqual(self.docker.inspections, 2)
        self.assertEqual(result["dependency_checks"], {})
        self.assertIn({"phase": "dependencies", "success": True, "status": "not_required"}, result["stages"])
        self.assertTrue(all(c[c.index("-p")+1] == result["project"] for c in self.docker.calls if "-p" in c))

    def test_wrong_owner_cannot_produce_successful_http_check(self):
        self.docker.wrong_owner = True
        with patch("agent.validator.run_command", side_effect=self.docker), patch("agent.validator.check_application_url") as probe:
            result = validate_docker(str(self.repo), run=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "ownership")
        probe.assert_not_called()

    def test_container_replacement_during_probe_is_failure(self):
        self.docker.swapped = True
        result = self.validate()
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "services")

    def test_exited_service_cannot_be_hidden_by_healthy_http(self):
        self.docker.state = "exited"
        result = self.validate()
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "services")
        self.assertIn("fixture startup evidence", result["logs"])

    def test_healthcheck_must_be_healthy(self):
        self.docker.config["services"]["app"]["healthcheck"] = {"test": ["CMD", "true"]}
        self.docker.health = "unhealthy"
        result = self.validate()
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "services")
        self.assertIsNone(result["application_check"])

    def test_declared_missing_health_status_is_not_ready(self):
        self.docker.config["services"]["app"]["healthcheck"] = {"test": ["CMD", "true"]}
        self.assertFalse(self.validate()["success"])

    def test_partial_startup_failure_always_cleans_up_even_keep_running(self):
        self.docker.fail_up = True
        result = self.validate(keep_running=True)
        self.assertEqual(result["phase"], "startup")
        self.assertEqual(result["cleanup"]["status"], "complete")
        self.assertFalse(self.docker.started)

    def test_cancelled_startup_cleans_up(self):
        self.docker.cancel_up = True
        result = self.validate()
        self.assertEqual(result["phase"], "cancelled")
        self.assertEqual(result["cleanup"]["status"], "complete")

    def test_cleanup_failure_overrides_application_success(self):
        self.docker.fail_down = True
        result = self.validate()
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "cleanup")
        self.assertEqual(result["primary_phase"], "application")
        self.assertEqual(result["environment_state"], "unknown")

    def test_successful_keep_running_has_scoped_stop_command(self):
        result = self.validate(keep_running=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["environment_state"], "running")
        self.assertIn(result["project"], result["cleanup"]["stop_command"])
        self.assertIn("down", result["cleanup"]["stop_command"])
        self.assertFalse(any("down" in c for c in self.docker.calls))

    def test_failed_inspection_is_not_ignored(self):
        self.docker.failed_inspect = True
        result = self.validate()
        self.assertFalse(result["success"])
        self.assertEqual(result["phase"], "services")

    def test_ambiguous_application_stops_before_build_or_start(self):
        self.docker.config["services"]["other"] = copy.deepcopy(self.docker.config["services"]["app"])
        result = self.validate()
        self.assertEqual(result["phase"], "application")
        self.assertFalse(self.docker.started)

    def test_shared_resources_are_rejected_before_mutation(self):
        for shared in ({"container_name": "user-container"}, {"network_mode": "host"},
                       {"volumes": [{"type": "bind", "source": str(self.repo), "target": "/app"}]}):
            with self.subTest(shared=shared):
                docker = DockerFixture()
                docker.config["services"]["app"].update(shared)
                with patch("agent.validator.run_command", side_effect=docker):
                    result = validate_docker(str(self.repo), run=True)
                self.assertEqual(result["phase"], "isolation")
                self.assertFalse(docker.started)

    def test_config_only_does_not_claim_runtime_or_leak_values(self):
        self.docker.config["services"]["app"]["environment"] = {"TOKEN": "never-emit-this"}
        with patch("agent.validator.run_command", side_effect=self.docker):
            result = validate_docker(str(self.repo))
        self.assertTrue(result["success"])
        self.assertEqual(result["verified"], ["config"])
        self.assertNotIn("never-emit-this", json.dumps(result))
        self.assertEqual(len(self.docker.calls), 1)

    def test_authentication_failure_is_not_readiness_success(self):
        def unauthorized(url, **kwargs):
            return {"url": url, "healthy": False, "status_code": 401, "error": "Authentication required"}
        with patch("agent.validator.run_command", side_effect=self.docker), patch("agent.validator.check_application_url", side_effect=unauthorized):
            result = validate_docker(str(self.repo), run=True, readiness_timeout=.05)
        self.assertEqual(result["phase"], "application")
        self.assertFalse(result["success"])
        self.assertIn("Authentication", result["error"])

    def test_health_path_option_stays_on_discovered_endpoint(self):
        result = self.validate(health_path="/health")
        self.assertTrue(result["success"])
        self.assertEqual(result["application_check"]["url"], "http://127.0.0.1:49152/health")
        self.assertEqual(validate_docker(str(self.repo), health_path="//other-host")["phase"], "options")

    def test_process_timeout_and_missing_binary_are_structured(self):
        started = time.monotonic()
        result = run_command([sys.executable, "-c", "import time; time.sleep(10)"], self.repo, timeout=.05)
        self.assertFalse(result["success"])
        self.assertTrue(result["timed_out"])
        self.assertLess(time.monotonic() - started, 3)
        result = run_command([str(self.repo / "absent-executable")], self.repo)
        self.assertTrue(result["host_error"])

    def test_occupied_host_port_fails_before_start_without_stopping_owner(self):
        with socket.socket() as owner:
            owner.bind(("127.0.0.1", 0))
            owner.listen()
            port = owner.getsockname()[1]
            self.docker.config["services"]["app"]["ports"][0].update(published=str(port), host_ip="127.0.0.1")
            result = self.validate()
            self.assertEqual(result["phase"], "startup")
            self.assertEqual(result["cleanup"]["status"], "not_needed")
            self.assertFalse(any("up" in c or "down" in c for c in self.docker.calls))
            self.assertEqual(owner.getsockname()[1], port)

    def test_build_failure_removes_only_run_owned_image(self):
        self.docker.config["services"]["app"]["build"] = {"context": str(self.repo)}
        def boundary(command, repo, timeout=30):
            result = self.docker(command, repo, timeout)
            if command[-1] == "build":
                result.update(success=False, stderr="fixture build failed")
            return result
        with patch("agent.validator.run_command", side_effect=boundary):
            result = validate_docker(str(self.repo), build=True)
        self.assertEqual(result["phase"], "build")
        self.assertEqual(result["cleanup"]["status"], "complete")
        self.assertIn(["docker", "image", "rm", result["project"] + "-app:validation"], self.docker.calls)
        self.assertFalse(any("up" in c for c in self.docker.calls))
