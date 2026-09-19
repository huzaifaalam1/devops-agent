"""Local action policy, private journals and report redaction.

Repository files, command output and logs are untrusted data, never approval.
"""
import base64
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ACTIONS = {
    "inspect": "read_only",
    "apply": "reversible_project_edit",
    "recover": "reversible_project_edit",
    "repair": "bounded_project_repair",
    "build": "project_build",
    "run": "project_service_management",
}
TARGETS = {"Dockerfile", "docker-compose.yml", ".dockerignore"}
SENSITIVE = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|credential|private[_-]?key)")


def authorize(action, explicit=False):
    if action not in ACTIONS:
        raise ValueError("Action is outside the supported execution policy.")
    if action != "inspect" and not explicit:
        raise ValueError("This action requires its explicit command flag.")
    return {"action": action, "category": ACTIONS[action], "authorization": "explicit_command" if explicit else "read_only"}


class Redactor:
    def __init__(self, root=None):
        self.values = set()
        for key, value in os.environ.items():
            if SENSITIVE.search(key):
                self.add(value)
        if root:
            root = Path(root).resolve()
            for path in root.glob('.env*'):
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                    continue
                try:
                    for line in path.read_text().splitlines():
                        match = re.match(r'\s*(?:export\s+)?[A-Za-z_][\w]*\s*=\s*(.*)', line)
                        if match:
                            value = match[1].strip()
                            if value[:1] in ('"', "'"):
                                value = value[1:].split(value[0], 1)[0]
                            else:
                                value = value.split(' #', 1)[0].strip()
                            self.add(value)
                except (OSError, UnicodeError):
                    # If source cannot be inspected, pattern redaction still applies.
                    pass

    def add(self, value):
        if isinstance(value, str) and value:
            self.values.add(value)
            self.values.add(quote(value, safe=''))

    def learn_config(self, config):
        # All environment values, not merely names we guess are sensitive.
        for service in config.get('services', {}).values():
            environment = service.get('environment') or {}
            if isinstance(environment, dict):
                for value in environment.values():
                    if value is not None:
                        self.add(str(value))
            build = service.get('build')
            if isinstance(build, dict) and isinstance(build.get('args'), dict):
                for key, value in build['args'].items():
                    if SENSITIVE.search(key) and value is not None:
                        self.add(str(value))

    def text(self, value):
        for secret in sorted(self.values, key=len, reverse=True):
            # Even short known values are sensitive; boundary matching avoids
            # replacing every occurrence of a single letter in normal prose.
            if len(secret) < 4:
                value = re.sub(r'(?<!\w)' + re.escape(secret) + r'(?!\w)', '[REDACTED]', value)
            else:
                value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)', '[REDACTED PRIVATE KEY]', value, flags=re.S)
        value = re.sub(r'(?i)(https?://|postgres(?:ql)?://|mysql://|redis://)([^\s/@]+(?::[^\s/@]*)?@)', r'\1[REDACTED]@', value)
        value = re.sub(r'(?i)("(?:password|passwd|secret|[^"\n]*token|api[_-]?key)"\s*:\s*)"[^"\n]*"', r'\1"[REDACTED]"', value)
        value = re.sub(r'(?i)(\b(?:authorization\s*[:=]\s*(?:bearer|basic)?|password|passwd|secret|[\w.-]*token|api[_-]?key)\s*[:=]?\s*)("[^"\n]*"|\x27[^\x27\n]*\x27|[^\s,;&]+)', r'\1[REDACTED]', value)
        value = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', value)
        value = ''.join(c for c in value if ord(c) >= 32 or c in '\n\t')
        return value

    def clean(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.clean(item) for item in value]
        if isinstance(value, dict):
            return {key: ('[REDACTED]' if SENSITIVE.search(str(key)) and item is not None else self.clean(item)) for key, item in value.items()}
        return value


def sha(data):
    return hashlib.sha256(data).hexdigest()


