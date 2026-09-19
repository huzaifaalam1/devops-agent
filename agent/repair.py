"""One approved repair attempt, deterministic verification, guarded rollback."""
import difflib
import json
import os
import re
import socket
from urllib.parse import urlparse
from pathlib import Path

from agent.detector import detect_stack
from agent.scanner import scan_repo
from agent.diagnostics import diagnose_failure
from agent.docker_generator import DOCKERFILE, ENV_FILES, development_compose
from agent.safety import (Journal, Redactor, authorize, check_target, project_lock,
                          repository_fingerprint, sha, state_directory, _recovery)
from agent.validator import _journaled_validation


class RepairRefused(ValueError):
    pass


def read_session(root, session_id):
    if not re.fullmatch(r'[a-f0-9]{32}', session_id):
        raise RepairRefused('Invalid validation session ID.')
    file = state_directory(create=False) / (session_id + '.json')
    if (file.is_symlink() or not file.is_file() or file.stat().st_nlink != 1
            or file.stat().st_uid != os.getuid() or file.stat().st_mode & 0o077
            or file.stat().st_size > 16 * 1024 * 1024):
        raise RepairRefused('Validation session is missing or unsafe to read.')
    data = json.loads(file.read_text())
    if data.get('repository') != str(root) or data.get('action') != 'run' or data.get('status') != 'failed':
        raise RepairRefused('Select a failed runtime validation session for this exact project.')
    events = data.get('events') or []
    report = events[-1] if events else {}
    if report.get('success') is not False or not report.get('repair_context'):
        raise RepairRefused('Session lacks a replayable result; rerun validate --run first.')
    return report


def already_attempted(root, key):
    for file in state_directory(create=False).glob('*.json'):
        if file.is_symlink() or file.stat().st_mode & 0o077:
            raise RepairRefused('Unsafe session history; cannot establish the repair attempt limit.')
        data = json.loads(file.read_text())
        if data.get('repository') == str(root) and data.get('action') == 'repair' and data.get('attempt_key') == key:
            return True
    return False


