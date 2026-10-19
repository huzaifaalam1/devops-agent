import json
import tempfile
import unittest
from pathlib import Path
from agent.existing_compose import inspect_existing, copy_mounts
from agent.scanner import scan_repo
from agent.runtime_policy import runtime_options
from agent.validator import isolated_config, ValidationFailure
from agent.tools import ToolRegistry, ToolRefused

class ExistingStackTests(unittest.TestCase):
    def fixture(self,root):
        (root/'backend').mkdir();(root/'backend/manage.py').write_text('')
        (root/'frontend').mkdir();(root/'frontend/package.json').write_text('{"dependencies":{"vue":"3"}}')
        (root/'LocalDockerfile').write_text('FROM python:3.12\nCOPY entrypoint.sh /entrypoint.sh\nENTRYPOINT ["/entrypoint.sh"]\n')
        (root/'entrypoint.sh').write_text('python manage.py migrate\nnpm run dev &\npython manage.py runserver 0.0.0.0:8000\n')
        (root/'compose.local.yml').write_text('services:\n  app:\n    build:\n      context: .\n      dockerfile: LocalDockerfile\n    ports: ["3000:3000", "8000:8000"]\n    volumes: ["./backend:/app/backend"]\n')
    def test_root_existing_setup_is_reviewable_and_startup_is_disclosed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            info=scan_repo(d);self.assertIn('LocalDockerfile',info['dockerfiles'])
            option=runtime_options(info)[0]
            self.assertEqual(option['status'],'reviewable')
            self.assertTrue(option['parameters']['isolated_stack'])
            self.assertTrue(option['existing_configuration']['startup_database_effects'])
            registry=ToolRegistry(root)
            review=registry.review('validate_runtime',option['parameters'])
            self.assertIn('new and empty',review['effect'])
            self.assertIn('entrypoint.sh',review['preview']['evidence'])
            self.assertIn('LOCAL_UID',review['preview']['host_build_defaults'])
            with self.assertRaises(ToolRefused):registry.execute('validate_runtime',option['parameters'])
    def test_snapshot_copies_sources_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo';root.mkdir();self.fixture(root)
            out=Path(d)/'copy';out.mkdir()
            config={'services':{'app':{'volumes':[{'type':'bind','source':str(root/'backend'),'target':'/app/backend'}]}}}
            result=copy_mounts(config,root,out)
            copied=Path(config['services']['app']['volumes'][0]['source'])
            (copied/'manage.py').write_text('changed')
            self.assertEqual((root/'backend/manage.py').read_text(),'')
            isolated_config(config,'devops-validation-123',root,copied_sources=out)
            with self.assertRaises(ValidationFailure):isolated_config(config,'devops-validation-123',root)
            (root/'backend/escape').symlink_to('/tmp')
            config['services']['app']['volumes'][0]['source']=str(root/'backend')
            other=Path(d)/'other';other.mkdir()
            with self.assertRaises(ValueError):copy_mounts(config,root,other)
    def test_existing_evidence_redacts_and_does_not_execute_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            (root/'entrypoint.sh').write_text('POSTGRES_PASSWORD=private-test-secret\ntouch SHOULD_NOT_EXIST')
            evidence=inspect_existing(root,'compose.local.yml')
            self.assertNotIn('private-test-secret',json.dumps(evidence))
            self.assertFalse((root/'SHOULD_NOT_EXIST').exists())
    def test_external_resources_stay_forbidden(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for resource in [{'external':True},{'name':'real_database'},{'driver_opts':{'device':'/host'}}]:
                with self.assertRaises(ValidationFailure):
                    isolated_config({'services':{'app':{}},'volumes':{'data':resource}},'devops-validation-123',root,copied_sources=root/'copies')
    def test_monolanguage_startup_uses_same_existing_path(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            import shutil
            shutil.rmtree(root/'frontend')
            (root/'entrypoint.sh').write_text('python manage.py migrate --noinput\nexec python manage.py runserver 0.0.0.0:8000\n')
            option=runtime_options(scan_repo(d))[0]
            self.assertEqual(option['status'],'reviewable')
            self.assertTrue(option['existing_configuration']['startup_database_effects'])
            self.assertIn('migrate',option['existing_configuration']['startup_evidence']['entrypoint.sh'])
    def test_routes_ignore_docstring_examples(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            (root/'backend/project').mkdir()
            (root/'backend/project/urls.py').write_text('"""Example: path("fictional/", view)"""\nurlpatterns = [path("api/admin/", admin.site.urls)]')
            inspected=inspect_existing(root,'compose.local.yml')
            self.assertEqual(inspected['route_evidence'],{'backend/project/urls.py':['api/admin/']})
            self.assertEqual(inspected['suggested_readiness'],{'service':'app','container_port':8000,'health_path':'/api/admin/login/'})
    def test_second_endpoint_failure_cannot_pass_stack(self):
        from unittest.mock import patch
        from tests.test_validation import DockerFixture, healthy
        from agent.validator import validate_docker
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);docker=DockerFixture()
            docker.config['services']['app']['ports'].append({'target':8000,'published':'0','protocol':'tcp'})
            def command(args,repo,timeout=30,**kwargs):
                result=docker(args,repo,timeout)
                if args[1]=='inspect':
                    data=json.loads(result['stdout']);data[0]['NetworkSettings']['Ports']['8000/tcp']=[{'HostIp':'127.0.0.1','HostPort':'49153'}]
                    result['stdout']=json.dumps(data)
                return result
            def response(url,**kwargs):
                result=healthy(url)
                if ':49153/' in url:result.update(healthy=False,status_code=503,error='Backend not ready')
                return result
            with patch('agent.validator.run_command',side_effect=command),patch('agent.validator.check_application_url',side_effect=response),patch('agent.validator.shutil.disk_usage',return_value=type('Usage',(),{'free':20*1024**3})()):
                result=validate_docker(root,run=True,isolated_stack=True,container_port=8080,timeout=2,readiness_timeout=.3)
            self.assertFalse(result['success'])
            self.assertEqual(len(result['application_checks']),2)
            self.assertEqual(result['cleanup']['status'],'complete')
    def test_direct_git_mount_is_not_copied(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo';root.mkdir();(root/'.git').mkdir()
            out=Path(d)/'copy';out.mkdir()
            config={'services':{'app':{'volumes':[{'type':'bind','source':str(root/'.git'),'target':'/metadata'}]}}}
            with self.assertRaisesRegex(ValueError,'excluded'):
                copy_mounts(config,root,out)
            self.assertEqual(list(out.iterdir()),[])