def state_directory(create=True):
    root = Path(os.environ.get('DEVOPS_AGENT_STATE_DIR', str(Path.home() / '.local/state/devops-agent'))).absolute()
    # macOS temporary paths legitimately use /var -> /private/var. Canonicalize
    # ancestors, but never accept a symlink at the configured journal directory.
    if root.is_symlink():
        raise ValueError('Journal storage must not be a symlink.')
    root = root.parent.resolve() / root.name
    if not root.exists() and not create:
        return root
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    mode = root.stat()
    if mode.st_uid != os.getuid() or stat.S_IMODE(mode.st_mode) & 0o077:
        raise ValueError('Journal storage must be owned by this user with mode 0700.')
    return root


@contextmanager
def project_lock(root):
    """Serialize agent mutations, without claiming to lock other editors."""
    lock = state_directory() / (sha(str(Path(root).resolve()).encode()) + '.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('Unsafe project lock file.')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another agent action is active for this project; retry after it finishes.') from None
        yield
    finally:
        os.close(fd)


def check_target(root, name):
    if name not in TARGETS:
        raise ValueError('Recovery/edit target is outside the generated-file allowlist.')
    target = root / name
    if target.is_symlink() or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1)):
        raise ValueError('Edit target must be a regular file without links.')
    return target


def protect_dirty_targets(root, changes):
    if not any((parent / '.git').exists() for parent in (root, *root.parents)):
        return
    command = ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(root)]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_CONFIG'))}
    try:
        for change in changes:
            if (root / change['path']).exists():
                tracked = subprocess.run(command + ['ls-files', '--error-unmatch', '--', change['path']],
                                         capture_output=True, timeout=10, env=environment)
                if tracked.returncode:
                    raise ValueError('An existing target is untracked or ignored; preserve/reconcile it before applying.')
        result = subprocess.run(command + ['status', '--porcelain', '--untracked-files=all', '--',
                                 *[c['path'] for c in changes]], capture_output=True, timeout=10, text=True, env=environment)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('Cannot verify Git target state; refusing edits.') from None
    if result.returncode or result.stdout.strip():
        raise ValueError('A proposed target has uncommitted changes, or Git state is unavailable. Preserve/reconcile that work before applying.')


class Journal:
    def __init__(self, root, action, approval, redactor=None):
        self.root = Path(root).resolve()
        self.redactor = redactor or Redactor(self.root)
        self.id = uuid.uuid4().hex
        storage = state_directory()
        if storage.resolve().is_relative_to(self.root):
            raise ValueError('Journal storage must be outside the selected project and its build context.')
        self.path = storage / (self.id + '.json')
        self.data = {'schema_version': 1, 'id': self.id, 'repository': str(self.root),
                     'started_at': datetime.now(timezone.utc).isoformat(), 'action': action,
                     'approval': approval, 'status': 'started', 'changes': [], 'events': []}
        self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.data, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def snapshot(self, proposal):
        protect_dirty_targets(self.root, proposal['changes'])
        records = []
        for change in proposal['changes']:
            target = check_target(self.root, change['path'])
            before = target.read_bytes() if target.exists() else None
            if (sha(before) if before is not None else None) != change['before_sha256']:
                raise ValueError('Edit target changed before its recovery snapshot.')
            records.append({'path': change['path'], 'before': None if before is None else base64.b64encode(before).decode(),
                            'before_sha256': change['before_sha256'], 'after_sha256': sha(change['content'].encode()),
                            'mode': stat.S_IMODE(target.stat().st_mode) if before is not None else None})
        self.data.update(changes=records, proposal_id=proposal['id'], status='prepared')
        self.save()

    def finish(self, status, result):
        self.data['status'] = status
        self.data['events'].append(self.redactor.clean(result))
        self.save()


