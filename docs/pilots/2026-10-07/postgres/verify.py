import json
import subprocess
import uuid
from pathlib import Path
from urllib.request import urlopen

base = Path(__file__).resolve().parent
report = json.loads((base / 'runtime-cli.json').read_text())
assert report['success'], 'Runtime validation did not pass'
project = report['project']
assert project.startswith('devops-validation-')
def command(args):
    return subprocess.check_output(args, text=True, timeout=60).strip()
ids = command(['docker', 'ps', '-q', '--filter', f'label=com.docker.compose.project={project}']).splitlines()
records = json.loads(command(['docker', 'inspect', *ids]))
app = next(r for r in records if r['Config']['Labels']['com.docker.compose.service'] == 'app')
db = next(r for r in records if r['Config']['Labels']['com.docker.compose.service'] == 'postgres')
port = app['NetworkSettings']['Ports']['3000/tcp'][0]
assert port['HostIp'] == '127.0.0.1'
url = f"http://127.0.0.1:{port['HostPort']}/"
marker = 'pilot-' + uuid.uuid4().hex
js = '''const {PrismaClient}=require('./lib/generated/prisma');
const p=new PrismaClient();
(async()=>{try {
if(process.argv[1]==='create') {await p.todo.create({data:{text:process.argv[2]}});}
else {await p.todo.deleteMany({where:{text:process.argv[2]}});}
} finally {await p.$disconnect();}})().catch(()=>process.exit(1));'''
result = {'project':project, 'url':url, 'database_healthy':db['State'].get('Health',{}).get('Status')=='healthy'}
try:
    command(['docker','exec',app['Id'],'node','-e',js,'create',marker])
    with urlopen(url, timeout=60) as response:
        page=response.read().decode()
        result.update(http_status=response.status, page_heading='Todo List' in page, database_record_rendered=marker in page)
    assert result['database_record_rendered'] and result['page_heading'] and result['database_healthy']
finally:
    command(['docker','exec',app['Id'],'node','-e',js,'delete',marker])
with urlopen(url, timeout=60) as response:
    result['deleted_record_absent'] = marker not in response.read().decode()
assert result['deleted_record_absent']
(base/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
