import json,os,shutil,socket,sys,tempfile
from pathlib import Path
root=Path.cwd().resolve();sys.path.insert(0,str(root))
from agent.loop import AgentLoop
from agent.tools import ToolRegistry
from tests.test_loop import Planner,action
from tests.test_django_project import FIXTURE
from tests.django_step7_smoke import docker
from tests.step8_eval import frozen_inputs
report={'success':False,'live_model':False,'scope':'Scripted planner, real Docker preflight and owned socket on port 8000','source_sha256':frozen_inputs()}
before=set(docker('ps','-q','--no-trunc').split())
with tempfile.TemporaryDirectory(prefix='step8-port-') as directory:
 base=Path(directory).resolve();repo=base/'app';shutil.copytree(FIXTURE,repo)
 os.environ.update(DEVOPS_AGENT_STATE_DIR=str(base/'state'),BUILDX_CONFIG=str(base/'buildx'))
 registry=ToolRegistry(repo);proposal=registry.execute('propose_docker',{})['result'];params={'proposal_id':proposal['id']}
 review=registry.review('apply_docker',params);registry.execute('apply_docker',params,approval=registry.approve(review['review_id']))
 original=(repo/'docker-compose.yml').read_bytes()
 with socket.socket() as owner:
  owner.bind(('127.0.0.1',8000));owner.listen()
  loop=AgentLoop(repo,Planner([action('validate_runtime',{'compose_file':'docker-compose.yml','run':True,'readiness_timeout':5})]))
  try:
   loop.start('Start this Django app');loop.answer(True);done=loop.answer(True)
   report['conversation']=done
   assert done['state']['status']=='blocked' and done['state']['model_calls']==1
   assert 'make it available' in done['state']['message']
   assert done['state']['observations'][-1]['result']['diagnosis']['type']=='port_conflict'
   with socket.create_connection(('127.0.0.1',8000),timeout=2):
    connection,_=owner.accept();connection.close()
   report['port_owner_preserved']=True
   report['compose_unchanged']=(repo/'docker-compose.yml').read_bytes()==original
   report['unrelated_containers_preserved']=before==set(docker('ps','-q','--no-trunc').split())
   report['success']=report['compose_unchanged'] and report['unrelated_containers_preserved']
  finally:loop.close()
(root/'work/v2-step8/port-owner.json').write_text(json.dumps(report,indent=2)+'\n')
print({k:report.get(k) for k in ['success','port_owner_preserved','compose_unchanged','unrelated_containers_preserved']})
