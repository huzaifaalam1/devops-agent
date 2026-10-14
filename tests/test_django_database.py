import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.django_database import inspect_contract, prepare_config, database_target, migrate
from agent.docker_generator import propose_docker_files
from agent.tools import ToolRegistry, ToolRefused
from tests.test_django_project import FIXTURE


def postgres_fixture(root):
    shutil.copytree(FIXTURE, root)
    path = root/'config/settings.py'
    path.write_text("import os\nSECRET_KEY='disposable-only'\nALLOWED_HOSTS=['127.0.0.1','localhost']\nROOT_URLCONF='config.urls'\nINSTALLED_APPS=['notes']\nMIDDLEWARE=[]\nDATABASES={'default':{'ENGINE':'django.db.backends.postgresql'," + ','.join(repr(key)+":os.environ["+repr('DB_'+key)+"]" for key in ['NAME','USER','PASSWORD','HOST','PORT']) + '}}\n')
    (root/'requirements.txt').write_text('Django==5.2.8\npsycopg[binary]==3.2.10\n')
    (root/'notes/migrations').mkdir(parents=True)
    (root/'notes/__init__.py').touch();(root/'notes/migrations/__init__.py').touch()
    (root/'notes/models.py').write_text("from django.db import models\nclass Note(models.Model):\n    value=models.CharField(max_length=64)\n")
    (root/'notes/migrations/0001_initial.py').write_text("from django.db import migrations,models\nclass Migration(migrations.Migration):\n    initial=True\n    dependencies=[]\n    operations=[migrations.CreateModel(name='Note',fields=[('id',models.AutoField(primary_key=True)),('value',models.CharField(max_length=64))])]\n")
    (root/'config/urls.py').write_text("from django.http import HttpResponse\nfrom django.urls import path\nfrom notes.models import Note\ndef ready(request):\n    row=Note.objects.create(value='step7-database-ready')\n    value=Note.objects.get(pk=row.pk).value\n    row.delete()\n    return HttpResponse(value)\nurlpatterns=[path('',ready)]\n")


class DjangoDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()/'app';postgres_fixture(self.root)
        env=patch.dict(os.environ,{'DEVOPS_AGENT_STATE_DIR':str(self.root.parent/'state')})
        env.start();self.addCleanup(env.stop)
    def test_contract_and_no_persistent_or_published_database(self):
        proposal=propose_docker_files(self.root);self.assertEqual(proposal['status'],'ready',proposal)
        self.assertIsNone(proposal['run_command'])
        compose=next(c['content'] for c in proposal['changes'] if c['path']=='docker-compose.yml')
        self.assertIn('tmpfs:',compose);self.assertEqual(compose.count('ports:'),1)
        self.assertNotIn('volumes:',compose)
        self.assertIn('service_healthy',compose)
    def test_literal_external_target_and_duplicate_fields_refused(self):
        path=self.root/'config/settings.py';before=path.read_text()
        for text in [before.replace("os.environ['DB_HOST']","'production.example'"),before.replace("'PORT':", "'HOST':")]:
            path.write_text(text)
            with self.assertRaises(ValueError):inspect_contract(self.root,['config/settings.py'])
    def test_runtime_password_generated_and_not_in_template(self):
        from agent.safety import Redactor
        project={'database_environment':inspect_contract(self.root,['config/settings.py'])}
        config={'services':{'app':{'environment':{}},'db':{'environment':{}}}}
        redactor=Redactor(self.root);prepare_config(config,project,redactor)
        password=config['services']['db']['environment']['POSTGRES_PASSWORD']
        self.assertGreater(len(password),32)
        self.assertEqual(password,config['services']['app']['environment']['DB_PASSWORD'])
        self.assertNotIn(password,json.dumps(redactor.clean(config)))
        self.assertNotIn('runserver',str(config['services']['app']['command']))
    def test_tools_cannot_execute_without_separate_approval(self):
        registry=ToolRegistry(self.root)
        with self.assertRaises(ToolRefused):registry.execute('prepare_database',{})
        with self.assertRaises(ToolRefused):registry.execute('migrate_database',{'session_id':'a'*32})
        with self.assertRaises((ValueError,OSError)):registry.review('migrate_database',{'session_id':'a'*32})
    def test_existing_compose_refused_before_docker(self):
        from agent.main import validation_result
        (self.root/'Dockerfile').write_text('FROM python:3.12-slim\n')
        (self.root/'docker-compose.yml').write_text('services: {}\n')
        with patch('agent.main.validate_docker') as docker:
            result=validation_result(str(self.root),compose_file='docker-compose.yml',run=True,keep_running=True,prepare_database=True)
            self.assertFalse(result['success']);docker.assert_not_called()
    def test_no_ordinary_postgres_run_before_initialization_review(self):
        from agent.main import validation_result
        with patch('agent.main.validate_docker') as docker:
            result=validation_result(str(self.root),run=True)
            self.assertFalse(result['success']);docker.assert_not_called()
    def test_unowned_database_refused_without_exec(self):
        with patch('agent.runtime_control.command') as command:
            with self.assertRaises(ValueError):database_target(self.root,{'containers':{'db':'x'}})
            command.assert_not_called()
    def test_changed_preview_never_runs_migrations(self):
        with patch('agent.django_database.migration_preview',return_value={'different':True}), patch('agent.django_database.run_database') as run:
            with self.assertRaises(ValueError):migrate(self.root,'a'*32,{})
            run.assert_not_called()
    def test_migration_verifies_services_and_is_never_replayed(self):
        runtime={'project':'devops-validation-123456789abc','containers':{'app':'a'*64,'db':'b'*64}}
        preview={'runtime':runtime,'plan':{'digest':'d'*64}}
        containers=[{'Id':cid,'Config':{'Labels':{'com.docker.compose.project':runtime['project'],'com.docker.compose.service':name}},'State':{'Status':'running','Running':True,**({'Health':{'Status':'healthy'}} if name=='db' else {})},'NetworkSettings':{'Ports':{'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'8000'}]} if name=='app' else {}}} for name,cid in runtime['containers'].items()]
        with patch('agent.django_database.database_target',return_value='172.22.0.2'), patch('agent.django_database.migration_preview',return_value=preview), patch('agent.django_database.run_database',return_value={'orm_verified':True}) as run, patch('agent.runtime_control.command',return_value=json.dumps(containers)), patch('agent.validator.check_application_url',return_value={'healthy':True}):
            result=migrate(self.root,'a'*32,preview)
            self.assertTrue(result['success']);self.assertTrue(result['orm_verified'])
            with self.assertRaises(FileExistsError):migrate(self.root,'a'*32,preview)
            run.assert_called_once()
    def test_failed_migration_keeps_fence_and_records_failure(self):
        preview={'runtime':{},'plan':{'digest':'d'*64}}
        with patch('agent.django_database.migration_preview',return_value=preview), patch('agent.django_database.run_database',side_effect=ValueError('Plan changed')) as run:
            result=migrate(self.root,'a'*32,preview)
            self.assertFalse(result['success']);self.assertEqual(result['diagnosis']['type'],'database_migration')
            with self.assertRaises(FileExistsError):migrate(self.root,'a'*32,preview)
            run.assert_called_once()
        records=[json.loads(p.read_text()) for p in (self.root.parent/'state').glob('*.json')]
        self.assertEqual(records[0]['status'],'failed')
    def test_docker_tmpfs_configuration_without_mounts_entry_is_accepted(self):
        project='devops-validation-123456789abc';network=project+'_default'
        runtime={'project':project,'containers':{'app':'a'*64,'db':'b'*64}}
        details=[{'Id':cid,'Config':{'Labels':{'com.docker.compose.project':project,'com.docker.compose.service':name}},'State':{'Running':True,'Health':{'Status':'healthy'}},'HostConfig':{'Tmpfs':{'/var/lib/postgresql/data':''}},'Mounts':[],'NetworkSettings':{'Networks':{network:{'IPAddress':'172.22.0.2'}}}} for name,cid in runtime['containers'].items()]
        details[0]['NetworkSettings']['Networks'][project+'_ingress']={'IPAddress':'172.23.0.2'}
        network_info=[{'Name':network,'Internal':True,'Labels':{'com.docker.compose.project':project}},{'Name':project+'_ingress','Internal':False,'Labels':{'com.docker.compose.project':project}}]
        with patch('agent.runtime_control.command',side_effect=[json.dumps(details),json.dumps(network_info)]):
            self.assertEqual(database_target(self.root,runtime),'172.22.0.2')
        for field,value in [('Mounts',[{'Type':'volume','Destination':'/var/lib/postgresql/data'}]),('HostConfig',{'Tmpfs':{}})]:
            changed=json.loads(json.dumps(details));changed[1][field]=value
            with patch('agent.runtime_control.command',return_value=json.dumps(changed)):
                with self.assertRaises(ValueError):database_target(self.root,runtime)

class DatabaseCommandDiagnosticsTests(unittest.TestCase):
    def test_timeout_retains_completed_stage_output(self):
        import sys
        from agent.validator import run_command
        with tempfile.TemporaryDirectory() as directory:
            result=run_command([sys.executable,'-c',"import time;print('stage reached',flush=True);time.sleep(30)"],directory,timeout=.2)
        self.assertFalse(result['success']);self.assertTrue(result['timed_out'])
        self.assertIn('stage reached',result['stdout'])
