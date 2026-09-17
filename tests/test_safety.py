"""Execution boundaries, recovery and disclosure regression tests."""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner

from agent.safety import authorize, Redactor, recovery, history, project_lock
from agent.docker_generator import propose_docker_files, apply_docker_proposal
from agent.validator import validate_docker
from agent.main import app
from tests.fixture_support import materialize
from tests.test_validation import DockerFixture, healthy


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.repo = materialize('minimal', base / 'app')
        self.storage = base / 'state'
        self.env = patch.dict(os.environ, {'DEVOPS_AGENT_STATE_DIR': str(self.storage)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_policy_refuses_unapproved_or_outside_actions(self):
        self.assertEqual(authorize('inspect')['category'], 'read_only')
        for action in ('apply', 'run', 'build', 'recover', 'deploy', 'delete_all'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                authorize(action)
        with self.assertRaises(ValueError):
            authorize('deploy', explicit=True)

    def test_apply_has_private_snapshot_and_exact_recovery(self):
        original = b'custom-rule\n'
        (self.repo / '.dockerignore').write_bytes(original)
        (self.repo / '.dockerignore').chmod(0o640)
        plan = propose_docker_files(self.repo)
        result = apply_docker_proposal(plan)
        record = self.storage / (result['session_id'] + '.json')
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.storage.stat().st_mode), 0o700)
        data = json.loads(record.read_text())
        self.assertEqual(data['status'], 'applied')
        self.assertEqual(data['approval']['authorization'], 'explicit_command')
        preview = recovery(self.repo, result['session_id'])
        self.assertEqual(preview['status'], 'preview')
        self.assertTrue((self.repo / 'Dockerfile').exists())
        recovery(self.repo, result['session_id'], apply=True)
        self.assertFalse((self.repo / 'Dockerfile').exists())
        self.assertFalse((self.repo / 'docker-compose.yml').exists())
        self.assertEqual((self.repo / '.dockerignore').read_bytes(), original)
        self.assertEqual(stat.S_IMODE((self.repo / '.dockerignore').stat().st_mode), 0o640)

    def test_recovery_refuses_all_edits_when_one_target_changed(self):
        result = apply_docker_proposal(propose_docker_files(self.repo))
        (self.repo / '.dockerignore').write_text('user changed this')
        with self.assertRaises(ValueError):
            recovery(self.repo, result['session_id'], apply=True)
        self.assertTrue((self.repo / 'Dockerfile').exists())
        self.assertEqual((self.repo / '.dockerignore').read_text(), 'user changed this')

    def test_recovery_rejects_wrong_project_and_traversal(self):
        result = apply_docker_proposal(propose_docker_files(self.repo))
        with self.assertRaises(ValueError):
            recovery(self.repo.parent, result['session_id'], apply=True)
        with self.assertRaises(ValueError):
            recovery(self.repo, '../outside', apply=True)
        record = self.storage / (result['session_id'] + '.json')
        data = json.loads(record.read_text())
        data['changes'][0]['path'] = '../outside'
        record.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            recovery(self.repo, result['session_id'], apply=True)

    def test_symlink_and_hardlink_targets_are_refused(self):
        outside = self.repo.parent / 'outside'
        outside.write_text('outside state')
        target = self.repo / '.dockerignore'
        os.link(outside, target)
        with self.assertRaises(ValueError):
            apply_docker_proposal(propose_docker_files(self.repo))
        self.assertEqual(outside.read_text(), 'outside state')

    def test_dirty_target_refused_but_unrelated_dirty_work_preserved(self):
        def git(*args):
            return subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)
        git('init')
        (self.repo / '.dockerignore').write_text('original\n')
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'baseline')
        (self.repo / '.dockerignore').write_text('uncommitted\n')
        with self.assertRaises(ValueError):
            apply_docker_proposal(propose_docker_files(self.repo))
        self.assertFalse((self.repo / 'Dockerfile').exists())
        (self.repo / '.dockerignore').write_text('original\n')
        (self.repo / 'app/page.js').write_text('unrelated user edit')
        apply_docker_proposal(propose_docker_files(self.repo))
        self.assertEqual((self.repo / 'app/page.js').read_text(), 'unrelated user edit')

    def test_journal_failure_blocks_mutation_and_docker(self):
        self.storage.symlink_to(self.repo)
        with self.assertRaises(ValueError):
            apply_docker_proposal(propose_docker_files(self.repo))
        self.assertFalse((self.repo / 'Dockerfile').exists())
        with patch('agent.validator.run_command') as command:
            result = validate_docker(self.repo, run=True)
        command.assert_not_called()
        self.assertEqual(result['phase'], 'safety')

    def test_journal_inside_project_is_refused(self):
        with patch.dict(os.environ, {'DEVOPS_AGENT_STATE_DIR': str(self.repo / 'private-state')}):
            with self.assertRaises(ValueError):
                apply_docker_proposal(propose_docker_files(self.repo))
        self.assertFalse((self.repo / 'Dockerfile').exists())

    def test_history_never_exposes_snapshot_contents(self):
        (self.repo / '.dockerignore').write_text('private-backup-marker\n')
        apply_docker_proposal(propose_docker_files(self.repo))
        entries = history(self.repo)
        self.assertEqual(entries[-1]['status'], 'applied')
        self.assertNotIn('private-backup-marker', json.dumps(entries))
        self.assertNotIn('changes', entries[-1])

    def test_redaction_covers_known_values_patterns_and_nested_results(self):
        (self.repo / '.env').write_text('APP_VALUE="bare-private-value"\n')
        redactor = Redactor(self.repo)
        result = redactor.clean({'logs': 'bare-private-value password=hunter27 Authorization: Bearer abc-def\npostgres://user:dbpass@db/x\n-----BEGIN PRIVATE KEY-----\nprivate-key-body\n-----END PRIVATE KEY-----',
                                 'nested': [{'api_key': 'nested-secret'}]})
        encoded = json.dumps(result)
        for secret in ('bare-private-value', 'hunter27', 'abc-def', 'dbpass', 'private-key-body', 'nested-secret'):
            self.assertNotIn(secret, encoded)
        self.assertIn('[REDACTED', encoded)

    def test_runtime_report_and_journal_redact_compose_environment(self):
        docker = DockerFixture()
        docker.config['services']['app']['environment'] = {'NORMAL_NAME': 'compose-private-value'}
        docker.fail_up = True
        def command(args, repo, timeout=30):
            result = docker(args, repo, timeout)
            if 'up' in args:
                result['stderr'] = 'failure compose-private-value'
            return result
        with patch('agent.validator.run_command', side_effect=command):
            result = validate_docker(self.repo, run=True)
        self.assertNotIn('compose-private-value', json.dumps(result))
        data = (self.storage / (result['session_id'] + '.json')).read_text()
        self.assertNotIn('compose-private-value', data)
        self.assertIn('requested', data)
        self.assertIn(docker.project, data)

    def test_unsafe_builds_and_privileges_never_start(self):
        for unsafe in ({'build': {'context': str(self.repo.parent)}},
                       {'build': {'context': str(self.repo), 'ssh': ['default']}},
                       {'cap_add': ['SYS_ADMIN']}, {'use_api_socket': True},
                       {'build': {'context': str(self.repo), 'dockerfile': '../Dockerfile'}}):
            with self.subTest(unsafe=unsafe):
                docker = DockerFixture()
                docker.config['services']['app'].update(unsafe)
                with patch('agent.validator.run_command', side_effect=docker):
                    result = validate_docker(self.repo, run=True)
                self.assertEqual(result['phase'], 'isolation')
                self.assertFalse(any('up' in c or 'build' == c[-1] for c in docker.calls))

    def test_cli_verbose_and_json_do_not_disclose_dotenv_values(self):
        (self.repo / '.env').write_text('APP_VALUE=cli-secret-value\n')
        apply_docker_proposal(propose_docker_files(self.repo))
        report = {'success': False, 'phase': 'services', 'error': 'cli-secret-value', 'logs': 'cli-secret-value'}
        for flags in ([], ['--verbose'], ['--json']):
            with self.subTest(flags=flags), patch('agent.main.validate_docker', return_value=dict(report)):
                result = CliRunner().invoke(app, ['validate', str(self.repo), '--run', *flags])
            self.assertEqual(result.exit_code, 1)
            self.assertNotIn('cli-secret-value', result.output)
            self.assertIn('[REDACTED]', result.output)

    def test_successful_validation_with_failed_final_audit_is_not_success(self):
        docker = DockerFixture()
        with patch('agent.validator.run_command', side_effect=docker), patch('agent.validator.check_application_url', side_effect=healthy), patch('agent.safety.Journal.finish', side_effect=OSError('disk full')):
            result = validate_docker(self.repo, run=True)
        self.assertFalse(result['success'])
        self.assertEqual(result['phase'], 'audit')
        self.assertEqual(result['cleanup']['status'], 'complete')

    def test_concurrent_agent_action_is_refused_before_edit(self):
        with project_lock(self.repo):
            with self.assertRaises(ValueError):
                apply_docker_proposal(propose_docker_files(self.repo))
        self.assertFalse((self.repo / 'Dockerfile').exists())

    def test_history_without_prior_sessions_does_not_create_storage(self):
        self.assertEqual(history(self.repo), [])
        self.assertFalse(self.storage.exists())

    def test_json_secrets_and_truncated_private_key_are_redacted(self):
        clean = Redactor().text('prefix {"token": "json-private-value"}\n-----BEGIN PRIVATE KEY-----\ntruncated-key-data')
        self.assertNotIn('json-private-value', clean)
        self.assertNotIn('truncated-key-data', clean)

    def test_recovery_refuses_symlink_introduced_after_apply(self):
        result = apply_docker_proposal(propose_docker_files(self.repo))
        outside = self.repo.parent / 'outside'
        outside.write_text('unrelated')
        (self.repo / 'Dockerfile').unlink()
        (self.repo / 'Dockerfile').symlink_to(outside)
        with self.assertRaises(ValueError):
            recovery(self.repo, result['session_id'], apply=True)
        self.assertEqual(outside.read_text(), 'unrelated')

    def test_cancelled_apply_records_failure_and_rolls_back_owned_files(self):
        original = Path.open
        def interrupt(path, *args, **kwargs):
            if path.name == 'docker-compose.yml' and args and args[0] == 'x':
                raise KeyboardInterrupt
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', interrupt), self.assertRaises(KeyboardInterrupt):
            apply_docker_proposal(propose_docker_files(self.repo))
        self.assertFalse((self.repo / 'Dockerfile').exists())
        self.assertEqual(history(self.repo)[-1]['status'], 'failed')

    def test_validation_configuration_limits_wildcard_ports_to_loopback(self):
        from agent.validator import isolated_config
        config = {'services': {'app': {'image': 'fixture', 'ports': [{'target': 3000, 'published': '3000'}]}}}
        result = isolated_config(config, 'test-project', self.repo.resolve())
        self.assertEqual(result['services']['app']['ports'][0]['host_ip'], '127.0.0.1')

    def test_ignored_existing_target_is_not_overwritten(self):
        subprocess.run(['git', '-C', str(self.repo), 'init'], check=True, capture_output=True)
        (self.repo / '.gitignore').write_text('.dockerignore\n')
        (self.repo / '.dockerignore').write_text('ignored user content\n')
        with self.assertRaises(ValueError):
            apply_docker_proposal(propose_docker_files(self.repo))
        self.assertEqual((self.repo / '.dockerignore').read_text(), 'ignored user content\n')
        self.assertFalse((self.repo / 'Dockerfile').exists())

    def test_git_fsmonitor_is_not_executed_during_state_inspection(self):
        import shlex
        subprocess.run(['git', '-C', str(self.repo), 'init'], check=True, capture_output=True)
        sentinel = self.repo.parent / 'hook-ran'
        hook = self.repo.parent / 'fsmonitor-hook'
        hook.write_text('#!/bin/sh\ntouch ' + shlex.quote(str(sentinel)) + '\n')
        hook.chmod(0o700)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'core.fsmonitor', str(hook)], check=True, capture_output=True)
        apply_docker_proposal(propose_docker_files(self.repo))
        self.assertFalse(sentinel.exists())
