"""Model suggestions cannot become execution authority or verified outcomes."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from agent.main import app
from agent import planning as p
from agent import model_transport as transport
from agent.safety import Journal, authorize, repository_fingerprint
from tests.fixture_support import materialize


def proposal(bundle, action=None):
    return {'disposition': 'proposed', 'hypotheses': [
        {'text': 'The evidence suggests further inspection.', 'confidence': 'low', 'evidence_ids': ['E001']}],
        'steps': [{'action_id': action or bundle['actions'][-1]['id'], 'reason': 'Inspect the supplied evidence.', 'evidence_ids': ['E001']}],
        'uncertainties': ['Runtime behavior has not been independently verified.']}


def response(plan):
    # Adapt valid legacy display plans into the new model-only analysis contract.
    if (set(plan) == {'disposition', 'hypotheses', 'steps', 'uncertainties'}
            and plan['disposition'] == 'proposed' and len(plan['steps']) == 1
            and plan['steps'][0]['action_id'] in p.ACTION_LABELS and plan['uncertainties']):
        plan = {'observed_discrepancy': 'The supplied facts require inspection.',
                'explanation': 'The evidence does not establish a verified repair.',
                'evidence_ids': plan['steps'][0]['evidence_ids']}
    return {'body': json.dumps({'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
        'content': [{'type': 'output_text', 'text': json.dumps(plan)}]}],
        'usage': {'input_tokens': 5000, 'output_tokens': 1000, 'total_tokens': 6000}})}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = materialize('minimal', self.root / 'app')
        env = patch.dict(os.environ, {'DEVOPS_AGENT_STATE_DIR': str(self.root / 'state'), 'OPENAI_API_KEY': 'fake-secret-for-test', 'DEVOPS_AGENT_PROVIDER': 'openai'})
        env.start()
        self.addCleanup(env.stop)

    def preview(self, **kwargs):
        return p.preview_advice(self.repo, 'gpt-5.2', **kwargs)

    def send(self, reply=None, **kwargs):
        preview = self.preview()
        bundle = json.loads(preview['request']['input'][0]['content'])
        with patch.object(p, 'request_once', return_value=reply or response(proposal(bundle))) as call:
            result = p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'], **kwargs)
            self.assertEqual(call.call_count, 1)
        return result

    def record(self, **extra):
        report = {'success': False, 'phase': 'startup', 'error': 'Unclassified failure',
                  'cleanup': {'status': 'complete'}, 'repair_context': {'inputs_sha256': repository_fingerprint(self.repo)}}
        report.update(extra)
        journal = Journal(self.repo, 'run', authorize('run', explicit=True))
        journal.finish('succeeded' if report['success'] else 'failed', report)
        return journal.id

    def test_preview_is_readonly_sanitized_and_has_no_tools(self):
        (self.repo / '.env').write_text('PASSWORD=private-fixture-value\n')
        before = repository_fingerprint(self.repo)
        with patch.object(p, 'request_once') as call:
            preview = self.preview()
            call.assert_not_called()
        wire = json.dumps(preview['request'])
        for value in (str(self.repo), str(Path.home()), 'private-fixture-value', 'fake-secret-for-test'):
            self.assertNotIn(value, wire)
        self.assertFalse(preview['request']['store'])
        self.assertNotIn('tools', preview['request'])
        self.assertEqual(before, repository_fingerprint(self.repo))
        self.assertFalse((self.root / 'state').exists())

    def test_approval_binds_model_budget_and_repository(self):
        original = self.preview()
        self.assertNotEqual(original['id'], self.preview(max_output_tokens=1000)['id'])
        self.assertNotEqual(original['id'], p.preview_advice(self.repo, 'another-model')['id'])
        (self.repo / 'new.txt').write_text('changed')
        with patch.object(p, 'request_once') as call:
            for expected in (None, 'bad', original['id']):
                with self.assertRaises(p.PlanningError):
                    p.advise(self.repo, 'gpt-5.2', send=True, expect=expected)
            call.assert_not_called()

    def test_missing_key_and_model_fail_before_request(self):
        with self.assertRaises(p.PlanningError):
            p.preview_advice(self.repo, '')
        preview = self.preview()
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}), patch.object(p, 'request_once') as call:
            with self.assertRaises(p.PlanningError):
                p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
            call.assert_not_called()

    def test_valid_plan_is_unverified_zero_execution_with_cost(self):
        result = self.send(input_rate=1.75, output_rate=14)
        self.assertTrue(result['success'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['actions_executed'], 0)
        self.assertAlmostEqual(result['metrics']['estimated_cost_usd'], .02275)
        self.assertIsNone(result['metrics']['semantic_claim_accuracy'])
        self.assertNotIn('fake-secret-for-test', (self.root / 'state' / (result['session_id'] + '.json')).read_text())

    def test_errors_fall_back_without_retry(self):
        for error in ('timeout', 'http_error', 'response_too_large'):
            with self.subTest(error=error):
                result = self.send({'error': error, 'http_status': 429})
                self.assertFalse(result['success'])
                self.assertTrue(result['fallback_used'])
                self.assertEqual(result['baseline']['action_ids'], ['preview_setup'])
                self.assertEqual(result['actions_executed'], 0)

    def test_rejects_invented_evidence_commands_and_false_success(self):
        bundle = p.build_bundle(self.repo)[0]
        valid = proposal(bundle)
        mutations = []
        for key, value in [('command', 'rm -rf /'), ('verified', True)]:
            bad = copy.deepcopy(valid); bad[key] = value; mutations.append(bad)
        bad = copy.deepcopy(valid); bad['steps'][0]['action_id'] = 'execute_shell'; mutations.append(bad)
        bad = copy.deepcopy(valid); bad['steps'][0]['evidence_ids'] = ['E999']; mutations.append(bad)
        bad = copy.deepcopy(valid); bad['steps'] *= 2; mutations.append(bad)
        bad = copy.deepcopy(valid); bad['uncertainties'] = []; mutations.append(bad)
        bad = copy.deepcopy(valid); bad['disposition'] = 'verified'; mutations.append(bad)
        for bad in mutations:
            with self.subTest(bad=bad):
                self.assertEqual(self.send(response(bad))['status'], 'rejected')

    def test_refusal_incomplete_tool_calls_and_invalid_json_rejected(self):
        bodies = ['{"status":"completed","status":"completed"}', 'NaN',
                  json.dumps({'status': 'incomplete'}),
                  json.dumps({'status': 'completed', 'output': [{'type': 'function_call'}]}),
                  json.dumps({'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal'}]}]})]
        for body in bodies:
            self.assertEqual(self.send({'body': body})['status'], 'rejected')

    def test_abstention_is_explicit(self):
        plan = proposal(p.build_bundle(self.repo)[0]); plan.update(disposition='abstain', steps=[])
        self.assertEqual(self.send(response(plan))['status'], 'rejected')

    def test_secret_in_model_text_is_redacted(self):
        plan = proposal(p.build_bundle(self.repo)[0]); plan['uncertainties'] = ['fake-secret-for-test']
        self.assertNotIn('fake-secret-for-test', json.dumps(self.send(response(plan))))

    def test_audit_failure_prevents_send(self):
        preview = self.preview()
        with patch.object(p.Journal, 'save', side_effect=OSError('disk full')), patch.object(p, 'request_once') as call:
            with self.assertRaises(OSError):
                p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
            call.assert_not_called()

    def test_cancellation_is_recorded(self):
        preview = self.preview()
        with patch.object(p, 'request_once', side_effect=KeyboardInterrupt):
            result = p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['actions_executed'], 0)

    def test_validation_context_is_bound_and_cleanup_restricts_actions(self):
        session = self.record(cleanup={'status': 'failed'})
        bundle, baseline, _ = p.build_bundle(self.repo, session)
        self.assertEqual(baseline['action_ids'], ['inspect_cleanup'])
        self.assertEqual({a['id'] for a in bundle['actions']}, {'inspect_cleanup'})
        (self.repo / 'changed').write_text('new')
        with self.assertRaises(p.PlanningError):
            p.build_bundle(self.repo, session)

    def test_success_and_kept_environment_do_not_trigger_repairs(self):
        session = self.record(success=True, cleanup={'status': 'kept_running'})
        self.assertEqual(p.build_bundle(self.repo, session)[1]['action_ids'], ['no_action'])

    def test_unsupported_project_has_no_runtime_actions(self):
        repo = materialize('unsupported', self.root / 'unsupported')
        bundle, baseline, _ = p.build_bundle(repo)
        self.assertEqual(baseline['action_ids'], ['review_project'])
        self.assertNotIn('validate_runtime', [a['id'] for a in bundle['actions']])

    def test_cli_preview_and_missing_approval_are_json(self):
        runner = CliRunner()
        args = ['advise', str(self.repo), '--model', 'gpt-5.2', '--json']
        preview = runner.invoke(app, args)
        self.assertEqual(preview.exit_code, 0, preview.output)
        self.assertEqual(json.loads(preview.output)['status'], 'preview')
        denied = runner.invoke(app, args + ['--send'])
        self.assertEqual(denied.exit_code, 1)
        self.assertIn('error', json.loads(denied.output))

    def test_evaluation_is_offline_and_does_not_claim_model_quality(self):
        from tests.planning_eval import evaluate
        with patch('agent.model_transport._worker') as worker:
            report = evaluate()
        worker.assert_not_called()
        self.assertEqual(report['requests_sent'], 0)
        self.assertEqual(report['baseline_matches'], 8)
        self.assertEqual(report['proposal_matches'], 8)
        self.assertIsNone(report['model_outperforms_baseline'])
        self.assertTrue(all(c['unsupported_claims'] is None for c in report['cases']))

    def test_final_audit_failure_is_explicit(self):
        with patch.object(p.Journal, 'finish', side_effect=OSError('disk full')):
            result = self.send()
        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'audit_failed')
        self.assertTrue(result['fallback_used'])

    def test_invalid_session_shapes_are_refused(self):
        session = self.record()
        path = self.root / 'state' / (session + '.json')
        record = json.loads(path.read_text())
        for events in (None, {}, [None], [{'repair_context': None}]):
            record['events'] = events
            path.write_text(json.dumps(record))
            with self.assertRaises(p.PlanningError):
                p.build_bundle(self.repo, session)

    def test_evidence_mapping_survives_in_result(self):
        result = self.send()
        ids = {fact['id'] for fact in result['evidence']}
        self.assertTrue(set(result['plan']['steps'][0]['evidence_ids']) <= ids)

    def test_one_action_limit_applies_even_to_distinct_allowed_actions(self):
        bundle = p.build_bundle(self.repo)[0]
        plan = proposal(bundle)
        plan['steps'].append({'action_id': 'manual_investigation', 'reason': 'Another step', 'evidence_ids': ['E001']})
        with self.assertRaises(p.PlanningError):
            p.check_plan(plan, bundle)
        self.assertNotIn('steps', p.output_schema(bundle)['properties'])

    def test_evidence_separates_observations_unknowns_and_inferences(self):
        session = self.record()
        facts = p.build_bundle(self.repo, session)[0]['facts']
        kinds = {fact['source']: fact['kind'] for fact in facts}
        self.assertEqual(kinds['analysis.eligibility'], 'observation')
        self.assertNotIn('analysis.unknowns', kinds)
        self.assertNotIn('analysis.assumptions', kinds)
        self.assertNotIn('diagnosis.hypothesis', kinds)
        self.assertIn('validation.result', kinds)

    def test_temporary_limit_retries_once_inside_deadline(self):
        preview = self.preview()
        bundle = json.loads(preview['request']['input'][0]['content'])
        limit = {'error': 'http_error', 'http_status': 429, 'error_code': 'rate_limit_exceeded', 'retry_after_seconds': 7.14}
        with patch.object(p, 'request_once', side_effect=[limit, response(proposal(bundle))]) as call, patch.object(p.time, 'sleep') as sleep:
            result = p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
        sleep.assert_called_once_with(7.14)
        self.assertTrue(result['success'])
        self.assertEqual(result['metrics']['request_count'], 2)
        self.assertEqual(call.call_count, 2)
        self.assertLessEqual(call.call_args.kwargs['timeout'], 60)

    def test_repeated_limit_is_not_retried_forever(self):
        preview = self.preview()
        limit = {'error': 'http_error', 'http_status': 429, 'error_code': 'rate_limit_exceeded', 'retry_after_seconds': 0}
        with patch.object(p, 'request_once', return_value=limit) as call, patch.object(p.time, 'sleep'):
            result = p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
        self.assertEqual(call.call_count, 2)
        self.assertFalse(result['success'])
        self.assertEqual(result['error_code'], 'rate_limit_exceeded')

    def test_quota_long_wait_or_unknown_limit_does_not_retry(self):
        for code, delay in [('insufficient_quota', 1), ('rate_limit_exceeded', 30), ('rate_limit_exceeded', float('nan')), ('unknown', 1)]:
            preview = self.preview()
            reply = {'error': 'http_error', 'http_status': 429, 'error_code': code, 'retry_after_seconds': delay}
            with patch.object(p, 'request_once', return_value=reply) as call, patch.object(p.time, 'sleep') as sleep:
                p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
            call.assert_called_once(); sleep.assert_not_called()

    def test_cancelled_retry_wait_is_recorded(self):
        preview = self.preview()
        reply = {'error': 'http_error', 'http_status': 429, 'error_code': 'rate_limit_exceeded', 'retry_after_seconds': 1}
        with patch.object(p, 'request_once', return_value=reply) as call, patch.object(p.time, 'sleep', side_effect=KeyboardInterrupt):
            result = p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
        call.assert_called_once()
        self.assertEqual(result['status'], 'cancelled')

    def test_unsupported_scope_does_not_prompt_node_migration(self):
        repo = materialize('unsupported', self.root / 'other-stack')
        bundle = p.build_bundle(repo)[0]
        blockers = [fact['value']['code'] for fact in bundle['facts'] if fact['source'] == 'analysis.blocker']
        self.assertEqual(blockers, ['unsupported_framework'])
        self.assertTrue(any(fact['source'] == 'analysis.scope' for fact in bundle['facts']))

    def test_analysis_cannot_select_actions_or_supply_checks_and_uncertainty(self):
        bundle = p.build_bundle(self.repo)[0]
        value = {'observed_discrepancy': 'Observed fact', 'explanation': 'Qualified interpretation',
                 'evidence_ids': ['E001']}
        plan = p.analysis_to_plan(value, bundle)
        self.assertEqual(plan['steps'][0]['action_id'], 'preview_setup')
        for extra in ({'action_id': 'execute_shell'}, {'uncertainty': None}, {'next_check': 'Change the interpreter'}):
            with self.assertRaises(p.PlanningError):
                p.analysis_to_plan({**value, **extra}, bundle)
        with self.assertRaises(p.PlanningError):
            p.analysis_to_plan({**value, 'evidence_ids': ['E999']}, bundle)


    def test_retained_bad_checks_and_uncertainties_are_rejected_not_sanitized(self):
        reports = Path(__file__).parents[1] / 'docs' / 'evaluations' / 'step9-v7'
        for name in ('python.json', 'native.json'):
            retained = json.loads((reports / name).read_text())['cases'][0]
            reason = retained['result']['plan']['steps'][0]['reason']
            value = {'observed_discrepancy': 'Retained response replay',
                     'explanation': 'Contract regression, not a live quality measurement.',
                     'evidence_ids': ['E001'],
                     'next_check': reason.split('Next check: ', 1)[1],
                     'uncertainty': retained['result']['plan']['uncertainties'][0]}
            preview = self.preview()
            with patch.object(p, 'request_once', return_value=response(value)):
                result = p.advise(self.repo, 'gpt-5.2', send=True, expect=preview['id'])
            self.assertFalse(result['success'])
            self.assertTrue(result['fallback_used'])
            self.assertEqual(result['actions_executed'], 0)
            self.assertNotIn('plan', result)

    def test_explanation_gets_policy_guidance_and_local_notice(self):
        bundle = p.build_bundle(self.repo)[0]
        value = {'observed_discrepancy': 'Setup is absent.',
                 'explanation': 'The supplied observation does not establish a working runtime.',
                 'evidence_ids': ['E001']}
        with patch.object(p, 'request_once') as network:
            plan = p.analysis_to_plan(value, bundle)
        network.assert_not_called()
        self.assertEqual(plan['uncertainties'], [p.ANALYSIS_NOTICE])
        self.assertTrue(plan['steps'][0]['reason'].endswith(p.ACTION_LABELS['preview_setup']))
        self.assertEqual(set(p.output_schema(bundle)['properties']), set(value))


class TransportTests(unittest.TestCase):
    def test_deadline_terminates_worker(self):
        context = MagicMock(); receiver = MagicMock(); sender = MagicMock()
        context.Pipe.return_value = (receiver, sender)
        receiver.poll.return_value = False
        process = context.Process.return_value
        process.pid = 123; process.is_alive.return_value = True
        with patch.object(transport.multiprocessing, 'get_context', return_value=context):
            self.assertEqual(transport.request_once({}, 'fake', timeout=.01), {'error': 'timeout'})
        process.terminate.assert_called_once(); process.kill.assert_called_once()
        receiver.close.assert_called_once()

    def test_worker_fixed_endpoint_no_redirect_or_proxy_and_bounded_body(self):
        for status, chunks, expected in [(200, [b'{}'], {'body': '{}'}),
                (302, [b'secret'], {'error': 'http_error', 'http_status': 302}),
                (200, [b'x' * (transport.MAX_RESPONSE_BYTES + 1)], {'error': 'response_too_large'})]:
            sender = MagicMock()
            with patch('requests.Session') as session:
                client = session.return_value.__enter__.return_value
                reply = client.post.return_value.__enter__.return_value
                reply.status_code = status; reply.iter_content.return_value = chunks
                transport._worker(sender, {}, 'fake')
                self.assertFalse(client.trust_env)
                self.assertEqual(client.post.call_args.args[0], transport.ENDPOINT)
                self.assertFalse(client.post.call_args.kwargs['allow_redirects'])
                sender.send.assert_called_once_with(expected)
                sender.close.assert_called_once()

    def test_error_metadata_never_exposes_provider_message_or_org(self):
        body = json.dumps({'error': {'code': 'rate_limit_exceeded', 'type': 'tokens', 'message': 'org_secret fake-key Please try again in 7.14s.'}})
        data = transport.error_metadata(body, {})
        self.assertEqual(data, {'error_code': 'rate_limit_exceeded', 'limit_type': 'tokens', 'retry_after_seconds': 7.14})
        self.assertNotIn('secret', json.dumps(data))
        self.assertEqual(transport.error_metadata(body, {'retry-after': '2'})['retry_after_seconds'], 2)
        self.assertNotIn('retry_after_seconds', transport.error_metadata(body, {'retry-after': 'nan'}))
