"""Stop only exact containers retained in a private validation journal."""
import hashlib
import json
import os
import re
from pathlib import Path
from agent.safety import state_directory, project_lock
from agent.validator import run_command


def evidence(root, session):
    if not re.fullmatch('[a-f0-9]{32}',session):raise ValueError('Invalid runtime session ID.')
    path=state_directory(create=False)/(session+'.json')
    info=path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077 or info.st_size>16*1024**2:
        raise ValueError('Unsafe runtime journal.')
    data=json.loads(path.read_text())
    if data.get('repository')!=str(root) or data.get('action')!='run' or data.get('status')!='succeeded':
        raise ValueError('Select a successful run for this repository.')
    report=data['events'][-1];cleanup=report.get('cleanup',{})
    project=cleanup.get('project','')
    if cleanup.get('status')!='kept_running' or not re.fullmatch('devops-validation-[a-f0-9]{12}',project):
        raise ValueError('This session did not retain an agent-owned environment.')
    records=report.get('service_states',{})
    ids={name:item['id'] for name,item in records.items()}
    if not ids or any(not re.fullmatch('[a-f0-9]{64}',cid) for cid in ids.values()):
        raise ValueError('Runtime journal lacks exact container ownership evidence.')
    return {'session_id':session,'project':project,'containers':ids}


def command(root,args):
    result=run_command(['docker',*args],root,timeout=30)
    if not result['success']:raise ValueError('Docker operation failed; no successful stop is claimed.')
    return result['stdout']


def snapshot(root,session):
    record=evidence(root,session)
    endpoint=os.environ.get('DOCKER_HOST') or json.loads(command(root,['context','inspect','--format','{{json .Endpoints.docker.Host}}']))
    if not isinstance(endpoint,str) or not endpoint.startswith(('unix://','npipe://')):
        raise ValueError('Runtime control requires a local Docker engine.')
    available=set(command(root,['ps','--all','--no-trunc','--quiet','--filter','label=com.docker.compose.project='+record['project']]).split())
    states={}
    for service,cid in record['containers'].items():
        if cid not in available:
            states[service]={'id':cid,'state':'absent'};continue
        item=json.loads(command(root,['inspect',cid]))[0]
        labels=item.get('Config',{}).get('Labels') or {}
        if item.get('Id')!=cid or labels.get('com.docker.compose.project')!=record['project'] or labels.get('com.docker.compose.service')!=service:
            raise ValueError('Container ownership changed; stop refused.')
        states[service]={'id':cid,'state':'running' if item['State']['Running'] else 'stopped'}
    return {**record,'endpoint':endpoint,'states':states}


def fingerprint(root,session):
    return hashlib.sha256(json.dumps(snapshot(root,session),sort_keys=True).encode()).hexdigest()


def status(root):
    sessions=[]
    storage=state_directory(create=False)
    paths=sorted(storage.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]
    for path in paths:
        try:evidence(root,path.stem)
        except (OSError,ValueError,KeyError,TypeError,IndexError):continue
        sessions.append(snapshot(root,path.stem))
        if len(sessions)>=10:break
    return {'sessions':sessions,'notice':'Only journaled containers from this repository; this is container state, not an application health check.'}


def stop(root,session,expected):
    with project_lock(root):
        current=snapshot(root,session)
        if current!=expected:raise ValueError('Runtime changed since review; request a fresh stop review.')
        ids=[item['id'] for item in current['states'].values() if item['state']=='running']
        if ids:command(root,['stop','--time','10',*ids])
        after=snapshot(root,session)
        success=all(item['state']!='running' for item in after['states'].values())
        return {'success':success,'phase':'stop','session_id':session,
                'environment_state':'stopped' if success else 'unknown',
                'notice':'Container data, volumes, networks and images are preserved.'}
