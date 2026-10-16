import json
from pathlib import Path
import tempfile
import unittest
from agent.detector import detect_stack
from agent.scanner import scan_repo
from agent.docker_generator import propose_docker_files
from agent.safety import Redactor
from agent.tools import ToolRegistry, ToolRefused

class NodeProjectsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def fixture(self,kind='vite',script='vite'):
        dependencies={'vue':'3.5.31','vite':'8.0.3'} if kind=='vite' else {}
        p={'name':'node-pilot','version':'1.0.0','scripts':{'dev':script},'dependencies':dependencies,'engines':{'node':'>=22.12.0'}}
        (self.root/'package.json').write_text(json.dumps(p));(self.root/'package-lock.json').write_text(json.dumps({'lockfileVersion':3,'packages':{'':{k:v for k,v in p.items() if k!='scripts'},'node_modules/vite':{'engines':{'node':'^20.19.0 || >=22.12.0'}}}}))
    def test_vue_wrapped_command_infers_config_port_and_generates_binding(self):
        self.fixture(script='node --no-warnings ./node_modules/.bin/vite --host 0.0.0.0')
        (self.root/'vite.config.js').write_text('export default {server: {port: 3001}}')
        p=detect_stack(scan_repo(str(self.root)))['project'];self.assertEqual(p['eligibility'],'eligible');self.assertEqual(p['application_port'],3001)
        proposal=propose_docker_files(self.root);self.assertEqual(proposal['status'],'ready')
        files={c['path']:c['content'] for c in proposal['changes']}
        self.assertIn('127.0.0.1:3001:3001',files['docker-compose.yml']);self.assertIn('"--strictPort"',files['Dockerfile']);self.assertNotIn('next dev',files['Dockerfile'])
    def test_generic_node_literal_port_and_dynamic_refusal(self):
        self.fixture('node','node server.js');(self.root/'server.js').write_text("require('http').createServer((q,s)=>s.end('ready')).listen(3210)")
        self.assertEqual(detect_stack(scan_repo(str(self.root)))['project']['application_port'],3210)
        (self.root/'server.js').write_text('server.listen(process.env.PORT)')
        self.assertEqual(propose_docker_files(self.root)['status'],'blocked')
    def test_shell_hook_and_dynamic_vite_port_blocked(self):
        self.fixture(script='vite && curl example.com');self.assertEqual(propose_docker_files(self.root)['status'],'blocked')
        self.fixture();(self.root/'vite.config.ts').write_text('export default {server:{port:Number(process.env.PORT)}}')
        self.assertEqual(propose_docker_files(self.root)['status'],'blocked')
    def test_dependency_engine_can_supply_compatibility_without_editing_manifest(self):
        self.fixture();p=json.loads((self.root/'package.json').read_text());p.pop('engines');(self.root/'package.json').write_text(json.dumps(p))
        lock=json.loads((self.root/'package-lock.json').read_text());lock['packages'][''].pop('engines');(self.root/'package-lock.json').write_text(json.dumps(lock))
        project=detect_stack(scan_repo(str(self.root)))['project'];self.assertEqual(project['eligibility'],'eligible');self.assertEqual(project['node_version'],'20.19')
    def test_compose_prefixed_secret_literals_redacted(self):
        text='environment: {POSTGRES_PASSWORD: inline-value, API_KEY: \"inline-key\"}\n  - DJANGO_SUPERUSER_PASSWORD=hunter22\n  POSTGRES_PASSWORD: "local-db-value"\n  - API_TOKEN=other-value\n  PORT: 5173\n'
        output=Redactor().text(text)
        for secret in ['hunter22','local-db-value','other-value','inline-value','inline-key']:self.assertNotIn(secret,output)
        self.assertIn('PORT: 5173',output)
    def test_multi_application_refused_before_review(self):
        for name in ['frontend','other']:
            p=self.root/name;p.mkdir();(p/'package.json').write_text('{"scripts":{"dev":"vite"}}')
        (self.root/'compose.yaml').write_text('services: {}')
        registry=ToolRegistry(self.root)
        with self.assertRaisesRegex(ToolRefused,'blocked before approval'):
            registry.review('validate_runtime',{'run':True,'existing_setup':True,'compose_file':'compose.yaml'})
        self.assertFalse(registry._reviews)

    def test_vue_cli_serve_script_and_explicit_port(self):
        self.fixture()
        package=json.loads((self.root/'package.json').read_text())
        package['dependencies']={'vue':'3.5.31','@vue/cli-service':'5.0.8'}
        package['scripts']={'serve':'vue-cli-service serve --port 8081'}
        (self.root/'package.json').write_text(json.dumps(package))
        (self.root/'package-lock.json').write_text(json.dumps({'lockfileVersion':3,'packages':{'':{k:v for k,v in package.items() if k!='scripts'}}}))
        result=detect_stack(scan_repo(str(self.root)))['project']
        self.assertEqual(result['framework'],'Vue CLI');self.assertEqual(result['application_port'],8081)
        self.assertEqual(result['command'],['npm','run','serve','--','--host','0.0.0.0','--port','8081'])
