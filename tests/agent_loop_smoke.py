"""Opt-in live provider + real Docker acceptance for the bounded agent loop."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import uuid
from urllib.request import build_opener, ProxyHandler

from agent.loop import AgentLoop
from agent.safety import Redactor
from tests.fixture_support import materialize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',choices=['minimal','unsupported'],default='minimal')
    args=parser.parse_args()
    base=args.output.resolve().parent/('run-'+uuid.uuid4().hex[:8])
    base.mkdir(parents=True)
    if shutil.disk_usage(base).free<8*1024**3:raise SystemExit('Need 8 GiB free.')
    if args.case=='minimal':
        with socket.socket() as sock:sock.bind(('127.0.0.1',3000))
    repo=materialize(args.case,base/'app')
    os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
    (base/'buildx').mkdir()
    report={'success':False,'approvals':[],'manual_interventions':[],
            'case':args.case,'scope':'Live model acceptance: fresh Next.js build/page/cleanup or unsupported-stack stop. Automated harness supplies explicit reviewed approvals.'}
    loop=AgentLoop(repo,emit=lambda message:print(message,flush=True))
    result=None
    restarted=False
    try:
        report['provider']=loop.model.provider;report['model']=loop.model.model
        report['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('agent').glob('*.py'))}
        result=loop.start('Set up this repository for local development with Docker, build it, verify HTTP readiness, and leave the successful app running so I can open its page.')
        while result.get('pending'):
            pending=result['pending']
            if pending['kind']=='action':
                assert args.case=='minimal','Unsupported repository requested a mutation'
                review=pending['review']
                if review['tool']=='apply_docker':
                    assert {c['path'] for c in review['preview']['changes']} <= {'Dockerfile','docker-compose.yml','.dockerignore'}
                    if not restarted:
                        thread=result['id'];loop.close()
                        loop=AgentLoop(repo,emit=lambda message:print(message,flush=True))
                        result=loop.resume(thread);restarted=True
                        report['restarted_before_apply']=True
                        continue
                else:
                    assert review['tool']=='validate_runtime'
                    assert not review['parameters'].get('existing_setup',False)
                    if review['parameters'].get('run'):assert review['parameters'].get('keep_running') is True
                report['approvals'].append({'kind':'action','tool':review['tool'],'parameters':review['parameters']})
            else:
                report['approvals'].append({'kind':'provider','context':pending['context']})
            result=loop.answer(True)
        report['conversation']=result
        if args.case=='unsupported':
            assert result['state']['status'] in {'blocked','finished'}
            assert not (repo/'Dockerfile').exists()
            assert all(item['tool'] not in {'apply_docker','validate_runtime'} for item in result['state']['observations'])
            report['blocked_without_mutation']=True
        else:
            assert result['state']['status']=='verified',result['state'].get('message')
            runtime=next(item['result'] for item in reversed(result['state']['observations']) if item['tool']=='validate_runtime' and item['result'].get('success'))
            assert runtime['environment_state']=='running'
            url=runtime['application_check']['url']
            with build_opener(ProxyHandler({})).open(url,timeout=30) as response:
                body=response.read(2*1024*1024)
                report['independent_http']={'status':response.status,'marker':b'devops-agent-baseline-ready' in body,'url':url,'sha256':hashlib.sha256(body).hexdigest()}
            assert report['independent_http']['status']==200 and report['independent_http']['marker']
        report['success']=True
    except Exception as error:
        report['error']=loop.redactor.text(str(error))
        report['model_diagnostic']=loop.redactor.clean(getattr(loop.model,'last_diagnostic',{}))
        if loop.thread:report['conversation']=loop.snapshot()
    finally:
        if loop.thread:
            # Discover ownership from deterministic retained validation records.
            current=loop.snapshot()
            for item in current['state'].get('observations',[]):
                runtime=item['result']
                if item['tool']!='validate_runtime' or runtime.get('cleanup',{}).get('status')!='kept_running':continue
                project=runtime['cleanup']['project'];assert project.startswith('devops-validation-')
                results=[]
                for cmd in [['docker','compose','--project-directory',str(repo),'-p',project,'-f',str(repo/'docker-compose.yml'),'down','--volumes','--timeout','5'],['docker','image','rm',project+'-app:validation']]:
                    done=subprocess.run(cmd,capture_output=True,text=True,timeout=45);results.append(done.returncode==0)
                for kind,cmd in [('containers',['docker','ps','-aq']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:
                    done=subprocess.run(cmd+['--filter','label=com.docker.compose.project='+project],capture_output=True,text=True,timeout=15)
                    results.append(done.returncode==0 and not done.stdout.strip())
                report['cleanup']={'success':all(results),'project':project}
                report['success']=report['success'] and all(results)
        loop.close()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2).replace(str(base),'<pilot>')+'\n')
    print(json.dumps({k:report.get(k) for k in ['success','error','independent_http','cleanup']},indent=2),flush=True)
    return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