def _propose_repair(path, session_id, host_port=None, health_path=None):
    root = Path(path).resolve()
    redactor = Redactor(root)
    plan = {'schema_version': 1, 'status': 'blocked', 'path': str(root),
            'source_session': session_id, 'changes': [], 'attempt_limit': 1,
            'approval': 'repair --apply --expect <proposal-id> authorizes the edit and one build/run verification',
            'blockers': [], 'unverified': ['Repair success until the requested runtime validation passes']}
    try:
        report = read_session(root, session_id)
        diagnosis = diagnose_failure(report)
        plan['diagnosis'] = diagnosis
        if report.get('cleanup', {}).get('status') not in ('complete', 'not_needed'):
            raise RepairRefused('Resolve the prior run cleanup before attempting a repair.')
        context = report['repair_context']
        fingerprint = repository_fingerprint(root)
        if not fingerprint or fingerprint != context.get('inputs_sha256'):
            raise RepairRefused('Repository inputs changed or cannot be snapshotted; rerun validate --run first.')
        analysis = detect_stack(scan_repo(str(root)))
        if analysis['project']['eligibility'] != 'eligible':
            raise RepairRefused('Project is not eligible for the first-release runtime workflow.')
        compose = context.get('compose_file')
        if not isinstance(compose, str) or Path(compose).is_absolute() or len(Path(compose).parts) != 1:
            raise RepairRefused('Repair requires a recorded root-level Compose filename.')
        if not re.fullmatch(r'/[A-Za-z0-9/_.-]*', context.get('health_path', '')):
            raise RepairRefused('Repair cannot replay a query-bearing or redacted health path.')
        validation = {key: context.get(key) for key in ('compose_file', 'health_path', 'service', 'container_port')}
        # One fixed execution budget, never a log-controlled command or retry count.
        validation.update(run=True, keep_running=False, timeout=300, readiness_timeout=90)
        category = diagnosis['type']
        if category == 'port_conflict':
            if health_path is not None:
                raise RepairRefused('A port repair cannot also change the health path.')
            if not isinstance(host_port, int) or isinstance(host_port, bool) or not 1024 <= host_port <= 65535:
                raise RepairRefused('Choose an explicit unused --host-port between 1024 and 65535.')
            if compose != 'docker-compose.yml':
                raise RepairRefused('Automatic port edits are limited to agent-generated docker-compose.yml.')
            target = check_target(root, compose)
            current = target.read_text()
            match = re.search(r'127\.0\.0\.1:(\d+):3000', current)
            mounts = [name for name in ENV_FILES if (root / name).exists()]
            if (not match or current != development_compose(mounts, int(match[1]))
                    or check_target(root, 'Dockerfile').read_text() != DOCKERFILE):
                raise RepairRefused('Compose/Dockerfile differs from the supported generated template; edit it manually.')
            old_port = int(match[1])
            if old_port == host_port:
                raise RepairRefused('Replacement host port must differ from the failed binding.')
            # Confirm the source conflict still exists, rather than repairing stale logs.
            try:
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', old_port))
            except OSError as error:
                import errno
                if error.errno != errno.EADDRINUSE:
                    raise RepairRefused('Cannot verify the original host-port conflict.') from None
            else:
                raise RepairRefused('Original port is now free; retry validation without changing files.')
            try:
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', host_port))
            except OSError:
                raise RepairRefused('Replacement host port is unavailable; no repair was applied.') from None
            content = development_compose(mounts, host_port)
            plan['changes'] = [{'path': compose, 'operation': 'update', 'before_sha256': sha(target.read_bytes()),
                                'content': content, 'diff': ''.join(difflib.unified_diff(current.splitlines(True), content.splitlines(True), fromfile='a/'+compose, tofile='b/'+compose))}]
            plan.update(kind='host_port', summary=f'Change the published host port from {old_port} to {host_port}; preserve container port 3000.',
                        impact='Changes the local URL; does not stop the current port owner.',
                        verification='Require full runtime readiness on the new inspected host port and successful cleanup.')
        elif category == 'http_authentication':
            if host_port is not None:
                raise RepairRefused('A readiness-path repair cannot also change the host port.')
            if not health_path or not re.fullmatch(r'/[A-Za-z0-9/_.-]*', health_path) or health_path.startswith('//'):
                raise RepairRefused('Supply an existing unauthenticated --health-path without credentials, query or fragment.')
            if health_path == context['health_path']:
                raise RepairRefused('Choose a readiness path different from the failed endpoint.')
            endpoint = urlparse((report.get('application_check') or {}).get('url', ''))
            if endpoint.hostname not in ('127.0.0.1', '::1') or not endpoint.port:
                raise RepairRefused('Source session lacks an owned local readiness endpoint.')
            try:
                family = socket.AF_INET6 if endpoint.hostname == '::1' else socket.AF_INET
                with socket.socket(family, socket.SOCK_STREAM) as probe:
                    probe.bind((endpoint.hostname, endpoint.port))
            except OSError:
                raise RepairRefused('The previous endpoint port is not available yet. Retry preview after it releases; no repair attempt was consumed.') from None
            validation['health_path'] = health_path
            plan.update(kind='health_path', summary=f'Retry readiness at {health_path}; leave authentication and files unchanged.',
                        impact='Applies only to this validation. Future runs must explicitly select this health path.',
                        verification='Require owned endpoint HTTP 2xx, stable service health and successful cleanup.')
        else:
            raise RepairRefused('No approved automatic repair for this diagnosis. Follow its manual action and verification guidance.')
        plan.update(inputs_sha256=fingerprint, validation=validation, host_port=host_port, health_path=health_path)
        plan['attempt_key'] = sha((str(root) + fingerprint + plan['kind']).encode())
        if already_attempted(root, plan['attempt_key']):
            raise RepairRefused('This repair was already attempted for unchanged inputs. Stop and investigate; a new session does not reset the attempt limit.')
        plan['status'] = 'ready'
        plan['id'] = sha(json.dumps(plan, sort_keys=True).encode())
    except (OSError, ValueError, KeyError, TypeError) as error:
        plan['status'] = 'blocked'
        plan['blockers'].append(str(error))
    return plan


