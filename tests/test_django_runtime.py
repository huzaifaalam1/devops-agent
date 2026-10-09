import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.docker_generator import propose_docker_files, apply_docker_proposal
from agent.main import validation_result
from agent.scanner import scan_repo
from agent.detector import detect_stack
from tests.test_django_project import FIXTURE


class DjangoRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()/'app';shutil.copytree(FIXTURE,self.root)
        env=patch.dict(os.environ,{'DEVOPS_AGENT_STATE_DIR':str(self.root.parent/'state')})
        env.start();self.addCleanup(env.stop)
    def proposal(self):return propose_docker_files(self.root)
    def test_template_uses_python_without_migrations_or_host_db(self):
        p=self.proposal();self.assertEqual(p['status'],'ready')
        files={c['path']:c['content'] for c in p['changes']}
        self.assertIn('FROM python:3.12-slim',files['Dockerfile'])
        self.assertIn('pip install --no-cache-dir -r requirements.txt',files['Dockerfile'])
        self.assertIn('0.0.0.0:8000',files['Dockerfile'])
        self.assertNotIn('migrate',files['Dockerfile'])
        self.assertNotIn('volumes:',files['docker-compose.yml'])
        self.assertIn('**/*.sqlite3',files['.dockerignore'])
        self.assertFalse((self.root/'Dockerfile').exists())
    def test_apply_reuses_existing_setup_without_overwrite(self):
        p=self.proposal();result=apply_docker_proposal(p)
        self.assertEqual(set(result['created']),{'Dockerfile','docker-compose.yml','.dockerignore'})
        self.assertEqual(self.proposal()['status'],'unchanged')
    def test_requirements_include_or_settings_change_invalidates_proposal(self):
        for name in ['requirements.txt','config/settings.py']:
            with self.subTest(name=name):
                p=self.proposal();target=self.root/name;before=target.read_text();target.write_text(before+'\n# changed\n')
                with self.assertRaises(ValueError):apply_docker_proposal(p)
                target.write_text(before)
    def test_environment_values_not_baked_into_proposal(self):
        secret='step6-private-fixture-value'
        (self.root/'.env').write_text('DJANGO_SECRET_KEY='+secret+'\nDJANGO_SETTINGS_MODULE=other.settings\n')
        p=self.proposal();self.assertNotIn(secret,json.dumps(p))
        files={c['path']:c['content'] for c in p['changes']}
        self.assertIn('env_file:',files['docker-compose.yml'])
        self.assertIn('DJANGO_SETTINGS_MODULE: config.settings',files['docker-compose.yml'])
    def test_postgres_is_blocked_before_docker(self):
        target=self.root/'config/settings.py';target.write_text(target.read_text().replace('django.db.backends.sqlite3','django.db.backends.postgresql'))
        self.assertEqual(self.proposal()['status'],'blocked')
        (self.root/'Dockerfile').write_text('FROM python:3.12-slim\n')
        (self.root/'compose.yml').write_text('services:\n  app:\n    image: python:3.12-slim\n')
        with patch('agent.main.validate_docker') as docker:
            result=validation_result(str(self.root),compose_file='compose.yml',existing_setup=True,run=True)
            self.assertEqual(result['phase'],'eligibility');docker.assert_not_called()
    def test_shared_or_dynamic_sqlite_names_are_blocked(self):
        target=self.root/'config/settings.py';original=target.read_text()
        for expression in ["'/outside/data.sqlite3'",'get_database_path()',"'production-data'", "'nested/db.sqlite3'"]:
            target.write_text(original.replace("':memory:'",expression))
            codes={b['code'] for b in self.proposal()['blockers']}
            self.assertIn('django_sqlite_path',codes)
    def test_partial_setup_preserved_and_ambiguous_requires_selection(self):
        (self.root/'Dockerfile').write_text('FROM python:3.12-slim\n')
        self.assertEqual(self.proposal()['status'],'blocked')
        for name in ['compose.yml','compose.dev.yml']:(self.root/name).write_text('services: {}\n')
        p=detect_stack(scan_repo(str(self.root)))['project']
        self.assertIn('compose_selection',{b['code'] for b in p['blockers']})
    def test_supported_validation_dispatches_shared_validator(self):
        apply_docker_proposal(self.proposal())
        with patch('agent.main.validate_docker',return_value={'success':True,'phase':'application'}) as docker:
            result=validation_result(str(self.root),run=True)
        self.assertTrue(result['success']);docker.assert_called_once()

    def test_linked_environment_file_is_blocked(self):
        (self.root/'credentials').write_text('DJANGO_SECRET_KEY=not-for-image\n')
        (self.root/'.env').symlink_to('credentials')
        self.assertIn('django_environment_file',{b['code'] for b in self.proposal()['blockers']})
    def test_included_requirement_changes_invalidate_review(self):
        (self.root/'deps').mkdir();(self.root/'deps/base.txt').write_text('Django==5.2.8\n')
        (self.root/'requirements.txt').write_text('-r deps/base.txt\n')
        proposal=self.proposal();self.assertEqual(proposal['status'],'ready')
        (self.root/'deps/base.txt').write_text('Django==5.2.9\n')
        with self.assertRaises(ValueError):apply_docker_proposal(proposal)
