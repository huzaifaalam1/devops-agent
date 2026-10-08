"""Provider response validation without network access."""
import json
import unittest
from unittest.mock import patch
from agent.loop_model import NextActionModel, ModelUnavailable


class LoopModelTests(unittest.TestCase):
    def model(self):
        with patch('agent.loop_model.settings',return_value={'DEVOPS_AGENT_PROVIDER':'groq','DEVOPS_AGENT_MODEL':'test','GROQ_API_KEY':'private'}):
            return NextActionModel()

    def reply(self,action):
        return {'body':json.dumps({'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps({'action':action})}]}]})}

    def test_structured_action_validates_local_parameters(self):
        action={'tool':'validate_runtime','parameters':{'run':True},'reason':'Verify readiness'}
        with patch('agent.loop_model.request_once',return_value=self.reply(action)) as request:
            result=self.model().choose({'request':'run'})
        self.assertEqual(result['parameters'],{'run':True})
        self.assertEqual(request.call_args.kwargs['provider'],'groq')
        self.assertNotIn('private',str(request.call_args.args[0]))

    def test_invalid_action_and_provider_errors_refused(self):
        for reply in [self.reply({'tool':'shell','parameters':{},'reason':'run'}),
                      self.reply({'tool':'validate_runtime','parameters':{'approved':True},'reason':'run'}),
                      {'body':json.dumps({'status':'incomplete','output':[]})},
                      {'error':'http_error','error_code':'rate_limit_exceeded','retry_after_seconds':7}]:
            with self.subTest(reply=reply),patch('agent.loop_model.request_once',return_value=reply),self.assertRaises(ModelUnavailable):
                self.model().choose({'request':'run'})

    def test_missing_key_does_not_send(self):
        model=self.model();model.key=''
        with patch('agent.loop_model.request_once') as request,self.assertRaises(ModelUnavailable):
            try:model.choose({})
            finally:request.assert_not_called()