def _recovery(path, session_id, apply=False):
    authorize('recover', explicit=apply) if apply else authorize('inspect')
    if not re.fullmatch('[a-f0-9]{32}', session_id):
        raise ValueError('Invalid recovery session ID.')
    root = Path(path).resolve()
    record = state_directory(create=False) / (session_id + '.json')
    if record.is_symlink() or not record.is_file() or record.stat().st_mode & 0o077:
        raise ValueError('Recovery record is missing or has unsafe permissions.')
    data = json.loads(record.read_text())
    if data.get('repository') != str(root) or data.get('action') not in ('apply', 'repair') or not data.get('changes'):
        raise ValueError('Recovery record does not belong to this project edit.')
    if data.get('status') not in ('applied', 'prepared', 'repaired'):
        raise ValueError('This session cannot be automatically recovered; inspect incomplete records manually.')
    prepared = []
    if len({c['path'] for c in data['changes']}) != len(data['changes']):
        raise ValueError('Recovery record has duplicate targets.')
    for change in data['changes']:
        target = check_target(root, change['path'])
        if not target.exists() or sha(target.read_bytes()) != change['after_sha256']:
            raise ValueError('A generated file changed or disappeared; refusing to overwrite subsequent work.')
        before = None if change['before'] is None else base64.b64decode(change['before'], validate=True)
        if (sha(before) if before is not None else None) != change['before_sha256']:
            raise ValueError('Recovery snapshot checksum mismatch.')
        prepared.append((target, before, change))
    result = {'session_id': session_id, 'status': 'preview', 'changes': [
        {'path': t.name, 'operation': 'remove_created' if b is None else 'restore_previous'} for t, b, _ in prepared]}
    if apply:
        journal = Journal(root, 'recover', authorize('recover', explicit=True))
        journal.data['source_session'] = session_id
        journal.save()
        try:
            for target, before, change in prepared:
                check_target(root, target.name)
                if sha(target.read_bytes()) != change['after_sha256']:
                    raise ValueError('File changed during recovery; stopping without overwriting it.')
                if before is None:
                    target.unlink()
                else:
                    fd = os.open(target, os.O_WRONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(before)
                        stream.truncate()
                    os.chmod(target, change['mode'] & 0o777)
            result.update(status='recovered', recovery_id=journal.id)
            journal.finish('recovered', result)
        except BaseException:
            journal.finish('incomplete', {'error': 'Recovery interrupted; inspect source snapshots and remaining files.'})
            raise
    return result


def history(path):
    """Return summaries only: recovery snapshots must never enter reports."""
    root = str(Path(path).resolve())
    result = []
    for record in sorted(state_directory(create=False).glob('*.json')):
        if record.is_symlink() or not record.is_file() or record.stat().st_mode & 0o077:
            continue
        data = json.loads(record.read_text())
        if data.get('repository') == root:
            result.append({key: data.get(key) for key in ('id', 'started_at', 'action', 'approval', 'status')})
    return sorted(result, key=lambda item: item['started_at'])


def recovery(path, session_id, apply=False):
    if apply:
        with project_lock(path):
            return _recovery(path, session_id, apply=True)
    return _recovery(path, session_id)


def repository_fingerprint(path):
    """Bounded source snapshot for stale repair refusal, never expose file values."""
    root = Path(path).resolve()
    excluded = {'.git', '.venv', 'venv', 'node_modules', '.next', '__pycache__',
                'work', 'dist', 'build', 'coverage', '.devops-agent'}
    digest = hashlib.sha256()
    count = total = 0
    def unreadable(error):
        raise error

    try:
        for parent, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
            dirs[:] = sorted(d for d in dirs if d not in excluded and not d.endswith('.egg-info'))
            if any((Path(parent) / d).is_symlink() for d in dirs):
                return None
            for name in sorted(files):
                item = Path(parent) / name
                if item.is_symlink() or not item.is_file():
                    return None
                count += 1
                total += item.stat().st_size
                if count > 2000 or total > 32 * 1024 * 1024:
                    return None
                digest.update(str(item.relative_to(root)).encode() + b'\0')
                with item.open('rb') as stream:
                    content = stream.read(32 * 1024 * 1024 + 1)
                if len(content) > 32 * 1024 * 1024:
                    return None
                digest.update(sha(content).encode())
        return digest.hexdigest()
    except OSError:
        return None
