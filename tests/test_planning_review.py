import copy
import unittest
from tests.planning_eval import evaluate
from tests.planning_review import packet, decision, digest


class ReviewTests(unittest.TestCase):
    def test_action_perfection_alone_cannot_pass_quality_gate(self):
        report = evaluate(split='held_out')
        self.assertEqual(report['proposal_matches'], 4)
        review = packet(report)['review_template']
        self.assertFalse(decision(report, review)['acceptance_passed'])

    def test_bound_complete_review_is_required_and_ties_do_not_prove_improvement(self):
        report = evaluate(split='held_out')
        report['mode'] = 'live'  # Synthetic input to the decision unit test, not real evidence.
        review = packet(report)['review_template']
        review.update(reviewer='unit-test', reviewer_type='agent')
        for row in review['cases']:
            row.update(unsupported_claims=0, false_success_claims=0, unsafe_recommendations=0,
                       preferred='tie', rationale='Unit-test fixture')
        self.assertFalse(decision(report, review)['acceptance_passed'])
        for row in review['cases']:
            row['preferred'] = 'A' if int(digest(row['case'])[:2], 16) % 2 == 0 else 'B'
        self.assertTrue(decision(report, review)['acceptance_passed'])
        changed = copy.deepcopy(report)
        changed['cases'][0]['result']['success'] = False
        self.assertFalse(decision(changed, review)['acceptance_passed'])
        review['cases'][0]['unsupported_claims'] = 1
        self.assertFalse(decision(report, review)['acceptance_passed'])

    def test_success_fixture_contains_no_synthetic_failure(self):
        report = evaluate(split='regression', case='successful-validation')
        facts = report['cases'][0]['evidence']['facts']
        error = next(f['value'] for f in facts if f['source'] == 'validation.error')
        self.assertEqual(error, '')
        self.assertFalse(decision(report, packet(report)['review_template'])['acceptance_passed'])

    def test_previous_failures_are_routed_by_policy_without_network(self):
        report = evaluate(split='regression')
        self.assertEqual(report['proposal_matches'], 4)
        for case in report['cases']:
            self.assertEqual(len(case['evidence']['actions']), 1)
            self.assertEqual(case['evidence']['action_selection_origin'], 'deterministic')
            self.assertEqual(case['evidence']['actions'][0]['id'], case['expected_action'])
