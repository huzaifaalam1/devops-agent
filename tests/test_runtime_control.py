import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.tools import ToolRegistry
from agent import runtime_control as runtime


class RuntimeControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()/'app';self.root.mkdir()
        self.state=Path(self.tmp.name)/'state';self.state.mkdir(mode=0o700)
        self.session='a'*32;self.cid='b'*64;self.project='devops-validation-'+'c'*12
        self.journal=self.state/(self.session+'.json')
        self.journal.write_text(json.dumps({'repository':str(self.root),'action':'run','status':'succeeded','events':[{
            'cleanup':{'status':'kept_running','project':self.project},'service_states':{'app':{'id':self.cid}}}]}))
        self.journal.chmod(0o600)
        env=patch.dict(os.environ,{'DEVOPS_AGENT_STATE_DIR':str(self.state),'DOCKER_HOST':'unix:///test.sock'})
        env.start();self.addCleanup(env.stop)
        self.running=True;self.label=self.project;self.commands=[]
        mock=patch('agent.runtime_control.run_command',side_effect=self.command)
        mock.start();self.addCleanup(mock.stop)
        self.registry=ToolRegistry(self.root)

    def command(self,args,*a,**kw):
        self.commands.append(args)
        if args[1]=='ps':output=self.cid+'\n'
        elif args[1]=='inspect':output=json.dumps([{'Id':self.cid,'State':{'Running':self.running},'Config':{'Labels':{'com.docker.compose.project':self.label,'com.docker.compose.service':'app'}}}])
        elif args[1]=='stop':self.running=False;output=self.cid
        else:raise AssertionError(args)
        return {'success':True,'stdout':output,'stderr':''}

    def test_stop_requires_review_and_preserves_other_resources(self):
        params={'session_id':self.session}
        with self.assertRaises(ValueError):self.registry.execute('stop_runtime',params)
        review=self.registry.review('stop_runtime',params)
        token=self.registry.approve(review['review_id'])
        result=self.registry.execute('stop_runtime',params,approval=token)['result']
        self.assertTrue(result['success']);self.assertFalse(self.running)
        self.assertEqual([c for c in self.commands if c[1]=='stop'],[['docker','stop','--time','10',self.cid]])
        with self.assertRaises(ValueError):self.registry.execute('stop_runtime',params,approval=token)

    def test_status_reads_current_state(self):
        self.assertEqual(runtime.status(self.root)['sessions'][0]['states']['app']['state'],'running')
        self.running=False
        self.assertEqual(runtime.status(self.root)['sessions'][0]['states']['app']['state'],'stopped')
        self.assertFalse(any(c[1]=='stop' for c in self.commands))

    def test_ownership_mismatch_cannot_stop(self):
        self.label='unrelated'
        with self.assertRaises(ValueError):self.registry.review('stop_runtime',{'session_id':self.session})
        self.assertFalse(any(c[1]=='stop' for c in self.commands))

    def test_state_change_invalidates_review(self):
        review=self.registry.review('stop_runtime',{'session_id':self.session})
        self.running=False
        with self.assertRaises(ValueError):self.registry.approve(review['review_id'])

    def test_other_repository_and_unsafe_journal_refused(self):
        with self.assertRaises(ValueError):runtime.evidence(self.root.parent,self.session)
        self.journal.chmod(0o644)
        with self.assertRaises(ValueError):runtime.evidence(self.root,self.session)

    def test_remote_engine_refused(self):
        with patch.dict(os.environ,{'DOCKER_HOST':'tcp://remote:2375'}),self.assertRaises(ValueError):
            runtime.snapshot(self.root,self.session)


    def test_chat_stop_finishes_without_another_model_request(self):
        from agent.loop import AgentLoop
        from tests.test_loop import Planner,action
        loop=AgentLoop(self.root,Planner([action('runtime_status'),action('stop_runtime',{'session_id':self.session})]))
        self.addCleanup(loop.close)
        result=loop.start('kill the container')
        result=loop.answer(True)
        self.assertEqual(result['pending']['review']['tool'],'stop_runtime')
        self.assertTrue(self.running)
        result=loop.answer(True)
        self.assertEqual(result['state']['status'],'finished')
        self.assertEqual(result['state']['model_calls'],2)
        self.assertFalse(self.running)
