"""Opt-in frozen live Node/Vue pilots; originals and unrelated Docker resources preserved."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener
from agent.loop import AgentLoop
from agent.loop_model import NextActionModel, PROMPT_VERSION
from agent.runtime_control import snapshot
from tests.django_step6_smoke import docker
from tests.step8_eval import frozen_inputs

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'media-facility'
PREFIX='media_facility_frontend/media_facility_frontend/'
REQUESTS={'vue':'Generate Docker setup for this Vue/Vite frontend using its existing port and dependency/runtime evidence. Build and verify the frontend HTTP server and leave it running. Do not change application source or claim backend/API verification.',
          'node':'Generate Docker setup for this Node HTTP app, build it, verify its page and leave it running. Preserve the source and use its evidenced port.'}

def tracked():
    return [p for p in subprocess.check_output(['git','-C',str(SOURCE),'ls-files','-z','--',PREFIX]).decode().split('\0') if p]

def source_hashes():
    return {p:hashlib.sha256((SOURCE/p).read_bytes()).hexdigest() for p in tracked() if (SOURCE/p).is_file() and not Path(p).name.startswith('.env')}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--case',choices=REQUESTS);parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args()
    args.directory.mkdir(parents=True,exist_ok=True);manifest=args.directory/'manifest.json'
    model=NextActionModel()
    record={'hashes':frozen_inputs(),'source_hashes':source_hashes(),'requests':REQUESTS,'prompt':PROMPT_VERSION,'provider':model.provider,'model':model.model,'success':'Real model, separately reviewed generated files/runtime, HTTP and Vue module transform, unchanged copied source, scoped stop/cleanup. No backend business-operation claim.'}
    if args.freeze:
        with manifest.open('x') as f:json.dump(record,f,indent=2)
        return 0
    assert record==json.loads(manifest.read_text()),'Candidate/source changed; freeze a fresh set.'
    with (args.directory/(args.case+'.started')).open('x') as f:f.write(str(time.time()))
    assert shutil.disk_usage(ROOT).free>=8*1024**3,'8 GiB free disk required'
    before=set(docker('ps','-q','--no-trunc').split());report={'success':False,'approvals':[],'case':args.case}
    with tempfile.TemporaryDirectory(prefix='node-pilot-') as d:
        base=Path(d).resolve();repo=base/'app';repo.mkdir()
        if args.case=='vue':
            for p in record['source_hashes']:
                source=SOURCE/p;assert not source.is_symlink()
                target=repo/p[len(PREFIX):];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            report['preparation']='Working tracked frontend files copied; ignored installs/build output and dotenv omitted; no source/dependency edits.'
            port=3000
        else:
            package={'name':'node-runtime-pilot','version':'1.0.0','engines':{'node':'>=22'},'scripts':{'start':'node server.js'}}
            (repo/'package.json').write_text(json.dumps(package));(repo/'package-lock.json').write_text(json.dumps({'name':package['name'],'version':'1.0.0','lockfileVersion':3,'packages':{'':{k:v for k,v in package.items() if k!='scripts'}}}))
            (repo/'server.js').write_text("require('node:http').createServer((req,res)=>res.end('node-runtime-ready')).listen(3210, '0.0.0.0');\n");port=3210
        original_files={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.rglob('*') if p.is_file()}
        os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
        loop=AgentLoop(repo,emit=lambda s:print(s,flush=True));runtime=None
        choose=NextActionModel.choose;last=[0.0]
        def paced(model,ctx):
            time.sleep(max(0,35-(time.monotonic()-last[0])))
            try:return choose(model,ctx)
            finally:last[0]=time.monotonic()
        try:
            with patch.object(NextActionModel,'choose',paced):
                result=loop.start(REQUESTS[args.case])
                while result.get('pending'):
                    p=result['pending']
                    if p['kind']=='action':
                        review=p['review'];assert review['tool'] in {'apply_docker','validate_runtime'}
                        if review['tool']=='apply_docker':assert {c['path'] for c in review['preview']['changes']}=={'Dockerfile','docker-compose.yml','.dockerignore'}
                        else:assert review['parameters'].get('run') and review['parameters'].get('keep_running')
                        report['approvals'].append({'tool':review['tool'],'parameters':review['parameters']})
                    result=loop.answer(True)
            assert result['state']['status']=='verified',result['state'].get('message')
            runtime=next(o['result'] for o in result['state']['observations'] if o['tool']=='validate_runtime' and o['result'].get('success'))
            url=runtime['application_check']['url'];assert f':{port}/' in url
            paths=['/','/src/main.js','/src/App.vue'] if args.case=='vue' else ['/']
            report['http']={}
            for path in paths:
                with build_opener(ProxyHandler({})).open(url.rstrip('/')+path,timeout=40) as response:
                    body=response.read(2*1024*1024).decode();assert response.status==200
                    if args.case=='node':assert 'node-runtime-ready' in body
                    if path=='/src/App.vue':assert 'vue' in body.lower()
                    report['http'][path]={'status':response.status,'sha256':hashlib.sha256(body.encode()).hexdigest()}
            assert all(hashlib.sha256((repo/p).read_bytes()).hexdigest()==h for p,h in original_files.items())
            report['source_preserved']=True
            params={'session_id':runtime['session_id']};review=loop.registry.review('stop_runtime',params)
            report['stop']=loop.registry.execute('stop_runtime',params,approval=loop.registry.approve(review['review_id']))['result'];assert report['stop']['success']
            report['success']=True
        except Exception as e:
            report['error']=loop.redactor.text(str(e));report['model_diagnostic']=loop.redactor.clean(loop.model.last_diagnostic)
        finally:
            if loop.thread:
                report['conversation']=loop.snapshot()
                if runtime is None:runtime=next((o['result'] for o in report['conversation']['state']['observations'] if o['tool']=='validate_runtime' and o['result'].get('cleanup',{}).get('status')=='kept_running'),None)
            report['cleanup_verified']=False
            if runtime:
                owned=snapshot(repo,runtime['session_id']);project=owned['project']
                for cid in owned['containers'].values():docker('rm','-f',cid)
                for network in docker('network','ls','-q','--filter','label=com.docker.compose.project='+project).split():docker('network','rm',network)
                for image in docker('image','ls','--format','{{.Repository}}:{{.Tag}}',project+'-*').split():docker('image','rm',image)
                report['cleanup_verified']=not docker('ps','-aq','--filter','label=com.docker.compose.project='+project)
            report['unrelated_preserved']=before.issubset(set(docker('ps','-q','--no-trunc').split()))
            report['success']=report['success'] and report['cleanup_verified'] and report['unrelated_preserved']
            (args.directory/(args.case+'.json')).write_text(json.dumps(loop.redactor.clean(report),indent=2).replace(str(base),'<temporary-pilot>')+'\n');loop.close()
    print(json.dumps({k:report.get(k) for k in ['success','error','cleanup_verified']}));return 0 if report['success'] else 1
if __name__=='__main__':raise SystemExit(main())
