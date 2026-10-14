"""Opt-in real Django 401 -> approved public readiness route, no port changes."""
import json
import argparse
import os
import shutil
import socket
import tempfile
import time
from pathlib import Path
from agent.tools import ToolRegistry
from tests.test_django_project import FIXTURE
from tests.django_step7_smoke import docker


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--output',type=Path,default=Path('work/v2-step8/recovery.json'));args=parser.parse_args()
    output=args.output;output.parent.mkdir(parents=True,exist_ok=True)
    with socket.socket() as check:check.bind(('127.0.0.1',8000))
    before=set(docker('ps','-q','--no-trunc').split())
    report={'success':False,'approvals':[],'live_model':args.live}
    with tempfile.TemporaryDirectory(prefix='step8-recovery-') as directory:
        base=Path(directory).resolve();repo=base/'app';shutil.copytree(FIXTURE,repo)
        if shutil.disk_usage(base).free<8*1024**3:raise RuntimeError('8 GiB required before Docker execution.')
        (repo/'config/urls.py').write_text("from django.http import HttpResponse\nfrom django.urls import path\nurlpatterns=[path('',lambda request:HttpResponse('login required',status=401)),path('health',lambda request:HttpResponse('step8-ready'))]\n")
        os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
        registry=ToolRegistry(repo);loop=None
        def approved(name,params):
            print('Reviewed action:',name,flush=True)
            review=registry.review(name,params);report['approvals'].append({'tool':name,'parameters':params})
            return registry.execute(name,params,approval=registry.approve(review['review_id']))['result']
        try:
            proposal=registry.execute('propose_docker',{})['result'];approved('apply_docker',{'proposal_id':proposal['id']})
            source=approved('validate_runtime',{'compose_file':'docker-compose.yml','run':True,'readiness_timeout':5,'timeout':300})
            report['failure']=source
            assert not source['success'] and source['diagnosis']['type']=='http_authentication',source
            assert source['cleanup']['status']=='complete'
            deadline=time.monotonic()+30
            while True:
                try:
                    with socket.socket() as check:check.bind(('127.0.0.1',8000))
                    break
                except OSError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.25)
            original=(repo/'docker-compose.yml').read_bytes()
            params={'session_id':source['session_id'],'health_path':'/health'}
            plan=registry.execute('propose_runtime_repair',params)['result']
            assert plan['status']=='ready',plan
            if args.live:
                from agent.loop import AgentLoop
                loop=AgentLoop(repo,emit=lambda s:print(s,flush=True))
                state=loop.start('Runtime session '+source['session_id']+' failed with HTTP 401 at /. Cleanup completed. The public readiness route is /health. Propose a bounded runtime repair, request separate approval, verify it once, and clean up. Preserve authentication, files and port 8000.')
                while state.get('pending'):
                    pending=state['pending']
                    if pending['kind']=='action':
                        review=pending['review'];assert review['tool']=='apply_runtime_repair',review['tool']
                        assert review['parameters']=={**params,'proposal_id':plan['id']}
                        report['approvals'].append({'tool':review['tool'],'parameters':review['parameters']})
                    state=loop.answer(True)
                report['conversation']=state
                assert state['state']['status']=='verified',state['state'].get('message')
                result=next(o['result'] for o in state['state']['observations'] if o['tool']=='apply_runtime_repair')
            else:
                result=approved('apply_runtime_repair',{**params,'proposal_id':plan['id']})
            report['repair']=result
            assert result['success'] and result['attempts']==1,result
            assert result['validation']['application_check']['status_code']==200
            assert result['validation']['cleanup']['status']=='complete'
            assert (repo/'docker-compose.yml').read_bytes()==original
            blocked=registry.execute('propose_runtime_repair',params)['result']
            assert blocked['status']=='blocked' and any('already attempted' in b for b in blocked['blockers']),blocked
            report['replay_refused']=True;report['compose_unchanged']=True
            for validation in (source,result['validation']):
                # Chat compacts project metadata; recover it from this test's own
                # private validation journal for the independent cleanup check.
                project=validation.get('project')
                if project is None:
                    project=json.loads((base/'state'/(validation['session_id']+'.json')).read_text())['project']
                assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+project)
            report['cleanup_verified']=True;report['success']=True
        except Exception as error:
            report['error']=str(error)
            if loop:report['conversation']=loop.snapshot()
        finally:
            if loop:loop.close()
            report['unrelated_containers_preserved']=before.issubset(set(docker('ps','-q','--no-trunc').split()))
            report['success']=report['success'] and report['unrelated_containers_preserved']
            output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ['success','error','cleanup_verified']}))
    return 0 if report['success'] else 1
if __name__=='__main__':raise SystemExit(main())
