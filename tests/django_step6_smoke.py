"""Opt-in fresh generated Django setup through the live agent and real Docker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tempfile
from urllib.request import build_opener, ProxyHandler
from agent.loop import AgentLoop
from agent.loop_model import PROMPT_VERSION
from agent.runtime_control import snapshot

ROOT=Path(__file__).resolve().parents[1]


def docker(*args):return subprocess.check_output(['docker',*args],text=True,timeout=60).strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'work/v2-step6/live-docker.json');args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(args.output.parent).free<8*1024**3:raise RuntimeError('8 GiB free disk required.')
    with socket.socket() as port_check:port_check.bind(('127.0.0.1',8000))
    before=set(docker('ps','-q','--no-trunc').split())
    report={'success':False,'prompt_version':PROMPT_VERSION,'scope':'Fresh Django SQLite app; live planner, trusted test-harness reviews, generated Docker files, real build/page and scoped stop/cleanup.',
            'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'agent').glob('*.py'))},'approvals':[]}
    with tempfile.TemporaryDirectory(prefix='django-step6-') as directory:
        base=Path(directory).resolve();repo=base/'app';shutil.copytree(ROOT/'tests/fixtures/django_inspection/clear',repo)
        settings=repo/'config/settings.py'
        settings.write_text('import os\nfrom pathlib import Path\nBASE_DIR=Path(__file__).resolve().parent.parent\n'+settings.read_text().replace("'disposable-fixture-only'","os.environ['DJANGO_SECRET_KEY']").replace("':memory:'","BASE_DIR / 'db.sqlite3'"))
        (repo/'.env').write_text('DJANGO_SECRET_KEY=step6-disposable-key-only\nDJANGO_SETTINGS_MODULE=unselected.settings\n')
        with sqlite3.connect(repo/'db.sqlite3') as conn:conn.execute('CREATE TABLE host_only_marker (id INTEGER)')
        host_hash=hashlib.sha256((repo/'db.sqlite3').read_bytes()).hexdigest()
        os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
        loop=AgentLoop(repo,emit=lambda s:print(s,flush=True));runtime=None;resumed=False
        try:
            result=loop.start('Set up this Django app with Docker, build it, verify its unauthenticated root page, and keep it running. Do not run migrations. Use its declared Python version and default SQLite configuration.')
            while result.get('pending'):
                pending=result['pending']
                if pending['kind']=='action':
                    review=pending['review'];name=review['tool']
                    if name=='apply_docker':
                        assert {c['path'] for c in review['preview']['changes']}=={'Dockerfile','docker-compose.yml','.dockerignore'}
                        assert 'FROM python:3.12-slim' in next(c['content'] for c in review['preview']['changes'] if c['path']=='Dockerfile')
                        if not resumed:
                            thread=result['id'];loop.close();loop=AgentLoop(repo,emit=lambda s:print(s,flush=True));result=loop.resume(thread);resumed=True;continue
                    else:
                        assert name=='validate_runtime',name
                        assert review['parameters'].get('run') and review['parameters'].get('keep_running')
                    report['approvals'].append({'tool':name,'parameters':review['parameters']})
                result=loop.answer(True)
            report['conversation']=result
            assert result['state']['status']=='verified',result['state'].get('message')
            runtime=next(o['result'] for o in reversed(result['state']['observations']) if o['tool']=='validate_runtime' and o['result'].get('success'))
            url=runtime['application_check']['url']
            with build_opener(ProxyHandler({})).open(url,timeout=10) as response:
                report['independent_http']={'status':response.status,'marker':response.read()==b'django-step5-ready'}
            assert report['independent_http']=={'status':200,'marker':True}
            cid=runtime['application_check']['container_id']
            script="import os,json;from pathlib import Path;import django;django.setup();from django.db import connection;c=connection.cursor();c.execute(\"SELECT count(*) FROM sqlite_master WHERE name='host_only_marker'\");print(json.dumps({'host_table_absent':c.fetchone()[0]==0,'dotenv_absent':not Path('/app/.env').exists(),'runtime_secret_present':bool(os.getenv('DJANGO_SECRET_KEY')),'settings':os.getenv('DJANGO_SETTINGS_MODULE')}))"
            report['isolation']=json.loads(docker('exec',cid,'python','-c',script))
            assert report['isolation']=={'host_table_absent':True,'dotenv_absent':True,'runtime_secret_present':True,'settings':'config.settings'}
            params={'session_id':runtime['session_id']};review=loop.registry.review('stop_runtime',params)
            token=loop.registry.approve(review['review_id'])
            report['stop']=loop.registry.execute('stop_runtime',params,approval=token)['result'];assert report['stop']['success']
            report['host_database_unchanged']=host_hash==hashlib.sha256((repo/'db.sqlite3').read_bytes()).hexdigest();assert report['host_database_unchanged']
            report['resume_before_apply']=resumed;report['success']=True
        except Exception as error:
            report['error']=loop.redactor.text(str(error));report['model_diagnostic']=loop.redactor.clean(loop.model.last_diagnostic)
            if loop.thread:report['conversation']=loop.snapshot()
        finally:
            args.output.write_text(json.dumps(report,indent=2)+'\n')
            if runtime is None and loop.thread:
                for item in loop.snapshot()['state'].get('observations',[]):
                    if item['tool']=='validate_runtime' and item['result'].get('cleanup',{}).get('status')=='kept_running':runtime=item['result']
            if runtime:
                owned=snapshot(repo,runtime['session_id']);project=owned['project']
                for cid in owned['containers'].values():docker('rm','-f',cid)
                for network in docker('network','ls','-q','--filter','label=com.docker.compose.project='+project).split():docker('network','rm',network)
                for image in docker('image','ls','--format','{{.Repository}}:{{.Tag}}',project+'-*').split():docker('image','rm',image)
                report['cleanup_verified']=not docker('ps','-aq','--filter','label=com.docker.compose.project='+project)
            report['unrelated_containers_preserved']=before.issubset(set(docker('ps','-q','--no-trunc').split()))
            report['success']=report['success'] and report.get('cleanup_verified',False) and report['unrelated_containers_preserved']
            loop.close()
            args.output.write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['success'] else 1

if __name__=='__main__':raise SystemExit(main())
