import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent.config import settings
from agent.planning import preview_advice, advise
from tests.fixture_support import materialize
from tests.test_planning import proposal, response
import json


class ConfigTests(unittest.TestCase):
    def test_env_file_supports_quotes_comments_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / '.env'
            env.write_text('export OPENAI_API_KEY="local-test-key" # comment\nDEVOPS_AGENT_PROVIDER=openai\nDEVOPS_AGENT_MODEL=gpt-5.2 # default\nUNRELATED=ignored\n')
            with patch('agent.config.ENV_FILE', env), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(settings(), {'OPENAI_API_KEY': 'local-test-key', 'DEVOPS_AGENT_MODEL': 'gpt-5.2', 'DEVOPS_AGENT_PROVIDER': 'openai'})
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'override'}):
                    self.assertEqual(settings()['OPENAI_API_KEY'], 'override')

    def test_file_key_works_without_exports_and_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            env = base / '.env'; env.write_text('DEVOPS_AGENT_PROVIDER=openai\nOPENAI_API_KEY=local-test-key\n')
            repo = materialize('minimal', base / 'target')
            (repo / '.env').write_text('OPENAI_API_KEY=untrusted-target-key\n')
            with patch('agent.config.ENV_FILE', env), patch.dict(os.environ, {'DEVOPS_AGENT_STATE_DIR': str(base / 'state')}, clear=True):
                preview = preview_advice(repo)
                self.assertEqual(preview['request']['model'], 'gpt-5.2')
                plan = proposal(json.loads(preview['request']['input'][0]['content']))
                plan['uncertainties'] = ['local-test-key']
                with patch('agent.planning.request_once', return_value=response(plan)) as call:
                    result = advise(repo, send=True, expect=preview['id'])
                self.assertEqual(call.call_args.args[1], 'local-test-key')
                self.assertTrue(result['success'])
                self.assertNotIn('local-test-key', json.dumps(result))
                self.assertNotIn('OPENAI_API_KEY', os.environ)

    def test_missing_file_defaults_and_malformed_value_does_not_echo_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / '.env'
            with patch('agent.config.ENV_FILE', env), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(settings()['DEVOPS_AGENT_MODEL'], 'openai/gpt-oss-120b')
                env.write_text('OPENAI_API_KEY="secret-without-closing-quote\n')
                with self.assertRaises(ValueError) as error:
                    settings()
                self.assertNotIn('secret-without', str(error.exception))

    def test_groq_routes_only_its_key_and_binds_provider_to_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); env = base / '.env'
            env.write_text('GROQ_API_KEY=groq-test-secret\nOPENAI_API_KEY=openai-test-secret\n')
            repo = materialize('minimal', base / 'target')
            with patch('agent.config.ENV_FILE', env), patch.dict(os.environ, {'DEVOPS_AGENT_STATE_DIR': str(base / 'state')}, clear=True):
                preview = preview_advice(repo)
                self.assertEqual(preview['provider'], 'groq')
                self.assertNotIn('store', preview['request'])
                self.assertEqual(preview['endpoint'], 'https://api.groq.com/openai/v1/responses')
                self.assertEqual(preview['request']['model'], 'openai/gpt-oss-120b')
                other = preview_advice(repo, provider='openai')
                self.assertNotEqual(preview['id'], other['id'])
                plan = proposal(json.loads(preview['request']['input'][0]['content']))
                plan['uncertainties'] = ['groq-test-secret']
                with patch('agent.planning.request_once', return_value=response(plan)) as call:
                    result = advise(repo, send=True, expect=preview['id'])
                self.assertEqual(call.call_args.args[1], 'groq-test-secret')
                self.assertEqual(call.call_args.kwargs['provider'], 'groq')
                self.assertNotIn('groq-test-secret', json.dumps(result))

    def test_missing_groq_key_never_falls_back_to_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); env=base/'.env'; env.write_text('OPENAI_API_KEY=unused-key\n')
            repo=materialize('minimal', base/'target')
            with patch('agent.config.ENV_FILE', env), patch.dict(os.environ, {}, clear=True):
                preview=preview_advice(repo)
                with patch('agent.planning.request_once') as call:
                    with self.assertRaisesRegex(ValueError, 'GROQ_API_KEY'):
                        advise(repo, send=True, expect=preview['id'])
                    call.assert_not_called()

    def test_unknown_provider_is_refused_before_transport(self):
        from agent.model_transport import request_once
        with self.assertRaises(ValueError):
            request_once({}, 'secret', provider='https://example.com')

    def test_groq_worker_uses_allowlisted_endpoint(self):
        from agent.model_transport import _worker
        from unittest.mock import MagicMock
        sender=MagicMock()
        with patch('requests.Session') as session:
            client=session.return_value.__enter__.return_value
            reply=client.post.return_value.__enter__.return_value
            reply.status_code=200; reply.iter_content.return_value=[b'{}']
            _worker(sender, {}, 'groq-secret', provider='groq')
            self.assertEqual(client.post.call_args.args[0], 'https://api.groq.com/openai/v1/responses')
            self.assertEqual(client.post.call_args.kwargs['headers']['Authorization'], 'Bearer groq-secret')
            self.assertFalse(client.post.call_args.kwargs['allow_redirects'])

    def test_live_eval_stops_on_quota_and_records_skips(self):
        from tests.planning_eval import evaluate
        with patch.dict(os.environ, {'DEVOPS_AGENT_PROVIDER':'groq', 'DEVOPS_AGENT_MODEL':'openai/gpt-oss-120b', 'GROQ_API_KEY':'fake-groq'}):
            with patch('agent.planning.request_once', return_value={'error':'http_error', 'http_status':429}) as call:
                result=evaluate(live=True)
        call.assert_called_once()
        self.assertEqual(result['requests_sent'],1)
        self.assertEqual(result['skipped_cases'],7)
        self.assertFalse(result['cases'][0]['result']['success'])

    def test_numeric_usage_survives_redaction_but_secret_strings_do_not(self):
        from agent.safety import Redactor
        clean = Redactor().clean({'input_tokens': 123, 'output_tokens': 'secret', 'access_token': 'secret', 'total_tokens': True})
        self.assertEqual(clean['input_tokens'], 123)
        for key in ('output_tokens', 'access_token', 'total_tokens'):
            self.assertEqual(clean[key], '[REDACTED]')
