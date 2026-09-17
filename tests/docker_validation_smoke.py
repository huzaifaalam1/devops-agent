"""Opt-in real validator smoke checks using a pre-existing node:22 image.

No dependency installation or image build. This tests the production validator,
not Next.js application compatibility. All published host ports are ephemeral.
"""
import argparse
import json
import shlex
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from agent.validator import check_application_url, run_command, validate_docker

SERVER = """require('http').createServer((req,res)=>{
 if(req.url==='/'){res.writeHead(302,{Location:'/health'});res.end();}
 else if(req.url==='/auth'){res.writeHead(401);res.end();}
 else {res.writeHead(200);res.end('validation-fixture');}
}).listen(8080,'0.0.0.0')"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('work/step5-docker.json'))
    args = parser.parse_args()
    evidence = {}
    available = run_command(['docker', 'image', 'inspect', 'node:22', '--format', '{{.Id}}'], Path.cwd(), timeout=10)
    if not available['success']:
        raise SystemExit('Requires an already-cached node:22 image; no image will be pulled.')
    evidence['image_id'] = available['stdout'].strip()
    held = None
    with tempfile.TemporaryDirectory(prefix='devops-runtime-smoke-') as directory:
        root = Path(directory).resolve()
        def fixture(name, script=SERVER, published=None):
            app = root / name
            app.mkdir()
            port = {'target':8080, 'host_ip':'127.0.0.1', 'protocol':'tcp'}
            if published:
                port['published'] = str(published)
            service = {'image':'node:22', 'pull_policy':'never', 'command':['node','-e',script],
                       'ports':[port], 'healthcheck':{'test':['CMD','node','-e',"require('http').get('http://127.0.0.1:8080/health',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"], 'interval':'1s','timeout':'2s','retries':5}}
            (app/'compose.yaml').write_text(json.dumps({'services':{'app':service}}))
            return app
        try:
            app = fixture('healthy')
            held = validate_docker(str(app), compose_file='compose.yaml', run=True, keep_running=True, timeout=30, readiness_timeout=15)
            evidence['healthy_redirect'] = held
            if not held['success']:
                raise RuntimeError('Healthy runtime failed: ' + str(held.get('error')))
            port = urlparse(held['application_check']['url']).port
            conflict = fixture('conflict', published=port)
            evidence['port_conflict'] = validate_docker(str(conflict), compose_file='compose.yaml', run=True, timeout=30, readiness_timeout=12)
            evidence['original_after_conflict'] = check_application_url(held['application_check']['url'], follow_redirects=True)
            assert not evidence['port_conflict']['success']
            assert evidence['port_conflict']['phase'] == 'startup'
            assert evidence['port_conflict']['cleanup']['status'] == 'not_needed'
            assert evidence['original_after_conflict']['healthy']
            failure = fixture('failure', script="console.error('Intentional fixture failure'); process.exit(42)")
            evidence['exited_service'] = validate_docker(str(failure), compose_file='compose.yaml', run=True, timeout=30, readiness_timeout=12)
            assert not evidence['exited_service']['success']
            assert evidence['exited_service']['phase'] == 'services'
            assert evidence['exited_service']['cleanup']['status'] == 'complete'
            auth = fixture('authentication')
            evidence['authentication'] = validate_docker(str(auth), compose_file='compose.yaml', run=True, health_path='/auth', timeout=30, readiness_timeout=8)
            assert not evidence['authentication']['success']
            assert evidence['authentication']['application_check']['status_code'] == 401
            assert evidence['authentication']['cleanup']['status'] == 'complete'
        finally:
            if held and held.get('cleanup',{}).get('status') == 'kept_running':
                evidence['held_cleanup'] = run_command(shlex.split(held['cleanup']['stop_command']), app, timeout=15)
                evidence['remaining'] = run_command(['docker','ps','-aq','--filter',f"label=com.docker.compose.project={held['project']}"], app, timeout=10)
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(evidence,indent=2).replace(str(root),'<temporary-fixtures>')+'\n')
    assert evidence['held_cleanup']['success']
    assert evidence['remaining']['success'] and not evidence['remaining']['stdout'].strip()
    print('PASS: owned endpoint, same-origin redirect, healthcheck, port conflict isolation, failed startup, auth failure, cleanup.')


if __name__ == '__main__':
    main()
