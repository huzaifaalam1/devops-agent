"""Opt-in real PostgreSQL acceptance. --live additionally uses the Groq planner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from urllib.request import build_opener, ProxyHandler
from agent.tools import ToolRegistry
from agent.runtime_control import snapshot
from tests.test_django_database import postgres_fixture

ROOT=Path(__file__).resolve().parents[1]
def docker(*args):return subprocess.check_output(['docker',*args],text=True,timeout=60).strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'work/v2-step7/docker.json');args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(args.output.parent).free<8*1024**3:raise RuntimeError('8 GiB free disk required.')
    with socket.socket() as check:check.bind(('127.0.0.1',8000))
    before=set(docker('ps','-q','--no-trunc').split())
    report={'success':False,'live_model':args.live,'approvals':[],
      'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'agent').glob('*.py'))}}
    with tempfile.TemporaryDirectory(prefix='django-step7-') as directory:
        base=Path(directory).resolve();repo=base/'app';postgres_fixture(repo)
        os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
        registry=ToolRegistry(repo);runtime=None;loop=None
        def execute(name,params):
            print('Reviewed action:',name,flush=True)
            review=registry.review(name,params);report['approvals'].append({'tool':name,'parameters':params})
            return registry.execute(name,params,approval=registry.approve(review['review_id']))['result']
        try:
            if args.live:
                from agent.loop import AgentLoop
                loop=AgentLoop(repo,emit=lambda s:print(s,flush=True))
                result=loop.start('Set up this Django app using a new disposable PostgreSQL database. Prepare the migration plan, request separate approval to apply it, verify ORM operations and the root page, and keep the containers running.')
                while result.get('pending'):
                    pending=result['pending']
                    if pending['kind']=='action':
                        review=pending['review'];assert review['tool'] in {'apply_docker','prepare_database','migrate_database'},review['tool']
                        report['approvals'].append({'tool':review['tool'],'parameters':review['parameters']})
                    import time
                    time.sleep(35)  # Pace separate model decisions below the free-tier TPM cap; never retry 429.
                    result=loop.answer(True)
                report['conversation']=result
                for item in result['state']['observations']:
                    if item['tool']=='prepare_database' and item['result'].get('success'):runtime=item['result']
                assert result['state']['status']=='verified',result['state'].get('message')
                migrated=next(o['result'] for o in result['state']['observations'] if o['tool']=='migrate_database')
            else:
                proposal=registry.execute('propose_docker',{})['result']
                assert proposal['status']=='ready',proposal
                execute('apply_docker',{'proposal_id':proposal['id']})
                runtime=execute('prepare_database',{})
                report['prepare']=runtime;assert runtime['success'],runtime
                assert runtime['phase']=='database_prepared' and runtime['application_check'] is None
                assert runtime['database_plan']['pending'] and not runtime['database_plan']['orm_verified']
                result=execute('migrate_database',{'session_id':runtime['session_id']})
                report['migrate']=result;assert result['success'],result
                migrated=result
            assert migrated['application_check']['url']=='http://127.0.0.1:8000/'
            with build_opener(ProxyHandler({})).open(migrated['application_check']['url'],timeout=10) as response:
                report['independent_application_orm']={'status':response.status,'marker':response.read()==b'step7-database-ready'}
            assert report['independent_application_orm']=={'status':200,'marker':True}
            try:registry.review('migrate_database',{'session_id':runtime['session_id']})
            except ValueError:report['replay_refused']=True
            else:raise AssertionError('Migration replay was not refused')
            report['stop']=execute('stop_runtime',{'session_id':runtime['session_id']});assert report['stop']['success']
            report['success']=True
        except Exception as error:
            report['error']=str(error)
            import traceback
            report['failure_frames']=[]
            current=error
            while current is not None:
                report['failure_frames'].append({'type':type(current).__name__,'frames':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(current.__traceback__)]})
                current=current.__context__
            if loop:report['conversation']=loop.snapshot()
        finally:
            args.output.write_text(json.dumps(report,indent=2)+'\n')
            if runtime is None and loop:
                for item in loop.snapshot()['state'].get('observations',[]):
                    if item['tool']=='prepare_database' and item['result'].get('cleanup',{}).get('status')=='kept_running':runtime=item['result']
            if runtime and runtime.get('cleanup',{}).get('status')=='kept_running':
                owned=snapshot(repo,runtime['session_id']);project=owned['project']
                for cid in owned['containers'].values():docker('rm','-f',cid)
                for network in docker('network','ls','-q','--filter','label=com.docker.compose.project='+project).split():docker('network','rm',network)
                for image in docker('image','ls','--format','{{.Repository}}:{{.Tag}}',project+'-*').split():docker('image','rm',image)
                report['cleanup_verified']=not docker('ps','-aq','--filter','label=com.docker.compose.project='+project)
            report['unrelated_containers_preserved']=before.issubset(set(docker('ps','-q','--no-trunc').split()))
            report['success']=report['success'] and report.get('cleanup_verified',False) and report['unrelated_containers_preserved']
            if loop:loop.close()
            args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ['success','error','cleanup_verified','unrelated_containers_preserved']}))
    return 0 if report['success'] else 1
if __name__=='__main__':raise SystemExit(main())
