"""Opt-in real generated Next.js development build and readiness acceptance."""
import argparse
import hashlib
import json
import os
import shlex
import shutil
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from agent.validator import run_command
from tests.fixture_support import materialize

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'work/step7-nextjs.json')
    parser.add_argument('--host-port', type=int, default=3000, help='Explicit reviewed host-port override for shared test hosts; container port remains 3000.')
    args = parser.parse_args()
    if not 1 <= args.host_port <= 65535:
        parser.error('--host-port must be between 1 and 65535')
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'success': False,
              'scope': 'Generated single-app Next.js/npm development image, real npm ci, startup, HTTP marker and scoped cleanup; not a production next build.'}
    validation = None
    with tempfile.TemporaryDirectory(prefix='devops-nextjs-acceptance-') as directory:
        root = Path(directory).resolve()
        repo = materialize('minimal', root / 'app')
        # Keep Buildx metadata and journals outside the generated build context.
        os.environ['BUILDX_CONFIG'] = str(root / 'buildx')
        os.environ['DEVOPS_AGENT_STATE_DIR'] = str(root / 'state')
        try:
            report['host_free_bytes'] = shutil.disk_usage(ROOT).free
            if report['host_free_bytes'] < 8 * 1024**3:
                raise RuntimeError('Less than 8 GiB free; build not started.')
            report['docker'] = run_command(['docker', 'version', '--format', '{{json .}}'], ROOT, timeout=15)
            if not report['docker']['success']:
                raise RuntimeError('Docker preflight failed.')
            # Exercise the generated published port unchanged; never stop its owner.
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', args.host_port))
            cli = [sys.executable, '-m', 'agent.main']
            report['analysis'] = run_command(cli + ['analyze', str(repo), '--json'], ROOT)
            if not report['analysis']['success']:
                raise RuntimeError('Analysis failed.')
            report['proposal'] = run_command(cli + ['dockerize', str(repo), '--json'], ROOT)
            if not report['proposal']['success']:
                raise RuntimeError('Proposal failed.')
            proposal = json.loads(report['proposal']['stdout'])
            report['apply'] = run_command(cli + ['dockerize', str(repo), '--apply', '--expect', proposal['id'], '--json'], ROOT)
            if not report['apply']['success']:
                raise RuntimeError('Apply failed.')
            if args.host_port != 3000:
                compose = repo / 'docker-compose.yml'
                compose.write_text(compose.read_text().replace('127.0.0.1:3000:3000', f'127.0.0.1:{args.host_port}:3000'))
                report['manual_intervention'] = f'Reviewed host-port override to {args.host_port}; generated container port unchanged.'
            report['generated_sha256'] = {c['path']: hashlib.sha256((repo/c['path']).read_bytes()).hexdigest() for c in proposal['changes']}
            report['dependencies'] = json.loads((repo/'package.json').read_text())['dependencies']
            print('Building generated Next.js image and validating startup...', flush=True)
            report['runtime_command'] = run_command(cli + ['validate', str(repo), '--run', '--keep-running', '--timeout', '600', '--readiness-timeout', '120', '--json'], ROOT, timeout=750)
            validation = json.loads(report['runtime_command']['stdout'])
            report['validation'] = validation
            if not validation['success']:
                raise RuntimeError('Validation failed: ' + validation.get('error', validation['phase']))
            url = validation['application_check']['url']
            with build_opener(ProxyHandler({})).open(url, timeout=20) as response:
                body = response.read(2 * 1024 * 1024).decode()
                report['page'] = {'url': url, 'status': response.status,
                                  'fixture_marker': 'devops-agent-baseline-ready' in body}
            if not report['page']['fixture_marker']:
                raise RuntimeError('HTTP response lacked the fixture-specific Next.js page marker.')
            report['success'] = True
        except Exception as error:
            report['error'] = str(error)
        finally:
            if validation and validation.get('cleanup', {}).get('status') == 'kept_running':
                report['shutdown'] = run_command(shlex.split(validation['cleanup']['stop_command']), repo, timeout=30)
                report['remaining'] = run_command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + validation['project']], repo, timeout=15)
                report['image_cleanup'] = run_command(['docker', 'image', 'rm', validation['project'] + '-app:validation'], repo, timeout=15)
                if not all(report[k]['success'] for k in ('shutdown', 'remaining', 'image_cleanup')) or report['remaining']['stdout'].strip():
                    report['success'] = False
                    report['error'] = 'Acceptance cleanup could not be verified.'
            report['host_free_bytes_after'] = shutil.disk_usage(ROOT).free
            report['retained'] = 'Shared base images and BuildKit cache; no global prune performed.'
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2).replace(str(root), '<temporary-fixture>') + '\n')
    if not report['success']:
        raise SystemExit('FAIL: ' + report.get('error', 'See evidence report.'))
    print('PASS: generated setup, Next.js image build, startup, owned HTTP endpoint, real page marker, and cleanup.')


if __name__ == '__main__':
    main()