def propose_repair(path, session_id, host_port=None, health_path=None):
    return Redactor(path).clean(_propose_repair(path, session_id, host_port, health_path))


def apply_repair(plan, expected_id):
    """Approval binds the full plan. No alternative repair is chosen after failure."""
    if plan.get('status') != 'ready' or expected_id != plan.get('id'):
        raise RepairRefused('Apply requires the ID of a ready reviewed repair proposal.')
    root = Path(plan['path']).resolve()
    redactor = Redactor(root)
    with project_lock(root):
        fresh = _propose_repair(root, plan['source_session'], plan.get('host_port'), plan.get('health_path'))
        if redactor.clean(fresh) != plan:
            raise RepairRefused('Repair proposal or project state changed. Review a fresh proposal.')
        plan = fresh
        journal = Journal(root, 'repair', authorize('repair', explicit=True), redactor)
        result = {'success': False, 'status': 'escalated', 'session_id': journal.id,
                  'source_session': plan['source_session'], 'proposal_id': plan['id'],
                  'attempts': 0, 'attempt_limit': 1, 'changes': [c['path'] for c in plan['changes']],
                  'rollback': {'status': 'not_needed'}}
        modified = False
        try:
            # Snapshot refuses dirty targets before the attempt is consumed.
            journal.snapshot(plan)
            journal.data.update(attempt_key=plan['attempt_key'], approval={**journal.data['approval'], 'proposal_id': plan['id']})
            journal.save()
            result['attempts'] = 1
            for change in plan['changes']:
                target = check_target(root, change['path'])
                # Stage completely before replacement, preserving the original on
                # disk-full/partial writes. Never apply redacted preview contents.
                original_stat = target.stat()
                staged = root / ('.devops-repair-' + journal.id + '.tmp')
                fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(change['content'].encode())
                        stream.flush()
                        os.fsync(stream.fileno())
                        os.fchmod(stream.fileno(), original_stat.st_mode & 0o777)
                    check_target(root, change['path'])
                    if target.stat().st_ino != original_stat.st_ino or sha(target.read_bytes()) != change['before_sha256']:
                        raise RepairRefused('Repair target changed before replacement.')
                    modified = True
                    os.replace(staged, target)
                finally:
                    staged.unlink(missing_ok=True)
            journal.data['status'] = 'applied'
            journal.save()
            # Outer project lock covers both the edit and this internal validation.
            validation = _journaled_validation(str(root), **plan['validation'])
            result['validation'] = validation
            result['diagnosis'] = diagnose_failure(validation)
            if validation['success']:
                result.update(success=True, status='repaired', summary=plan['summary'])
            else:
                result['error'] = 'The single repair attempt did not establish readiness; no further repair was attempted.'
                if validation.get('phase') == 'cancelled':
                    result['status'] = 'cancelled'
        except KeyboardInterrupt:
            result.update(status='cancelled', error='Repair cancelled; guarded recovery follows.')
        except Exception:
            result['error'] = 'Repair could not complete safely. Inspect this session and its recovery snapshots.'
        finally:
            if not result['success'] and modified:
                try:
                    # Recovery refuses later edits rather than overwriting them.
                    if all(sha(check_target(root, c['path']).read_bytes()) == c['before_sha256'] for c in plan['changes']):
                        result['rollback'] = {'status': 'unchanged'}
                    else:
                        result['rollback'] = _recovery(root, journal.id, apply=True)
                except (OSError, ValueError, KeyError, TypeError):
                    result['rollback'] = {'status': 'manual_recovery_required', 'session_id': journal.id}
            if not result['success']:
                result['next_action'] = 'Stop automatic attempts. Inspect the diagnosis, validation/cleanup evidence and rollback status; reconcile the cause before a new validation.'
            result = redactor.clean(result)
            try:
                journal.finish(result['status'], result)
            except (OSError, ValueError):
                result.update(success=False, status='audit_failed', error='Final repair journal write failed; inspect changes, validation and rollback state before proceeding.')
        return result
