"""Opt-in real Next.js port and readiness-path repair acceptance."""
import argparse
import json
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path

from agent.docker_generator import propose_docker_files, apply_docker_proposal, development_compose
from agent.repair import propose_repair, apply_repair
from agent.validator import validate_docker, run_command
from tests.fixture_support import materialize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('work/step8-docker.json'))
    args = parser.parse_args()
    evidence = {'success': False, 'scope': 'Real generated Next.js development image; two approved bounded repairs with automatic validator cleanup.'}
    with tempfile.TemporaryDirectory(prefix='devops-repair-smoke-') as directory:
        root = Path(directory).resolve()
        os.environ['DEVOPS_AGENT_STATE_DIR'] = str(root / 'state')
        os.environ['BUILDX_CONFIG'] = str(root / 'buildx')
        repo = materialize('minimal', root / 'app')
        owner = socket.socket()
        try:
            evidence['free_bytes'] = shutil.disk_usage(repo).free
            if evidence['free_bytes'] < 8 * 1024**3:
                raise RuntimeError('Less than 8 GiB free; no Docker build started.')
            engine = run_command(['docker', 'version'], repo, timeout=15)
            if not engine['success']:
                raise RuntimeError('Docker is unavailable: ' + engine['stderr'])
            for route, status in (('auth', 401), ('health', 200)):
                target = repo / 'app' / route
                target.mkdir()
                (target / 'route.js').write_text(f"export function GET() {{ return new Response('repair-fixture', {{status: {status}}}); }}\n")
            apply_docker_proposal(propose_docker_files(repo))
            owner.bind(('127.0.0.1', 0))
            owner.listen()
            old_port = owner.getsockname()[1]
            # Only the generated host-port field changes to create a fixture-owned conflict.
            (repo / 'docker-compose.yml').write_text(development_compose([], old_port))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                replacement = probe.getsockname()[1]
            print('Reproducing a port conflict, then applying the reviewed repair...', flush=True)
            source = validate_docker(repo, compose_file='docker-compose.yml', run=True)
            evidence['port_source'] = source
            assert not source['success'] and source['phase'] == 'startup'
            plan = propose_repair(repo, source['session_id'], host_port=replacement)
            assert plan['status'] == 'ready', plan
            evidence['port_repair'] = apply_repair(plan, plan['id'])
            assert evidence['port_repair']['success'], evidence['port_repair']
            with socket.create_connection(('127.0.0.1', old_port), timeout=2):
                evidence['original_owner_preserved'] = True
            # Docker Desktop can release its host-port proxy after container removal.
            # Use an independent binding for the next scenario instead of relying on timing.
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                auth_port = probe.getsockname()[1]
            (repo / 'docker-compose.yml').write_text(development_compose([], auth_port))
            print('Reproducing HTTP 401, then verifying the supplied /health route...', flush=True)
            source = validate_docker(repo, compose_file='docker-compose.yml', run=True,
                                     health_path='/auth', timeout=300, readiness_timeout=15)
            evidence['auth_source'] = source
            assert not source['success'] and (source.get('application_check') or {}).get('status_code') == 401, source
            # Wait only for this fixture's published port to finish releasing.
            # This is pre-approval setup, not another repair attempt.
            deadline = time.monotonic() + 30
            while True:
                try:
                    with socket.socket() as probe:
                        probe.bind(('127.0.0.1', auth_port))
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Fixture host port did not release within 30 seconds.')
                    time.sleep(.25)
            before = (repo / 'docker-compose.yml').read_bytes()
            plan = propose_repair(repo, source['session_id'], health_path='/health')
            assert plan['status'] == 'ready', plan
            evidence['auth_repair'] = apply_repair(plan, plan['id'])
            assert evidence['auth_repair']['success'], evidence['auth_repair']
            assert (repo / 'docker-compose.yml').read_bytes() == before
            for report in (evidence['port_repair']['validation'], source, evidence['auth_repair']['validation']):
                assert report['cleanup']['status'] == 'complete', report
                inventory = run_command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + report['project']], repo, timeout=10)
                assert inventory['success'] and not inventory['stdout'].strip(), inventory
            evidence['success'] = True
        except Exception as error:
            evidence['error'] = str(error)
        finally:
            owner.close()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2).replace(str(root), '<temporary-fixture>') + '\n')
    if not evidence['success']:
        raise SystemExit('FAIL: ' + evidence.get('error', 'See report.'))
    print('PASS: real Next.js port repair and auth-path repair, original owner preserved, no project containers remain.')


if __name__ == '__main__':
    main()
