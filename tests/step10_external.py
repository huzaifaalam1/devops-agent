"""Opt-in external pilots on isolated committed snapshots; never edit upstream."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
import tempfile
import time
from urllib.request import ProxyHandler, build_opener
from unittest.mock import patch

from agent.loop import AgentLoop
from agent.loop_model import NextActionModel
from agent.runtime_control import snapshot
from tests.django_step6_smoke import docker
from tests.step8_eval import frozen_inputs

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {'django': 'django-helloworld', 'nextjs': 'docker-nextjs-sample'}
REQUESTS = {
    'django': 'Generate Docker setup for this Django app using its declared Python version. Build and run it on port 8000, verify its public root page and keep it running. Do not run migrations or change application code.',
    'nextjs': 'Run this Next.js app using the existing Dockerfile.dev and explicitly selected compose.pilot.yaml. Use existing_setup=true, build and verify the public root page, and keep it running. Preserve all application and dependency files.',
}


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args])


def prepare(kind, source, repo):
    repo.mkdir()
    with tarfile.open(fileobj=io.BytesIO(git(source, 'archive', 'HEAD'))) as archive:
        archive.extractall(repo, filter='data')
    before = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.rglob('*') if p.is_file()}
    if kind == 'django':
        # Upstream's own Dockerfile selects Python 3.11; do not infer from host.
        assert 'FROM python:3.11' in (repo/'Dockerfile').read_text()
        (repo/'Dockerfile').rename(repo/'Dockerfile.upstream.txt')
        (repo/'.python-version').write_text('3.11\n')
        changes = ['Preserved original Dockerfile as Dockerfile.upstream.txt to exclude its automatic migrations from execution.', 'Declared .python-version=3.11, matching upstream Dockerfile. No dependency, settings, view or database edits.']
    else:
        shutil.copyfile(ROOT/'docs/pilots/2026-10-07/runtime/compose.pilot.yaml', repo/'compose.pilot.yaml')
        changes = ['Added previously reviewed single-app compose.pilot.yaml; unmodified upstream Dockerfile.dev and lockfiles, ephemeral loopback port, telemetry disabled.']
    return before, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=SOURCES, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    source = ROOT.parent/SOURCES[args.case]
    args.directory.mkdir(parents=True, exist_ok=True)
    manifest = args.directory/(args.case+'-manifest.json')
    record = {'candidate': frozen_inputs(), 'upstream_revision': git(source, 'rev-parse', 'HEAD').decode().strip(),
              'upstream': git(source, 'remote', 'get-url', 'origin').decode().strip(), 'request': REQUESTS[args.case],
              'scope': 'Assisted external pilot; real model and Docker, harness-approved reviews; no independent human review.',
              'success_rule': 'Verified runtime, independent expected page, unchanged upstream application files, reviewed stop, scoped cleanup, unrelated running containers preserved.',
              'spacing_seconds': 35, 'automatic_retry': False}
    if args.freeze:
        with manifest.open('x') as out: json.dump(record, out, indent=2)
        return 0
    assert json.loads(manifest.read_text()) == record, 'Candidate or upstream changed; freeze a fresh full set.'
    with (args.directory/(args.case+'.started')).open('x') as out: out.write(str(time.time()))
    assert shutil.disk_usage(ROOT).free >= 8*1024**3, '8 GiB free required'
    if args.case == 'django':
        with socket.socket() as probe: probe.bind(('127.0.0.1', 8000))
    before = set(docker('ps', '-q', '--no-trunc').split())
    report = {'success': False, 'approvals': [], 'manifest': record}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='step10-external-') as directory:
        base = Path(directory).resolve(); repo = base/'app'
        upstream_files, changes = prepare(args.case, source, repo)
        report['manual_preparation'] = changes
        os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'), BUILDX_CONFIG=str(base/'buildx'))
        loop = AgentLoop(repo, emit=lambda value: print(value, flush=True)); runtime = None
        original = NextActionModel.choose; last = [0.0]
        def paced(model, context):
            time.sleep(max(0, 35-(time.monotonic()-last[0])))
            try: return original(model, context)
            finally: last[0] = time.monotonic()
        try:
            with patch.object(NextActionModel, 'choose', paced):
                result = loop.start(REQUESTS[args.case])
                while result.get('pending'):
                    pending = result['pending']
                    if pending['kind'] == 'action':
                        review = pending['review']; name = review['tool']
                        assert name in ({'apply_docker','validate_runtime'} if args.case == 'django' else {'validate_runtime'}), name
                        if name == 'validate_runtime':
                            assert review['parameters'].get('run') and review['parameters'].get('keep_running')
                            if args.case == 'nextjs':
                                assert review['parameters'].get('compose_file') == 'compose.pilot.yaml'
                                assert review['parameters'].get('existing_setup') is True
                        else:
                            assert {c['path'] for c in review['preview']['changes']} == {'Dockerfile','docker-compose.yml','.dockerignore'}
                        report['approvals'].append({'tool': name, 'parameters': review['parameters']})
                    result = loop.answer(True)
            report['conversation'] = result
            assert result['state']['status'] == 'verified', result['state'].get('message')
            runtime = next(o['result'] for o in reversed(result['state']['observations']) if o['tool']=='validate_runtime' and o['result'].get('success'))
            with build_opener(ProxyHandler({})).open(runtime['application_check']['url'], timeout=20) as response:
                body = response.read(2*1024*1024).decode()
                markers = ['Hello, world!'] if args.case == 'django' else ['Next.js Resources', 'Docker Resources']
                report['independent_http'] = {'status': response.status, 'markers': {m:m in body for m in markers}}
                assert response.status == 200 and all(report['independent_http']['markers'].values())
            report['upstream_files_preserved'] = all(hashlib.sha256((repo/('Dockerfile.upstream.txt' if args.case=='django' and p=='Dockerfile' else p)).read_bytes()).hexdigest()==digest for p,digest in upstream_files.items())
            assert report['upstream_files_preserved']
            params = {'session_id':runtime['session_id']}; review = loop.registry.review('stop_runtime',params)
            report['stop'] = loop.registry.execute('stop_runtime',params,approval=loop.registry.approve(review['review_id']))['result']
            assert report['stop']['success']; report['success'] = True
        except Exception as error:
            report['error'] = loop.redactor.text(str(error))
            report['model_diagnostic'] = loop.redactor.clean(loop.model.last_diagnostic)
        finally:
            if loop.thread:
                report['conversation'] = loop.snapshot()
                if runtime is None:
                    runtime = next((o['result'] for o in reversed(report['conversation']['state'].get('observations',[])) if o['tool']=='validate_runtime' and o['result'].get('cleanup',{}).get('status')=='kept_running'), None)
            report['cleanup_verified'] = False
            if runtime:
                owned = snapshot(repo,runtime['session_id']); project = owned['project']
                for cid in owned['containers'].values(): docker('rm','-f',cid)
                for network in docker('network','ls','-q','--filter','label=com.docker.compose.project='+project).split(): docker('network','rm',network)
                for image in docker('image','ls','--format','{{.Repository}}:{{.Tag}}',project+'-*').split(): docker('image','rm',image)
                report['cleanup_verified'] = not docker('ps','-aq','--filter','label=com.docker.compose.project='+project)
            report['unrelated_containers_preserved'] = before.issubset(set(docker('ps','-q','--no-trunc').split()))
            report['success'] = report['success'] and report['cleanup_verified'] and report['unrelated_containers_preserved']
            report['elapsed_seconds'] = round(time.monotonic()-started,2)
            encoded = json.dumps(loop.redactor.clean(report),indent=2).replace(str(base),'<temporary-pilot>')
            (args.directory/(args.case+'.json')).write_text(encoded+'\n'); loop.close()
    return 0 if report['success'] else 1

if __name__ == '__main__': raise SystemExit(main())
