"""Range inference and generated-image/repair consistency."""
import json
import tempfile
import unittest
from pathlib import Path
from agent.node_runtime import select_node, ranges, contained
from agent.detector import detect_stack
from agent.scanner import scan_repo
from agent.docker_generator import propose_docker_files, apply_docker_proposal
from tests.fixture_support import materialize
from unittest.mock import patch


class NodeRuntimeTests(unittest.TestCase):
    def test_supported_ranges_select_contained_tags(self):
        cases = {'24': '24', '24.x': '24', '24.14': '24.14', '24.14.0': '24.14.0',
                 '^20.9.0': '20.9', '~22.14.2': '22.14.2', '>=24 <25': '24',
                 '>= 20.9.0 < 21': '20.9', '>=18': '18', '20 || 22': '20',
                 '>22': '23', '>22.14': '22.15', '>22.14.0': '22.14.1',
                 'v24.14.0': '24.14.0', '>=22.14.2 <=22.14.2': '22.14.2'}
        for spec, expected in cases.items():
            with self.subTest(spec=spec):
                actual = select_node([spec])
                self.assertEqual(actual, expected)
                self.assertTrue(contained(ranges(actual), ranges(spec)))

    def test_intersection_honors_next_and_runtime_files(self):
        self.assertEqual(select_node(['>=18', '^20.9.0 || >=22', '24.14.0']), '24.14.0')
        self.assertEqual(select_node(['>=18', '^20.9.0 || >=22']), '20.9')
        for constraints in (['18', '>=20.9'], ['>=24 <22'], ['^22', '24']):
            with self.assertRaises(ValueError):
                select_node(constraints)

    def test_no_default_or_untrusted_tag_interpolation(self):
        for spec in (None, 24, '', '*', 'latest', 'lts/*', '22 - 24', '24.0.0-rc.1',
                     '22;RUN echo bad', '22\nRUN bad', '22 ||', '022', '22.x.1'):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                select_node([spec])

    def test_new_major_generation_and_stale_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);repo = materialize('minimal', root/'app')
            package = json.loads((repo/'package.json').read_text())
            lock = json.loads((repo/'package-lock.json').read_text())
            package['engines']['node'] = '24.14.0'
            lock['packages']['']['engines'] = package['engines']
            (repo/'package.json').write_text(json.dumps(package))
            (repo/'package-lock.json').write_text(json.dumps(lock))
            proposal = propose_docker_files(repo)
            self.assertEqual(proposal['status'], 'ready')
            dockerfile = next(c for c in proposal['changes'] if c['path']=='Dockerfile')
            self.assertIn('FROM node:24.14.0\n', dockerfile['content'])
            self.assertIn('24.14.0', dockerfile['reason'])
            (repo/'.nvmrc').write_text('22')
            with patch.dict('os.environ', {'DEVOPS_AGENT_STATE_DIR': str(root/'state')}):
                with self.assertRaises(ValueError):
                    apply_docker_proposal(proposal)
            self.assertFalse((repo/'Dockerfile').exists())
            codes=[b['code'] for b in detect_stack(scan_repo(str(repo)))['project']['blockers']]
            self.assertIn('runtime_conflict',codes)

    def test_existing_matching_non22_dockerfile_is_not_a_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=materialize('minimal',Path(tmp)/'app')
            package=json.loads((repo/'package.json').read_text())
            lock=json.loads((repo/'package-lock.json').read_text())
            package['engines']['node']='24'
            lock['packages']['']['engines']=package['engines']
            (repo/'package.json').write_text(json.dumps(package));(repo/'package-lock.json').write_text(json.dumps(lock))
            (repo/'Dockerfile').write_text('FROM node:24-slim\n')
            (repo/'compose.yaml').write_text('services: {}\n')
            project=detect_stack(scan_repo(str(repo)))['project']
            self.assertEqual(project['node_version'],'24')
            self.assertEqual(project['eligibility'],'eligible')
