import unittest
from unittest.mock import patch
from agent.runtime_policy import existing_setup_blockers, runtime_options
from agent.loop import compact

class RuntimePolicyTests(unittest.TestCase):
    def test_only_existing_template_checks_deferred(self):
        codes=['package_manager','unknown_runtime','runtime','runtime_conflict','docker_runtime_conflict','service_dependency','environment_missing','unsupported_framework','application_selection']
        blocking,deferred=existing_setup_blockers([{'code':c} for c in codes],run=True)
        self.assertEqual([b['code'] for b in blocking],codes[-2:])
        self.assertEqual([b['code'] for b in deferred],codes[:-2])
        blocking,_=existing_setup_blockers([{'code':'service_dependency'}],run=False)
        self.assertEqual(blocking,[{'code':'service_dependency'}])

    def test_each_explicit_selection_is_reinspected_and_compacted(self):
        def detected(info):
            self.assertIn(info['selected_compose_file'],['compose.yaml','compose.pilot.yaml'])
            return {'project':{'blockers':[{'code':'unknown_runtime'}], 'services':[]}}
        with patch('agent.detector.detect_stack',side_effect=detected):
            options=runtime_options({'compose_files':['compose.yaml','compose.pilot.yaml']})
        self.assertEqual(len(options),2)
        self.assertTrue(all(o['status']=='reviewable' and o['parameters']['existing_setup'] for o in options))
        self.assertEqual(compact('inspect_repository',{'project':{},'runtime_options':options})['runtime_options'],options)

    def test_unsupported_and_database_gates_remain_blocked(self):
        for project in [{'blockers':[{'code':'unsupported_framework'}],'services':[]}, {'blockers':[],'services':['PostgreSQL']}]:
            with patch('agent.detector.detect_stack',return_value={'project':project}):
                option=runtime_options({'compose_files':['compose.yaml']})[0]
            self.assertEqual(option['status'],'blocked')
            self.assertTrue(option['blockers'])

    def test_missing_setup_exposes_database_prerequisites_without_mutation(self):
        import tempfile
        from pathlib import Path
        from tests.test_django_database import postgres_fixture
        from agent.tools import ToolRegistry, ToolRefused
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory)/'app';postgres_fixture(repo)
            registry=ToolRegistry(repo)
            summary=compact('inspect_repository',registry.execute('inspect_repository',{})['result'])
            self.assertEqual(summary['local_setup_prerequisites']['required_order'],
                             ['propose_docker','apply_docker','prepare_database','migrate_database'])
            with self.assertRaisesRegex(ToolRefused,'First propose_docker'):
                registry.review('prepare_database',{})
            self.assertEqual(registry._reviews,{})
            self.assertFalse((repo/'docker-compose.yml').exists())

    def test_generation_blockers_are_scoped_without_losing_evidence(self):
        blocker={'code':'unknown_runtime','message':'No generation runtime selected'}
        source={'project':{'eligibility':'blocked','blockers':[blocker]},
                'runtime_options':[{'status':'reviewable','compose_file':'compose.yaml'}]}
        result=compact('inspect_repository',source)
        self.assertEqual(result['eligibility'],'existing_setup_review_available')
        self.assertEqual(result['blockers'],[])
        self.assertEqual(result['generation'],{'eligibility':'blocked','blockers':[blocker]})
        self.assertEqual(source['project']['blockers'],[blocker])
        source['runtime_options'][0]['status']='blocked'
        self.assertEqual(compact('inspect_repository',source)['blockers'],[blocker])
