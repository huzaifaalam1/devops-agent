"""Real LangGraph/SQLite checkpoints with deterministic planner and tool boundaries."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixture_support import materialize
from agent.loop import AgentLoop


class Planner:
    provider='test'
    model='scripted'
    key='test-private-provider-key'
    def __init__(self, actions): self.actions=iter(actions)
    def choose(self,context):
        action=next(self.actions)
        if callable(action): action=action(context)
        return action


def action(tool,parameters=None):
    return {'tool':tool,'parameters':parameters or {},'reason':'Test next action'}


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.repo=materialize('minimal',self.root/'app')
        env=patch.dict(os.environ,{'DEVOPS_AGENT_STATE_DIR':str(self.root/'state')})
        env.start();self.addCleanup(env.stop)

    def loop(self,actions):
        loop=AgentLoop(self.repo,Planner(actions));self.addCleanup(loop.close);return loop

    def test_provider_decline_never_calls_model(self):
        loop=self.loop([])
        result=loop.start('inspect this repo')
        self.assertEqual(result['pending']['kind'],'provider')
        result=loop.answer(False)
        self.assertEqual(result['state']['status'],'cancelled')

    def test_apply_pause_restart_requires_new_review(self):
        def apply(context):
            return action('apply_docker',{'proposal_id':context['observations'][-1]['result']['id']})
        loop=self.loop([action('propose_docker'),apply,action('finish')])
        result=loop.start('set this up');result=loop.answer(True)
        self.assertEqual(result['pending']['kind'],'action')
        self.assertFalse((self.repo/'Dockerfile').exists())
        resumed=self.loop([action('finish')])
        result=resumed.resume(result['id'])
        self.assertEqual(result['pending']['kind'],'action')
        result=resumed.answer(True)
        self.assertTrue((self.repo/'Dockerfile').exists())
        self.assertEqual(result['pending']['kind'],'provider')
        result=resumed.answer(True)
        self.assertEqual(result['state']['status'],'finished')

    def test_stale_inputs_at_approval_are_refused(self):
        def apply(context):return action('apply_docker',{'proposal_id':context['observations'][-1]['result']['id']})
        loop=self.loop([action('propose_docker'),apply])
        loop.start('setup');loop.answer(True)
        (self.repo/'README.md').write_text('changed')
        with self.assertRaises(ValueError):loop.answer(True)
        self.assertFalse((self.repo/'Dockerfile').exists())

    def test_repeated_action_stops(self):
        loop=self.loop([action('propose_docker'),action('propose_docker')])
        loop.start('setup');result=loop.answer(True)
        self.assertEqual(result['state']['status'],'blocked')
        self.assertIn('Repeated action',result['state']['message'])

    def test_invalid_tool_never_executes(self):
        loop=self.loop([action('shell',{'command':'anything'})])
        loop.start('setup');result=loop.answer(True)
        self.assertEqual(result['state']['status'],'blocked')
        self.assertFalse((self.repo/'Dockerfile').exists())

    def test_uncertain_operation_is_not_replayed(self):
        loop=self.loop([]);loop.start('setup')
        state={'action':action('apply_docker',{'proposal_id':'fake'}),'operation':'uncertain'}
        loop.conn.execute('INSERT INTO operations VALUES (?,?,?,?)',('uncertain',loop.thread,'started',None));loop.conn.commit()
        with patch.object(loop.registry,'execute') as execute:
            result=loop._execute(state)
            execute.assert_not_called()
        self.assertEqual(result['status'],'reconcile')

    def test_completed_operation_reuses_evidence(self):
        loop=self.loop([]);loop.start('setup')
        update={'status':'verified','message':'recorded'}
        loop.conn.execute('INSERT INTO operations VALUES (?,?,?,?)',('done',loop.thread,'complete',json.dumps(update)));loop.conn.commit()
        with patch.object(loop.registry,'execute') as execute:
            result=loop._execute({'action':action('validate_runtime'), 'operation':'done'})
            execute.assert_not_called()
        self.assertEqual(result,update)

    def test_secrets_not_persisted(self):
        (self.repo/'.env').write_text('PASSWORD=local-private-value\n')
        loop=self.loop([])
        loop.start('inspect local-private-value test-private-provider-key')
        self.assertNotIn('local-private-value',json.dumps(loop.snapshot()))
        self.assertNotIn('test-private-provider-key',json.dumps(loop.snapshot()))
        loop.conn.execute('PRAGMA wal_checkpoint(FULL)')
        for file in (self.root/'state').glob('conversations.sqlite*'):
            self.assertNotIn(b'local-private-value',file.read_bytes())
            self.assertNotIn(b'test-private-provider-key',file.read_bytes())

    def test_cross_repository_resume_refused(self):
        loop=self.loop([]);result=loop.start('inspect')
        other=materialize('minimal',self.root/'other')
        otherloop=AgentLoop(other,Planner([]));self.addCleanup(otherloop.close)
        with self.assertRaises(ValueError):otherloop.resume(result['id'])

    def test_real_checkpoint_after_interrupted_mutation_refuses_replay(self):
        def apply(context):return action('apply_docker',{'proposal_id':context['observations'][-1]['result']['id']})
        loop=self.loop([action('propose_docker'),apply])
        loop.start('setup');result=loop.answer(True)
        original=loop.registry.execute
        def crash(name,params,**kwargs):
            if name=='apply_docker':
                (self.repo/'partial-marker').write_text('side effect started')
                raise SystemExit('simulated process interruption')
            return original(name,params,**kwargs)
        with patch.object(loop.registry,'execute',side_effect=crash), self.assertRaises(SystemExit):
            loop.answer(True)
        resumed=self.loop([])
        with patch.object(resumed.registry,'execute') as execute:
            result=resumed.resume(result['id'])
            execute.assert_not_called()
        self.assertEqual(result['state']['status'],'reconcile')
        self.assertTrue((self.repo/'partial-marker').exists())

    def test_successful_runtime_is_grounded_in_backend(self):
        loop=self.loop([action('validate_runtime',{'run':True})])
        loop.start('run locally');loop.answer(True)
        with patch.object(loop.registry,'execute',return_value={'result':{'success':True,'phase':'application','environment_state':'stopped','cleanup':{'status':'complete'}}}):
            result=loop.answer(True)
        self.assertEqual(result['state']['status'],'verified')
        self.assertIn('stopped',result['state']['message'])

    def test_provider_failures_remain_explicit(self):
        from agent.loop_model import ModelUnavailable
        loop=self.loop([]);loop.start('run')
        with patch.object(loop.model,'choose',side_effect=ModelUnavailable('Retry after 7 seconds; no fallback.')):
            result=loop.answer(True)
        self.assertEqual(result['state']['status'],'blocked')
        self.assertIn('7 seconds',result['state']['message'])
        self.assertEqual(result['state']['model_calls'],1)

    def test_limits_prevent_another_provider_request(self):
        loop=self.loop([]);loop.start('run')
        for i in range(12):
            loop.conn.execute('INSERT INTO model_requests VALUES (?,?)',(str(i),loop.thread))
        loop.conn.commit()
        with patch.object(loop.model,'choose') as choose:
            result=loop.answer(True)
            choose.assert_not_called()
        self.assertEqual(result['state']['status'],'blocked')

    def test_raw_config_preview_is_not_checkpointed(self):
        (self.repo/'Dockerfile').write_text('FROM node:22\n')
        (self.repo/'compose.yaml').write_text('services:\n  app:\n    environment:\n      CUSTOM_NAME: private-inline-example\n')
        loop=self.loop([action('validate_runtime',{'run':True})])
        loop.start('run');loop.answer(True)
        loop.conn.execute('PRAGMA wal_checkpoint(FULL)')
        for file in (self.root/'state').glob('conversations.sqlite*'):
            self.assertNotIn(b'private-inline-example',file.read_bytes())

    def test_failure_replans_once_with_new_parameters(self):
        loop=self.loop([action('validate_runtime',{'run':True,'health_path':'/wrong'}),
                        action('validate_runtime',{'run':True,'health_path':'/health'})])
        loop.start('check the app, use /health if the root is unavailable');loop.answer(True)
        with patch.object(loop.registry,'execute',return_value={'result':{'success':False,'phase':'application','error':'HTTP 404','cleanup':{'status':'complete'}}}):
            result=loop.answer(True)
        self.assertEqual(result['pending']['review']['parameters']['health_path'],'/health')
        with patch.object(loop.registry,'execute',return_value={'result':{'success':True,'phase':'application','environment_state':'stopped','cleanup':{'status':'complete'}}}):
            result=loop.answer(True)
        self.assertEqual(result['state']['status'],'verified')
        self.assertEqual(result['state']['failures'],1)

    def test_completed_conversation_cannot_reapprove_and_resume_is_historical(self):
        loop=self.loop([action('finish')]);loop.start('inspect');result=loop.answer(True)
        with self.assertRaises(ValueError):loop.answer(True)
        result=loop.resume(result['id'])
        self.assertIn('not been rechecked',result['resume_notice'])

    def test_concurrent_resume_cannot_modify_checkpoint(self):
        import fcntl
        loop=self.loop([]);result=loop.start('inspect')
        other=self.loop([])
        lock=loop.path.parent/(result['id']+'.conversation.lock')
        with lock.open('r+') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):other.resume(result['id'])
        self.assertEqual(loop.snapshot()['state'],result['state'])

    def test_initial_inspection_is_not_repeated(self):
        loop=self.loop([action('inspect_repository')])
        loop.start('inspect');result=loop.answer(True)
        self.assertEqual(result['state']['status'],'blocked')
        self.assertEqual(result['state']['count'],1)


    def test_large_installed_dependencies_do_not_block_inspection(self):
        dependencies=self.repo/'node_modules'
        dependencies.mkdir()
        with (dependencies/'large.bin').open('wb') as stream:
            stream.truncate(101*1024*1024)
        loop=self.loop([action('finish')])
        result=loop.start('can I run this locally?')
        self.assertEqual(result['pending']['kind'],'provider')
        self.assertTrue(result['state']['observations'])
        result=loop.answer(True)
        self.assertEqual(result['state']['status'],'finished')

    def test_large_repository_still_cannot_authorize_mutation(self):
        with (self.repo/'large.bin').open('wb') as stream:
            stream.truncate(2*1024*1024*1024+1)
        loop=self.loop([action('validate_runtime',{'run':True})])
        loop.start('run this')
        result=loop.answer(True)
        self.assertEqual(result['state']['status'],'blocked')
        self.assertIn('Repository exceeds bounded review size',result['state']['message'])
        self.assertNotIn('Model selection unavailable',result['state']['message'])
        self.assertIsNone(result.get('pending'))


    def test_read_patch_review_restart_and_followup(self):
        before=(self.repo/'package.json').read_text()
        params={'path':'package.json','old_text':before,'new_text':before.replace('{','{\n  "description": "reviewed change",',1)}
        loop=self.loop([action('read_file',{'path':'package.json'}),action('patch_file',params)])
        result=loop.start('edit configuration',history=[{'role':'user','content':'Add a description'}])
        result=loop.answer(True)
        self.assertEqual(result['pending']['kind'],'action')
        self.assertEqual((self.repo/'package.json').read_text(),before)
        resumed=self.loop([action('finish')])
        result=resumed.resume(result['id'])
        self.assertIn('diff',result['pending']['review']['preview'])
        result=resumed.answer(True)
        self.assertIn('reviewed change',(self.repo/'package.json').read_text())
        self.assertEqual(result['state']['history'][0]['content'],'Add a description')
        result=resumed.answer(True)
        self.assertEqual(result['state']['status'],'finished')
