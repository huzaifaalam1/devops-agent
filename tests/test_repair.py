"""Repair contracts: bounded attempts, approval, input binding and rollback."""
import copy
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner

from agent.main import app
from agent.repair import propose_repair, apply_repair
from agent.docker_generator import propose_docker_files, apply_docker_proposal, development_compose
from agent.safety import Journal, authorize, repository_fingerprint, history, recovery
from tests.fixture_support import materialize


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = materialize('minimal', root / 'app')
        self.storage = root / 'state'
        env = patch.dict(os.environ, {'DEVOPS_AGENT_STATE_DIR': str(self.storage)})
        env.start()
        self.addCleanup(env.stop)
        apply_docker_proposal(propose_docker_files(self.repo))
        self.owner = socket.socket()
        self.owner.bind(('127.0.0.1', 0))
        self.owner.listen()
        self.addCleanup(self.owner.close)
        self.old_port = self.owner.getsockname()[1]
        self.compose = self.repo / 'docker-compose.yml'
        self.compose.write_text(development_compose([], self.old_port))
        self.original = self.compose.read_bytes()
        with socket.socket() as unused:
            unused.bind(('127.0.0.1', 0))
            self.new_port = unused.getsockname()[1]
        self.session = self.record()

    def record(self, error=None, check=None, phase='startup', cleanup='not_needed'):
        journal = Journal(self.repo, 'run', authorize('run', explicit=True))
        if check is not None:
            check = {**check, 'url': f'http://127.0.0.1:{self.new_port}/'}
        report = {'success': False, 'phase': phase,
                  'error': error if error is not None else f'Host port {self.old_port} is already in use.',
                  'cleanup': {'status': cleanup}, 'application_check': check,
                  'repair_context': {'inputs_sha256': repository_fingerprint(self.repo),
                                     'compose_file': 'docker-compose.yml', 'service': None,
                                     'container_port': None, 'health_path': '/'}}
        journal.finish('failed', report)
        return journal.id

    def plan(self):
        return propose_repair(self.repo, self.session, host_port=self.new_port)

    def passed(self, *args, **kwargs):
        self.assertIn(str(self.new_port), self.compose.read_text())
        self.assertFalse(kwargs['keep_running'])
        return {'success': True, 'phase': 'application', 'cleanup': {'status': 'complete'}, 'environment_state': 'stopped'}

    def test_preview_is_read_only_with_concrete_diff(self):
        records = list(self.storage.glob('*.json'))
        plan = self.plan()
        self.assertEqual(plan['status'], 'ready', plan)
        self.assertIn(str(self.new_port), plan['changes'][0]['diff'])
        self.assertEqual(plan['attempt_limit'], 1)
        self.assertEqual(self.compose.read_bytes(), self.original)
        self.assertEqual(list(self.storage.glob('*.json')), records)

    def test_missing_wrong_or_tampered_approval_cannot_write(self):
        plan = self.plan()
        for expected in (None, 'incorrect'):
            with self.assertRaises(ValueError):
                apply_repair(plan, expected)
        tampered = copy.deepcopy(plan)
        tampered['changes'][0]['content'] = 'run arbitrary instructions'
        with self.assertRaises(ValueError):
            apply_repair(tampered, plan['id'])
        self.assertEqual(self.compose.read_bytes(), self.original)

    def test_success_keeps_repair_and_can_be_recovered(self):
        plan = self.plan()
        with patch('agent.repair._journaled_validation', side_effect=self.passed) as run:
            result = apply_repair(plan, plan['id'])
        self.assertTrue(result['success'], result)
        self.assertEqual(result['attempts'], 1)
        run.assert_called_once()
        self.assertIn(str(self.new_port), self.compose.read_text())
        self.assertEqual(self.owner.getsockname()[1], self.old_port)
        self.assertEqual(history(self.repo)[-1]['status'], 'repaired')
        recovery(self.repo, result['session_id'], apply=True)
        self.assertEqual(self.compose.read_bytes(), self.original)

    def test_failed_repair_rolls_back_and_repeated_attempt_is_blocked(self):
        plan = self.plan()
        failure = {'success': False, 'phase': 'application', 'error': 'still broken', 'cleanup': {'status': 'complete'}}
        with patch('agent.repair._journaled_validation', return_value=failure) as run:
            result = apply_repair(plan, plan['id'])
        self.assertFalse(result['success'])
        self.assertEqual(result['rollback']['status'], 'recovered')
        self.assertEqual(self.compose.read_bytes(), self.original)
        run.assert_called_once()
        self.assertEqual(self.plan()['status'], 'blocked')
        self.session = self.record()  # A new failed validation must not reset the cap.
        self.assertIn('already attempted', self.plan()['blockers'][0])

    def test_cancelled_validation_rolls_back(self):
        plan = self.plan()
        with patch('agent.repair._journaled_validation', side_effect=KeyboardInterrupt):
            result = apply_repair(plan, plan['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['rollback']['status'], 'recovered')
        self.assertEqual(self.compose.read_bytes(), self.original)

    def test_concurrent_user_edit_is_preserved_and_escalated(self):
        plan = self.plan()
        def changed(*args, **kwargs):
            self.compose.write_text('user edited after repair')
            return {'success': False, 'phase': 'services', 'cleanup': {'status': 'complete'}}
        with patch('agent.repair._journaled_validation', side_effect=changed):
            result = apply_repair(plan, plan['id'])
        self.assertEqual(result['rollback']['status'], 'manual_recovery_required')
        self.assertEqual(self.compose.read_text(), 'user edited after repair')

    def test_stale_source_and_changed_proposal_are_refused(self):
        plan = self.plan()
        (self.repo / 'app/page.js').write_text('changed application')
        self.assertEqual(self.plan()['status'], 'blocked')
        with self.assertRaises(ValueError):
            apply_repair(plan, plan['id'])
        self.assertEqual(self.compose.read_bytes(), self.original)

    def test_wrong_root_unsafe_session_and_old_report_are_refused(self):
        self.assertEqual(propose_repair(self.repo.parent, self.session, host_port=self.new_port)['status'], 'blocked')
        self.assertEqual(propose_repair(self.repo, '../outside', host_port=self.new_port)['status'], 'blocked')
        record = self.storage / (self.session + '.json')
        data = json.loads(record.read_text())
        data['events'][-1].pop('repair_context')
        record.write_text(json.dumps(data))
        self.assertIn('rerun validate', self.plan()['blockers'][0])

    def test_unknown_missing_credentials_and_cleanup_failures_stay_manual(self):
        for error, cleanup in [('unknown failure', 'complete'), ('Required environment variable PASSWORD is missing', 'complete'), ('port is already allocated', 'failed')]:
            self.session = self.record(error=error, cleanup=cleanup)
            self.assertEqual(self.plan()['status'], 'blocked')
        self.assertEqual(self.compose.read_bytes(), self.original)

    def test_custom_compose_cannot_receive_template_repair(self):
        self.compose.write_text(self.compose.read_text() + '# user extension\n')
        self.session = self.record()
        self.assertEqual(self.plan()['status'], 'blocked')

    def test_port_that_becomes_occupied_is_refused_at_apply(self):
        plan = self.plan()
        with socket.socket() as owner:
            owner.bind(('127.0.0.1', self.new_port))
            with self.assertRaises(ValueError):
                apply_repair(plan, plan['id'])
        self.assertEqual(self.compose.read_bytes(), self.original)

    def test_no_repair_if_original_conflict_has_disappeared(self):
        self.owner.close()
        self.assertIn('now free', self.plan()['blockers'][0])

    def test_health_path_retry_changes_no_files_and_uses_supplied_path(self):
        self.session = self.record(error='Readiness requires authentication', check={'status_code': 401}, phase='application')
        plan = propose_repair(self.repo, self.session, health_path='/health')
        self.assertEqual(plan['status'], 'ready', plan)
        self.assertEqual(plan['changes'], [])
        def passed(*args, **kwargs):
            self.assertEqual(kwargs['health_path'], '/health')
            return {'success': True, 'phase': 'application', 'cleanup': {'status': 'complete'}}
        with patch('agent.repair._journaled_validation', side_effect=passed) as run:
            result = apply_repair(plan, plan['id'])
        self.assertTrue(result['success'])
        run.assert_called_once()
        self.assertEqual(self.compose.read_bytes(), self.original)

    def test_health_path_rejects_external_or_query_values(self):
        self.session = self.record(check={'status_code': 403}, error='auth', phase='application')
        for path in ('//example.com', '/health?token=secret', '/', 'https://example.com'):
            self.assertEqual(propose_repair(self.repo, self.session, health_path=path)['status'], 'blocked')

    def test_cli_preview_and_approval_gate(self):
        args = ['repair', str(self.repo), '--session', self.session, '--host-port', str(self.new_port), '--json']
        preview = CliRunner().invoke(app, args)
        self.assertEqual(preview.exit_code, 0, preview.output)
        plan = json.loads(preview.output)
        refused = CliRunner().invoke(app, args + ['--apply'])
        self.assertEqual(refused.exit_code, 1)
        with patch('agent.repair._journaled_validation', side_effect=self.passed):
            applied = CliRunner().invoke(app, args + ['--apply', '--expect', plan['id']])
        self.assertEqual(applied.exit_code, 0, applied.output)
        self.assertTrue(json.loads(applied.output)['success'])

    def test_validation_failure_evidence_is_redacted(self):
        (self.repo / '.env').write_text('VALUE=private-repair-value\n')
        self.compose.write_text(development_compose(['.env'], self.old_port))
        self.session = self.record()
        plan = self.plan()
        failure = {'success': False, 'phase': 'services', 'logs': 'private-repair-value'}
        with patch('agent.repair._journaled_validation', return_value=failure):
            result = apply_repair(plan, plan['id'])
        self.assertNotIn('private-repair-value', json.dumps(result))
        journal = self.storage / (result['session_id'] + '.json')
        self.assertNotIn('private-repair-value', journal.read_text())

    def test_busy_previous_endpoint_does_not_consume_health_attempt(self):
        self.session = self.record(error='auth', check={'status_code': 401}, phase='application')
        before = len(history(self.repo))
        with socket.socket() as other:
            other.bind(('127.0.0.1', self.new_port))
            plan = propose_repair(self.repo, self.session, health_path='/health')
        self.assertEqual(plan['status'], 'blocked')
        self.assertIn('no repair attempt', plan['blockers'][0])
        self.assertEqual(len(history(self.repo)), before)

    def test_failed_atomic_replacement_preserves_original(self):
        plan = self.plan()
        real_replace = os.replace
        def fail_target(source, target):
            if Path(target) == self.compose.resolve():
                raise OSError('simulated failed replacement')
            return real_replace(source, target)
        with patch('agent.repair.os.replace', side_effect=fail_target), patch('agent.repair._journaled_validation') as validate:
            result = apply_repair(plan, plan['id'])
        validate.assert_not_called()
        self.assertFalse(result['success'])
        self.assertEqual(self.compose.read_bytes(), self.original)
        self.assertEqual(result['rollback']['status'], 'unchanged')
        self.assertFalse(list(self.repo.glob('.devops-repair-*.tmp')))

    def test_redacted_preview_is_never_written_into_repair_file(self):
        (self.repo / '.env').write_text('LOCAL_ADDRESS=127.0.0.1\n')
        self.compose.write_text(development_compose(['.env'], self.old_port))
        self.session = self.record()
        plan = self.plan()
        self.assertIn('[REDACTED]', plan['changes'][0]['content'])
        with patch('agent.repair._journaled_validation', side_effect=self.passed):
            result = apply_repair(plan, plan['id'])
        self.assertTrue(result['success'])
        self.assertNotIn('[REDACTED]', self.compose.read_text())
        self.assertIn('127.0.0.1', self.compose.read_text())

    def test_dirty_target_refusal_does_not_run_validation_or_consume_attempt(self):
        plan = self.plan()
        with patch('agent.safety.protect_dirty_targets', side_effect=ValueError('dirty target')), patch('agent.repair._journaled_validation') as run:
            result = apply_repair(plan, plan['id'])
        run.assert_not_called()
        self.assertEqual(result['attempts'], 0)
        self.assertEqual(self.compose.read_bytes(), self.original)
        self.assertEqual(self.plan()['status'], 'ready')
