"""Explicit opt-in acceptance: python -m tests.django_step5_smoke --docker --live."""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from agent.scanner import scan_repo
from agent.detector import detect_stack
from agent.loop_model import NextActionModel, PROMPT_VERSION
from agent.loop import compact
from agent.validator import validate_docker
from agent.main import validation_result

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/django_inspection/clear'


def docker(*args):
    return subprocess.check_output(['docker',*args],text=True,timeout=60).strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--docker',action='store_true');parser.add_argument('--live',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'work/v2-step5/acceptance.json');args=parser.parse_args()
    report={'scope':'Django discovery acceptance. Docker uses an explicitly authored test harness, not product Django setup support.',
            'prompt_version':PROMPT_VERSION,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'agent').glob('*.py'))}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(report,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='django-step5-') as directory:
        base=Path(directory);clear=base/'clear';shutil.copytree(FIXTURE,clear)
        ambiguous=base/'ambiguous';shutil.copytree(FIXTURE,ambiguous)
        (ambiguous/'runtime.txt').write_text('python-3.10\n')
        (ambiguous/'config/settings.py').write_text('from .production import *\nDATABASES=load_database_config()\n')
        cases={name:detect_stack(scan_repo(str(path))) for name,path in [('clear',clear),('ambiguous',ambiguous)]}
        report['frozen_cases']={name:{'inspection':analysis['project']} for name,analysis in cases.items()}
        save()
        if args.live:
            report['live']=[]
            for name,analysis in cases.items():
                model=NextActionModel()
                context={'request':'Explain the Django inspection findings and what remains uncertain. Answer only; do not change or execute anything.',
                         'read_only_request':True,'history':[], 'observations':[{'tool':'inspect_repository','result':compact('inspect_repository',analysis)}]}
                try:
                    action=model.choose(context)
                    entry={'case':name,'provider':model.provider,'model':model.model,'action':action,
                           'passed':action['tool']=='finish' and 'django' in action['reason'].lower() and (('sqlite' in action['reason'].lower() and '3.12' in action['reason']) if name=='clear' else ('python' in action['reason'].lower() and any(word in action['reason'].lower() for word in ['conflict','ambig','uncertain','dynamic'])))}
                except ValueError as error:entry={'case':name,'passed':False,'error':str(error),'diagnostic':model.last_diagnostic}
                report['live'].append(entry);save()
        if args.docker:
            if shutil.disk_usage(base).free<8*1024**3:raise RuntimeError('8 GiB free disk required.')
            before=set(docker('ps','-q','--no-trunc').split())
            os.environ['DEVOPS_AGENT_STATE_DIR']=str(base/'state')
            os.environ['BUILDX_CONFIG']=str(base/'buildx')
            (clear/'Dockerfile').write_text('FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nRUN python manage.py check\nCMD ["python","manage.py","runserver","0.0.0.0:8000","--noreload"]\n')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            (clear/'compose.yml').write_text('services:\n  app:\n    build: .\n    ports:\n      - "127.0.0.1:'+str(port)+':8000"\n')
            gate=validation_result(str(clear),compose_file='compose.yml',existing_setup=True,run=True)
            report['product_execution_gate']={'blocked':not gate['success'] and gate['phase']=='eligibility','blockers':gate.get('blockers')};save()
            retained=None
            try:
                result=validate_docker(str(clear),compose_file='compose.yml',run=True,keep_running=True,timeout=600,readiness_timeout=60)
                report['docker']={'validation':result};save()
                if result.get('cleanup',{}).get('status')=='kept_running':retained=result
                if not result['success']:return 1
                cid=result['application_check']['container_id']
                url=result['application_check']['url']
                with urllib.request.urlopen(url,timeout=10) as response:
                    report['docker']['independent_http']={'status':response.status,'marker':response.read().decode()=='django-step5-ready'}
                code="import os,json,sys;os.environ['DJANGO_SETTINGS_MODULE']='config.settings';import django;django.setup();from django.conf import settings;from django.db import connection;cursor=connection.cursor();cursor.execute('SELECT 1');print(json.dumps({'python':'.'.join(map(str,sys.version_info[:3])),'django':django.get_version(),'engine':settings.DATABASES['default']['ENGINE'],'database_probe':cursor.fetchone()[0]}))"
                actual=json.loads(docker('exec',cid,'python','-c',code));report['docker']['actual_runtime']=actual
                report['docker']['matches_inspection']=actual['python'].startswith('3.12.') and actual['django']=='5.2.8' and actual['engine']=='django.db.backends.sqlite3' and actual['database_probe']==1
                report['docker']['dependencies']=docker('exec',cid,'pip','freeze').splitlines();save()
            finally:
                if retained:
                    for record in retained['service_states'].values():docker('rm','-f',record['id'])
                    project=retained['cleanup']['project']
                    for network in docker('network','ls','-q','--filter','label=com.docker.compose.project='+project).split():docker('network','rm',network)
                    for image in docker('image','ls','--format','{{.Repository}}:{{.Tag}}',project+'-*').split():docker('image','rm',image)
                    report['docker']['cleanup_verified']=not docker('ps','-aq','--filter','label=com.docker.compose.project='+project)
                report['unrelated_containers_preserved']=before.issubset(set(docker('ps','-q','--no-trunc').split()));save()
    passed=all(item['passed'] for item in report.get('live',[]))
    if args.docker:
        checks=report.get('docker',{})
        passed=passed and report.get('product_execution_gate',{}).get('blocked',False) and checks.get('matches_inspection',False) and checks.get('independent_http',{}).get('marker',False) and checks.get('cleanup_verified',False) and report.get('unrelated_containers_preserved',False)
    report['passed']=passed;save()
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
