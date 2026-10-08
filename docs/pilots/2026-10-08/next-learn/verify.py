import hashlib,json,subprocess
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
base=Path(__file__).resolve().parent
r=json.loads((base/'runtime.json').read_text())
assert r['success'], r.get('error',r['phase'])
project=r['project'];assert project.startswith('devops-validation-')
def command(args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=60)
 assert p.returncode==0, p.stderr
 return p.stdout.strip()
result={'success':False,'project':project}
try:
 cid=r['application_check']['container_id']
 info=json.loads(command(['docker','inspect',cid]))[0]
 assert info['Config']['Labels']['com.docker.compose.project']==project
 port=info['NetworkSettings']['Ports']['3000/tcp'][0]
 assert port['HostIp']=='127.0.0.1'
 url='http://127.0.0.1:'+port['HostPort']
 checks=[]
 for path,markers in [('/',[b'Welcome to',b'Next.js!',b'pages/index.js',b'Documentation']),('/vercel.svg',[b'<svg'])]:
  with build_opener(ProxyHandler({})).open(url+path,timeout=45) as response:
   body=response.read(2*1024*1024)
   check={'path':path,'status':response.status,'markers_present':all(m in body for m in markers),'sha256':hashlib.sha256(body).hexdigest()}
   checks.append(check)
   assert response.status==200 and check['markers_present']
 result.update(success=True,url=url,checks=checks,node_version=command(['docker','exec',cid,'node','--version']))
finally:
 command(['docker','compose','--project-directory',str(base/'app'),'-p',project,'-f',str(base/'app/docker-compose.yml'),'down','--volumes','--timeout','5'])
 command(['docker','image','rm',project+'-app:validation'])
 remaining={kind:command(args) for kind,args in {
 'containers':['docker','ps','-aq','--filter','label=com.docker.compose.project='+project],
 'networks':['docker','network','ls','-q','--filter','label=com.docker.compose.project='+project],
 'volumes':['docker','volume','ls','-q','--filter','label=com.docker.compose.project='+project]}.items()}
 result['cleanup']={'success':not any(remaining.values()),'remaining':remaining}
 (base/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
 assert result['cleanup']['success']
print(json.dumps(result,indent=2))
