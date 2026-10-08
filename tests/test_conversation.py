"""Scripted human-driver tests using a real graph and fake model, no Docker."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.conversation import run_chat
from agent.loop import AgentLoop
from tests.test_loop import Planner, action
from tests.fixture_support import materialize


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.repo=materialize('minimal',self.root/'app')
        env=patch.dict(os.environ,{'DEVOPS_AGENT_STATE_DIR':str(self.root/'state')})
        env.start();self.addCleanup(env.stop)

    def test_human_can_decline_provider(self):
        entries=iter(['inspect this repo','no','/exit']);output=[]
        with patch('agent.conversation.AgentLoop',side_effect=lambda root,emit:AgentLoop(root,Planner([]),emit)):
            run_chat(str(self.repo),lambda _:next(entries),output.append)
        self.assertIn('Model request declined','\n'.join(output))
        self.assertFalse((self.repo/'Dockerfile').exists())

    def test_plan_is_reviewed_and_user_declines_apply(self):
        def apply(context):return action('apply_docker',{'proposal_id':context['observations'][-1]['result']['id']})
        entries=iter(['set up repo','yes','no','/exit']);output=[]
        with patch('agent.conversation.AgentLoop',side_effect=lambda root,emit:AgentLoop(root,Planner([action('propose_docker'),apply]),emit)):
            run_chat(str(self.repo),lambda _:next(entries),output.append)
        self.assertIn('diff','\n'.join(output))
        self.assertIn('Action declined','\n'.join(output))
        self.assertFalse((self.repo/'Dockerfile').exists())

    def test_pause_then_cancel_never_sends(self):
        entries=iter(['run app','pause','/cancel','/exit']);output=[]
        with patch('agent.conversation.AgentLoop',side_effect=lambda root,emit:AgentLoop(root,Planner([]),emit)):
            run_chat(str(self.repo),lambda _:next(entries),output.append)
        self.assertIn('Paused','\n'.join(output))
        self.assertIn('Model request declined','\n'.join(output))
