import json,os,sys,shutil,socket,subprocess,tempfile,time,signal
from pathlib import Path
from agent.tools import ToolRegistry
from tests.django_step6_smoke import docker
ROOT=Path.cwd();out=ROOT/'work/v2-step10/cancellation.json';report={'success':False,'scope':'Real SIGINT during owned Django readiness; no model calls.'}
with socket.socket() as p:p.bind(('127.0.0.1',8000))
before=set(docker('ps','-q','--no-trunc').split())
with tempfile.TemporaryDirectory(prefix='step10-cancel-') as d:
 base=Path(d).resolve();repo=base/'app';shutil.copytree(ROOT/'tests/fixtures/django_inspection/clear',repo)
 (repo/'config/urls.py').write_text("from django.http import HttpResponse\nfrom django.urls import path\nurlpatterns=[path('',lambda request:HttpResponse('not ready',status=503))]\n")
 os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
 reg=ToolRegistry(repo);proposal=reg.execute('propose_docker',{})['result'];review=reg.review('apply_docker',{'proposal_id':proposal['id']});reg.execute('apply_docker',{'proposal_id':proposal['id']},approval=reg.approve(review['review_id']))
 with (base/'stdout').open('w') as stdout,(base/'stderr').open('w') as stderr:
  process=subprocess.Popen([sys.executable,'-m','agent.main','validate',str(repo),'--run','--timeout','600','--readiness-timeout','180','--json'],stdout=stdout,stderr=stderr)
  try:
   deadline=time.monotonic()+600;owned=[]
   while time.monotonic()<deadline and process.poll() is None:
    current=set(docker('ps','-q','--no-trunc').split())-before
    for cid in current:
     record=json.loads(docker('inspect',cid))[0];labels=record['Config'].get('Labels') or {}
     if labels.get('com.docker.compose.project.working_dir')==str(repo):owned.append(cid)
    if owned:break
    time.sleep(1)
   assert owned,'No owned running container observed before deadline'
   report['owned_ids']=owned;process.send_signal(signal.SIGINT);process.wait(timeout=40)
   report['validation']=json.loads((base/'stdout').read_text());r=report['validation']
   assert not r['success'] and r['phase']=='cancelled' and r['cleanup']['status']=='complete',r
   assert not docker('ps','-aq','--filter','label=com.docker.compose.project='+r['project'])
   report['unrelated_containers_preserved']=before.issubset(set(docker('ps','-q','--no-trunc').split()))
   assert report['unrelated_containers_preserved'];report['success']=True
  except Exception as e:report['error']=str(e)
  finally:
   if process.poll() is None:process.send_signal(signal.SIGINT);process.wait(timeout=40)
   out.write_text(json.dumps(report,indent=2).replace(str(base),'<temporary-fixture>')+'\n')
print(json.dumps({'success':report['success'],'error':report.get('error')}))
