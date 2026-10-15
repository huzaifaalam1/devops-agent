"""AWS artifacts: real local schema checks, input binding, no cloud authority."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from typer.testing import CliRunner

from agent.aws_preparation import FILES, apply, propose, validate
from agent.main import app
from agent.safety import recovery
from agent.tools import ToolRegistry, ToolRefused
from tests.fixture_support import materialize
from tests.test_django_project import FIXTURE


class AwsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.repo=materialize('minimal',self.base/'app')
        env=patch.dict(os.environ,{'DEVOPS_AGENT_STATE_DIR':str(self.base/'state')});env.start();self.addCleanup(env.stop)

    def test_reviewable_parameters_never_claim_deployment(self):
        p=propose(self.repo);self.assertEqual(p['status'],'ready',p)
        self.assertFalse(p['readiness']['deployment_ready']);self.assertIn('ImageUri',p['readiness']['required_parameters'])
        self.assertFalse(any((self.repo/name).exists() for name in FILES))
        template=json.loads(next(c['content'] for c in p['changes'] if c['path']=='aws-template.json'))
        self.assertEqual(template['Resources']['Task']['Properties']['NetworkMode'],'awsvpc')
        self.assertEqual(template['Resources']['TargetGroup']['Properties']['TargetType'],'ip')
        self.assertEqual(template['Resources']['Service']['Properties']['NetworkConfiguration']['AwsvpcConfiguration']['AssignPublicIp'],'DISABLED')
        self.assertFalse(any(v['Type'].startswith('AWS::IAM::') for v in template['Resources'].values()))

    def test_nextjs_real_linter_without_network_or_project_config(self):
        apply(propose(self.repo))
        (self.repo/'.cfnlintrc').write_text('append_rules: [./untrusted_rules]\nignore_checks: [E]\n')
        with patch('socket.create_connection',side_effect=AssertionError('Network forbidden')), patch('cfnlint.config.ConfigFileArgs._find_config',side_effect=AssertionError('Local linter configuration forbidden')):
            result=validate(self.repo)
        self.assertTrue(result['success'],result);self.assertFalse(result['cloud_verified'])

    def test_django_and_secret_references_pass_real_linter(self):
        root=self.base/'django';shutil.copytree(FIXTURE,root)
        (root/'aws-runtime.json').write_text(json.dumps({'secret_names':['DATABASE_URL','DJANGO_SECRET_KEY']}))
        p=propose(root);self.assertEqual(p['status'],'ready',p);apply(p)
        result=validate(root);self.assertTrue(result['success'],result)
        self.assertTrue(any('durable database' in gap for gap in result['readiness']['unresolved']))
        t=json.loads((root/'aws-template.json').read_text());self.assertEqual(len(t['Resources']['Task']['Properties']['ContainerDefinitions'][0]['Secrets']),2)

    def test_registry_requires_fresh_one_use_approval(self):
        registry=ToolRegistry(self.repo);p=registry.execute('propose_aws',{})['result'];params={'proposal_id':p['id']}
        with self.assertRaises(ToolRefused):registry.execute('apply_aws',params)
        review=registry.review('apply_aws',params);token=registry.approve(review['review_id'])
        self.assertTrue(registry.execute('apply_aws',params,approval=token)['result']['success'])
        with self.assertRaises(ToolRefused):registry.execute('apply_aws',params,approval=token)

    def test_changed_input_invalidates_approval(self):
        registry=ToolRegistry(self.repo);p=propose(self.repo);params={'proposal_id':p['id']}
        review=registry.review('apply_aws',params);token=registry.approve(review['review_id'])
        (self.repo/'aws-runtime.json').write_text('{"secret_names": ["API_TOKEN"]}')
        with self.assertRaises(ToolRefused):registry.execute('apply_aws',params,approval=token)
        self.assertFalse((self.repo/'aws-template.json').exists())

    def test_preserves_existing_and_symlink_targets(self):
        target=self.repo/'aws-template.json';target.write_text('user owned')
        self.assertEqual(propose(self.repo)['status'],'blocked');self.assertEqual(target.read_text(),'user owned')
        target.unlink();outside=self.base/'outside';outside.write_text('preserve');target.symlink_to(outside)
        self.assertEqual(propose(self.repo)['status'],'blocked');self.assertEqual(outside.read_text(),'preserve')

    def test_tampered_proposal_and_template_are_refused(self):
        p=propose(self.repo);p['changes'][0]['content']='arbitrary change'
        with self.assertRaises(ValueError):apply(p)
        apply(propose(self.repo));(self.repo/'aws-template.json').write_text('{}')
        self.assertFalse(validate(self.repo)['success']);self.assertEqual(propose(self.repo)['status'],'blocked')

    def test_secret_values_are_not_an_input_or_output(self):
        sentinel='should-not-appear-829192';(self.repo/'.env').write_text('PRIVATE_TOKEN='+sentinel+'\n')
        p=propose(self.repo);self.assertNotIn(sentinel,json.dumps(p))
        (self.repo/'aws-runtime.json').write_text(json.dumps({'secret_names':['PRIVATE_TOKEN'],'value':sentinel}))
        p=propose(self.repo);self.assertEqual(p['status'],'blocked');self.assertNotIn(sentinel,json.dumps(p))

    def test_unsupported_repository_and_cloud_tools_refused(self):
        unsupported=materialize('unsupported',self.base/'unsupported');self.assertEqual(propose(unsupported)['status'],'blocked')
        registry=ToolRegistry(self.repo)
        for name in ['deploy_aws','aws','run_shell','create_iam_role']:
            with self.assertRaises(ToolRefused):registry.execute(name,{})
        with self.assertRaises(ToolRefused):registry.execute('propose_aws',{'region':'us-east-1'})

    def test_local_recovery_removes_only_unchanged_generated_files(self):
        result=apply(propose(self.repo));recovery(self.repo,result['session_id'],apply=True)
        self.assertFalse(any((self.repo/name).exists() for name in FILES))
        self.assertTrue((self.repo/'package.json').exists())

    def test_cli_requires_exact_proposal_and_is_idempotent(self):
        runner=CliRunner();p=propose(self.repo)
        self.assertEqual(runner.invoke(app,['aws',str(self.repo),'--apply','--expect','wrong','--json']).exit_code,1)
        result=runner.invoke(app,['aws',str(self.repo),'--apply','--expect',p['id'],'--json']);self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(propose(self.repo)['status'],'unchanged')
        result=runner.invoke(app,['aws',str(self.repo),'--check','--json']);self.assertEqual(result.exit_code,0,result.output)

    def test_permission_reminder_opens_review_but_cannot_approve(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        plan=propose(self.repo)
        ask={'tool':'finish','parameters':{},'reason':'Please confirm that I can write the proposed AWS files.'}
        loop=AgentLoop(self.repo,Planner([action('propose_aws'),ask,action('apply_aws',{'proposal_id':plan['id']})]));self.addCleanup(loop.close)
        loop.start('Prepare AWS files after review');pending=loop.answer(True)
        self.assertEqual(pending['pending']['review']['tool'],'apply_aws')
        self.assertFalse((self.repo/'aws-template.json').exists())
        done=loop.answer(False);self.assertEqual(done['state']['status'],'cancelled')
        self.assertFalse((self.repo/'aws-template.json').exists())

    def test_permission_reminder_is_bounded_and_does_not_force_writes(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        ask={'tool':'finish','parameters':{},'reason':'Please confirm the desired deployment region.'}
        loop=AgentLoop(self.repo,Planner([action('propose_aws'),ask,ask]));self.addCleanup(loop.close)
        loop.start('Prepare AWS artifacts');done=loop.answer(True)
        self.assertEqual(done['state']['status'],'finished');self.assertEqual(done['state']['model_calls'],3)
        self.assertEqual(sum(o['result'].get('code')=='aws_review_handoff' for o in done['state']['observations']),1)
        self.assertFalse((self.repo/'aws-template.json').exists())

    def test_advice_request_gets_no_approval_nudge(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        ask={'tool':'finish','parameters':{},'reason':'File creation would require approval.'}
        loop=AgentLoop(self.repo,Planner([action('propose_aws'),ask]));self.addCleanup(loop.close)
        loop.start('Can we prepare this for AWS?');done=loop.answer(True)
        self.assertEqual(done['state']['status'],'finished');self.assertEqual(done['state']['model_calls'],2)
        self.assertFalse(any(o['result'].get('code')=='aws_review_handoff' for o in done['state']['observations']))

    def test_approved_write_always_gets_real_schema_verification(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        plan=propose(self.repo)
        loop=AgentLoop(self.repo,Planner([action('propose_aws'),action('apply_aws',{'proposal_id':plan['id']})]));self.addCleanup(loop.close)
        loop.start('Create the AWS preparation files and check them');pending=loop.answer(True)
        self.assertEqual(pending['pending']['review']['tool'],'apply_aws')
        result=loop.answer(True);self.assertEqual(result['state']['status'],'prepared')
        validation=result['state']['observations'][-1]
        self.assertEqual(validation['tool'],'validate_aws');self.assertTrue(validation['result']['success'])
        self.assertFalse(validation['result']['deployment_ready']);self.assertEqual(result['state']['model_calls'],2)

    def test_failed_post_write_validation_cannot_claim_prepared(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        plan=propose(self.repo)
        loop=AgentLoop(self.repo,Planner([action('propose_aws'),action('apply_aws',{'proposal_id':plan['id']})]));self.addCleanup(loop.close)
        loop.start('Create AWS artifacts');loop.answer(True)
        with patch('agent.aws_preparation.validate',return_value={'success':False,'error':'Validator missing','deployment_ready':False}):
            result=loop.answer(True)
        self.assertEqual(result['state']['status'],'blocked');self.assertIn('files were written',result['state']['message'])
        self.assertTrue((self.repo/'aws-template.json').exists())

    def test_write_reserves_budget_for_its_mandatory_validation(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        plan=propose(self.repo)
        loop=AgentLoop(self.repo,Planner([action('apply_aws',{'proposal_id':plan['id']})]));self.addCleanup(loop.close)
        snapshot=loop.start('Prepare AWS files');loop.provider_allowed=True
        state=dict(snapshot['state']);state['count']=11
        result=loop._decide(state)
        self.assertEqual(result['status'],'blocked');self.assertIn('Not enough actions',result['message'])
        self.assertFalse((self.repo/'aws-template.json').exists())

    def test_prepare_action_reviews_exact_files_before_automatic_verification(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        loop=AgentLoop(self.repo,Planner([action('prepare_aws')]));self.addCleanup(loop.close)
        loop.start('Prepare this app for AWS');pending=loop.answer(True)
        self.assertEqual(pending['pending']['review']['tool'],'prepare_aws')
        self.assertEqual({c['path'] for c in pending['pending']['review']['preview']['changes']},set(FILES))
        self.assertFalse((self.repo/'aws-template.json').exists())
        done=loop.answer(True);self.assertEqual(done['state']['status'],'prepared')
        self.assertEqual(done['state']['model_calls'],1)
        self.assertTrue(done['state']['observations'][-1]['result']['success'])
