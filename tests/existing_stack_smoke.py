"""Opt-in real existing-stack pilot; copy tracked working files, preserve original data."""
import argparse,hashlib,json,os,shutil,subprocess,tempfile,time
from pathlib import Path
from unittest.mock import patch
from agent.loop import AgentLoop
from agent.loop_model import NextActionModel
from agent.runtime_control import snapshot
from agent.safety import Redactor
from tests.step8_eval import frozen_inputs

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'media-facility'

def docker(*args):
    return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.STDOUT).strip()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    assert not args.output.exists()
    if shutil.disk_usage(ROOT).free<8*1024**3:raise SystemExit('Need 8 GiB free.')
    source_files=subprocess.check_output(['git','ls-files','-z'],cwd=SOURCE).decode().split('\0')
    source_files=[p for p in source_files if p and (SOURCE/p).is_file() and not (SOURCE/p).is_symlink() and not Path(p).name.startswith('.env')]
    hashes={p:hashlib.sha256((SOURCE/p).read_bytes()).hexdigest() for p in source_files}
    before=set(docker('ps','-q','--no-trunc').split());report={'success':False,'source_hashes':hashes,'candidate':frozen_inputs(),'live_model':args.live}
    redactor=Redactor(ROOT);registry=None;runtime=None
    with tempfile.TemporaryDirectory(prefix='existing-stack-pilot-') as d:
        base=Path(d).resolve();repo=base/'repo';repo.mkdir()
        for name in source_files:
            target=repo/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(SOURCE/name,target)
        os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
        loop=AgentLoop(repo,emit=lambda text:print(text,flush=True));registry=loop.registry
        choose=NextActionModel.choose;last=[0.0]
        def paced(model,context):
            time.sleep(max(0,35-(time.monotonic()-last[0])))
            try:return choose(model,context)
            finally:last[0]=time.monotonic()
        try:
            if args.live:
                with patch.object(NextActionModel,'choose',paced):
                    result=loop.start('Can you run this repo locally and leave it running?')
                    while result.get('pending'):
                        pending=result['pending']
                        if pending['kind']=='action':
                            review=pending['review'];assert review['tool']=='validate_runtime'
                            params=review['parameters'];assert params.get('isolated_stack') and params.get('keep_running')
                            assert params.get('compose_file')=='docker-compose.local.yml'
                        result=loop.answer(True)
                    report['conversation']=result
                    runtime=next((o['result'] for o in result['state']['observations'] if o['tool']=='validate_runtime'),None)
                    assert result['state']['status']=='verified',result['state'].get('message')
            else:
                params={'compose_file':'docker-compose.local.yml','existing_setup':True,'isolated_stack':True,'run':True,'keep_running':True,'service':'app','container_port':8000,'health_path':'/api/admin/login/','timeout':600,'readiness_timeout':180}
                review=registry.review('validate_runtime',params)
                runtime=registry.execute('validate_runtime',params,approval=registry.approve(review['review_id']))['result']
            report['runtime']=runtime
            assert runtime and runtime['success'],runtime.get('error') if runtime else 'No runtime execution'
            checks=runtime['application_checks'];assert {c['container_port'] for c in checks}=={3000,8000} and all(c['healthy'] for c in checks)
            owned=snapshot(repo,runtime['session_id']);cid=owned['containers']['app']
            # Separate process-backed check: both endpoints belong to this exact app container.
            report['both_endpoints_same_container']=all(owned['containers'][c['service']]==cid for c in checks)
            assert report['both_endpoints_same_container']
            report['migration_state']=docker('exec',cid,'python','/app/backend/manage.py','migrate','--check','--settings=media_facility_backend.settings','--configuration=LocalDocker')
            assert all(hashlib.sha256((SOURCE/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
            report['original_source_preserved']=True
            params={'session_id':runtime['session_id']};review=registry.review('stop_runtime',params)
            report['stop']=registry.execute('stop_runtime',params,approval=registry.approve(review['review_id']))['result']
            assert report['stop']['success'];report['success']=True
        except Exception as error:
            report['error']=redactor.text(str(error))
            report['runtime']=runtime
            if loop.thread:report['conversation']=loop.snapshot()
        finally:
            if runtime and runtime.get('cleanup',{}).get('status')=='kept_running':
                project=runtime['cleanup']['project']
                for cid in docker('ps','-aq','--filter','label=com.docker.compose.project='+project).split():docker('rm','-f',cid)
                for kind in ['network','volume']:
                    for resource in docker(kind,'ls','-q','--filter','label=com.docker.compose.project='+project).split():docker(kind,'rm',resource)
                for image in docker('image','ls','--format','{{.Repository}}:{{.Tag}}',project+'-*').split():docker('image','rm',image)
                report['cleanup_verified']=not docker('ps','-aq','--filter','label=com.docker.compose.project='+project)
            report['unrelated_preserved']=before.issubset(set(docker('ps','-q','--no-trunc').split()))
            report['candidate_unchanged']=report['candidate']==frozen_inputs()
            report['success']=report['success'] and report.get('cleanup_verified',False) and report['unrelated_preserved'] and report['candidate_unchanged']
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(redactor.clean(report),indent=2).replace(str(base),'<pilot>'))
            loop.close()
    print(json.dumps({k:report.get(k) for k in ['success','error','cleanup_verified']}));return 0 if report['success'] else 1
if __name__=='__main__':raise SystemExit(main())
