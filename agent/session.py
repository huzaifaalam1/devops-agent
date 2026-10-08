"""Read-only terminal conversation shell; execution and model planning come later."""
from pathlib import Path
import re

from agent.scanner import scan_repo
from agent.detector import detect_stack
from agent.safety import Redactor


HELP = ('Ask to inspect the repo, explain blockers, or plan local setup. '
        'Commands: /status, /inspect, /cancel, /repo PATH, /help, /exit. '
        'This checkpoint inspects only; it does not run Docker or call a model.')


class Session:
    def __init__(self, emit):
        self.emit = emit
        self.repo = None
        self.goal = None
        self.analysis = None

    def say(self, message):
        self.emit(Redactor(self.repo).text(message))

    def select(self, path):
        if not str(path).strip():
            self.say('Enter an explicit application directory; an empty path is not a selection.')
            return False
        candidate = Path(path).expanduser()
        try:
            candidate = candidate.resolve(strict=True)
            if not candidate.is_dir():
                raise ValueError('Not a directory')
            # Selection verifies readability using the same bounded scanner as CLI.
            scan_repo(str(candidate))
        except (OSError, ValueError, RuntimeError):
            self.say('Cannot select that repository. Enter an existing readable application directory.')
            return False
        self.repo, self.goal, self.analysis = candidate, None, None
        self.say('Selected repository: ' + str(candidate))
        return True

    def inspect(self):
        self.say('Inspecting repository files...')
        self.analysis = None
        try:
            result = detect_stack(scan_repo(str(self.repo)))
        except (OSError, ValueError):
            self.say('Inspection failed. Check the selected path and file permissions; no readiness result is available.')
            return
        self.analysis = result
        project = result['project']
        self.say('Generation eligibility: ' + project['eligibility'] + '. Runtime readiness has not been tested.')
        for finding in project['findings']:
            evidence = finding['evidence'][0]
            self.say(f"{finding['name']}: {finding['value']} (source: {evidence['path']})")
        if project['blockers']:
            self.say('Resolve these blockers before generation:')
            for item in project['blockers']:
                self.say(f"{item['code']}: {item['message']}\nNext: {item['next_action']}")
        else:
            self.say('Next: review a Docker proposal, approve it, then build and verify the application.')
        self.say('Inspection complete. No files changed or services started by this session.')

    def handle(self, text):
        text = text.strip()
        if not text:
            return True
        lowered = text.lower()
        if lowered in {'/exit', 'exit', 'quit', '/quit'}:
            return False
        if lowered in {'/help', 'help'}:
            self.say(HELP)
            return True
        if lowered in {'/cancel', 'cancel', 'stop'}:
            self.goal = None
            self.say('Current request cancelled. Repository selection retained; this session has started no services.')
            return True
        if lowered == '/repo' or lowered.startswith('/repo '):
            path = text[5:].strip()
            if not path:
                self.say('Use /repo PATH to explicitly select another application directory.')
            else:
                self.select(path)
            return True
        if self.repo is None:
            self.say('Select an application directory with /repo PATH first.')
            return True
        if lowered in {'/status', 'status'}:
            self.say('Repository: ' + str(self.repo))
            self.say('Request: ' + (self.goal or 'none'))
            self.say('Inspection: ' + ('available; use /inspect to refresh' if self.analysis else 'not available'))
            self.say('Runtime: not tested by this session. No services started.')
            return True
        if lowered.startswith('/') and lowered != '/inspect':
            self.say('Unknown command. ' + HELP)
            return True
        words = set(re.findall(r'[a-z]+', lowered))
        if words & {'aws', 'deploy', 'deployment'}:
            self.goal = 'Prepare AWS deployment'
            self.say('AWS preparation is planned for step 9. No cloud actions are available in this session.')
        elif lowered == '/inspect' or words & {'inspect', 'analyze', 'analyse', 'blockers', 'blocked', 'explain', 'repo', 'repository', 'run', 'start', 'setup'}:
            setup = bool(words & {'run', 'start', 'setup'})
            self.goal = 'Plan local setup' if setup else 'Inspect repository'
            self.say('Plan: inspect evidence, report blockers, and explain the next step.')
            self.inspect()
            if setup:
                self.say('Execution is not connected to chat yet (steps 3–4). Existing CLI commands remain available; this request has not started the app.')
        else:
            self.say('I can inspect the selected repo or explain setup blockers. Try “inspect this repo” or “run this repo locally”. Free-form model planning arrives in step 4.')
        return True


def run_session(path, read, emit):
    """Dependency-injected I/O supports scripted tests without terminal/global state."""
    session = Session(emit)
    session.say('DevOps Agent interactive preview — read-only, no model required.')
    session.say(HELP)
    try:
        if path is not None:
            session.select(path)
        while session.repo is None:
            selected = read('Application directory (or /exit)')
            if selected.strip().lower() in {'/exit', 'exit', 'quit'}:
                return
            session.select(selected)
        while session.handle(read('You')):
            pass
    except (EOFError, KeyboardInterrupt):
        session.say('Session interrupted.')
    finally:
        session.say('Session ended. No files changed or services started by this session. History was not saved.')
