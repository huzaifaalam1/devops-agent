"""Scripted terminal conversations; no model or Docker execution."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner
from agent.main import app
from agent.session import Session, run_session
from tests.fixture_support import materialize


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = materialize('minimal', self.root / 'app')
        self.output = []

    def test_blank_path_never_selects_working_directory(self):
        session = Session(self.output.append)
        self.assertFalse(session.select(''))
        self.assertIsNone(session.repo)

    def test_cli_prompts_and_inspects_without_flags(self):
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        result = CliRunner().invoke(app, ['chat'], input=f'{self.repo}\ninspect this repo\n/status\n/exit\n')
        self.assertEqual(result.exit_code, 0, result.stdout)
        self.assertIn('Generation eligibility: eligible', result.stdout)
        self.assertIn('Runtime readiness has not been tested', result.stdout)
        self.assertEqual(before, {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()})

    def test_setup_followup_cancel_and_unknown(self):
        session = Session(self.output.append)
        session.select(self.repo)
        session.handle('run this repo locally')
        self.assertEqual(session.goal, 'Plan local setup')
        session.handle('/cancel')
        self.assertIsNone(session.goal)
        self.assertEqual(session.repo, self.repo.resolve())
        session.handle('what is the weather?')
        self.assertIn('Execution is not connected', '\n'.join(self.output))
        self.assertIn('Free-form model planning', self.output[-1])

    def test_switch_resets_state_and_invalid_selection_preserves_it(self):
        session = Session(self.output.append)
        session.select(self.repo)
        session.handle('/inspect')
        self.assertFalse(session.select(self.root / 'missing'))
        self.assertIsNotNone(session.analysis)
        other = materialize('unsupported', self.root / 'other')
        session.handle('/repo ' + str(other))
        self.assertIsNone(session.analysis)
        self.assertIsNone(session.goal)
        session.handle('explain blockers')
        self.assertIn('unsupported_framework', '\n'.join(self.output))

    def test_eof_and_interrupt_exit_cleanly(self):
        for error in [EOFError, KeyboardInterrupt]:
            with self.subTest(error=error):
                def read(prompt):
                    raise error()
                run_session(str(self.repo), read, self.output.append)
                self.assertIn('Session ended', self.output[-1])

    def test_failure_discards_stale_analysis(self):
        session = Session(self.output.append)
        session.select(self.repo)
        session.inspect()
        with patch('agent.session.scan_repo', side_effect=OSError('private detail')):
            session.inspect()
        self.assertIsNone(session.analysis)
        self.assertNotIn('private detail', '\n'.join(self.output))

    def test_secret_and_terminal_markup_not_echoed(self):
        (self.repo / '.env').write_text('PASSWORD=hidden-example-value\n')
        session = Session(self.output.append)
        session.select(self.repo)
        session.say('hidden-example-value')
        session.handle('run hidden-example-value [bold]repo[/bold]')
        self.assertNotIn('hidden-example-value', '\n'.join(self.output))

    def test_unknown_command_and_cloud_do_not_execute(self):
        session = Session(self.output.append)
        session.select(self.repo)
        with patch('agent.session.scan_repo') as scan:
            session.handle('/shell rm -rf anything')
            session.handle('deploy to AWS')
            scan.assert_not_called()
        self.assertIn('No cloud actions', self.output[-1])

    def test_interrupt_during_inspection_ends_session(self):
        entries = iter(['inspect repo'])
        with patch('agent.session.detect_stack', side_effect=KeyboardInterrupt):
            run_session(str(self.repo), lambda _: next(entries), self.output.append)
        self.assertIn('Session interrupted', '\n'.join(self.output))
        self.assertIn('Session ended', self.output[-1])
