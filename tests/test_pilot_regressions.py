"""Regressions discovered while screening external pilot repositories."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner
from agent.main import app
from agent.detector import detect_stack
from agent.scanner import scan_repo
from tests.fixture_support import materialize


class PilotRegressions(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runner = CliRunner()

    def test_django_and_vue_do_not_receive_nextjs_remediation(self):
        for name in ('django', 'vue'):
            repo = self.root / name
            repo.mkdir()
            if name == 'django':
                (repo / 'manage.py').write_text('# Django entrypoint\n')
                (repo / 'requirements.txt').write_text('Django==4.2\npsycopg2\n')
            else:
                (repo / 'package.json').write_text(json.dumps({'dependencies': {'vue': '^3'}, 'scripts': {'dev': 'vite'}}))
            result = detect_stack(scan_repo(str(repo)))
            self.assertEqual(result['project']['eligibility'], 'blocked')
            self.assertEqual([b['code'] for b in result['project']['blockers']], ['unsupported_framework'])
            guidance = ' '.join(result['recommendations'])
            for unwanted in ('next dev', 'Node 22', 'package-lock', 'Declare engines'):
                self.assertNotIn(unwanted, guidance)
            self.assertIn('Preserve this stack', guidance)
            self.assertIn('Django app' if name == 'django' else 'Vue app', result['detected'])
            if name == 'django':
                self.assertIn('PostgreSQL', result['services'])
            preview = self.runner.invoke(app, ['dockerize', str(repo), '--json'])
            self.assertEqual(preview.exit_code, 1)
            self.assertEqual(json.loads(preview.stdout)['changes'], [])

    def make_variants(self):
        repo = materialize('existing-compose', self.root / 'app')
        (repo / 'compose.dev.yaml').write_text('services:\n  app:\n    image: node:22-alpine\n')
        return repo

    def test_ambiguous_config_does_not_call_docker(self):
        repo = self.make_variants()
        with patch('agent.main.validate_docker') as docker:
            result = self.runner.invoke(app, ['validate', str(repo), '--json'])
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(json.loads(result.stdout)['phase'], 'selection')
        docker.assert_not_called()

    def test_selected_config_reaches_validator_and_removes_only_ambiguity(self):
        repo = self.make_variants()
        (repo / 'Dockerfile.dev').write_text('FROM node:22-alpine\n')
        with patch('agent.main.validate_docker', return_value={'success': True, 'phase': 'config'}) as docker:
            result = self.runner.invoke(app, ['validate', str(repo), '--compose-file', 'compose.dev.yaml', '--run', '--json'])
        self.assertEqual(result.exit_code, 0, result.stdout)
        self.assertEqual(docker.call_args.kwargs['compose_file'], 'compose.dev.yaml')
        self.assertTrue(docker.call_args.kwargs['run'])

    def test_selection_does_not_bypass_other_eligibility_blockers(self):
        repo = self.make_variants()
        (repo / 'Dockerfile.dev').write_text('FROM node:20-alpine\n')
        with patch('agent.main.validate_docker') as docker:
            result = self.runner.invoke(app, ['validate', str(repo), '--compose-file', 'compose.dev.yaml', '--run', '--json'])
        report = json.loads(result.stdout)
        self.assertEqual(result.exit_code, 1)
        codes = [b['code'] for b in report['project']['blockers']]
        self.assertIn('docker_runtime_conflict', codes)
        self.assertNotIn('compose_selection', codes)
        docker.assert_not_called()

    def test_selection_refuses_outside_unknown_and_symlink_paths(self):
        repo = self.make_variants()
        (repo / 'compose.link.yaml').symlink_to(repo / 'compose.dev.yaml')
        for selection in ('../compose.yaml', str(repo / 'compose.dev.yaml'), 'missing.yaml', 'compose.link.yaml'):
            with self.subTest(selection=selection), patch('agent.main.validate_docker') as docker:
                result = self.runner.invoke(app, ['validate', str(repo), '--compose-file', selection, '--json'])
                self.assertEqual(result.exit_code, 1)
                self.assertEqual(json.loads(result.stdout)['phase'], 'selection')
                docker.assert_not_called()

    def test_single_compose_keeps_default_selection(self):
        repo = materialize('existing-compose', self.root / 'app')
        with patch('agent.main.validate_docker', return_value={'success': True, 'phase': 'config'}) as docker:
            result = self.runner.invoke(app, ['validate', str(repo), '--json'])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(docker.call_args.kwargs['compose_file'], 'compose.yaml')

    def test_existing_setup_requires_selection_and_preserves_isolation(self):
        repo = self.make_variants()
        (repo / 'pnpm-lock.yaml').write_text('lockfileVersion: 9\n')
        with patch('agent.main.validate_docker') as docker:
            result = self.runner.invoke(app, ['validate', str(repo), '--existing-setup', '--run', '--json'])
            self.assertEqual(result.exit_code, 1)
            docker.assert_not_called()
        with patch('agent.main.validate_docker', return_value={'success': False, 'phase': 'isolation', 'error': 'Shared resources refused.'}) as docker:
            result = self.runner.invoke(app, ['validate', str(repo), '--existing-setup', '--compose-file', 'compose.dev.yaml', '--run', '--json'])
            report = json.loads(result.stdout)
            docker.assert_called_once()
            self.assertEqual(report['phase'], 'isolation')
            self.assertFalse(report['success'])
            self.assertIn('package_manager', [b['code'] for b in report['eligibility_basis']['deferred_template_checks']])

    def test_existing_setup_does_not_authorize_other_stacks(self):
        repo = materialize('unsupported', self.root / 'other')
        (repo / 'compose.yaml').write_text('services: {}\n')
        with patch('agent.main.validate_docker') as docker:
            result = self.runner.invoke(app, ['validate', str(repo), '--existing-setup', '--compose-file', 'compose.yaml', '--run', '--json'])
        self.assertEqual(json.loads(result.stdout)['phase'], 'eligibility')
        docker.assert_not_called()
