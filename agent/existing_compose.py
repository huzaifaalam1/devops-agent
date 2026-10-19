"""Read-only evidence for existing Compose setups, independent of generation adapters."""
import re
import ast
from pathlib import Path
import yaml
from agent.understanding import read_text
from agent.safety import Redactor


def inspect_existing(root, selected):
    root=Path(root).resolve()
    if Path(selected).name!=selected:
        raise ValueError('Select a root Compose file.')
    text=read_text(root,selected)
    try:data=yaml.safe_load(text)
    except yaml.YAMLError:raise ValueError('Compose YAML could not be parsed.') from None
    if not isinstance(data,dict) or not isinstance(data.get('services'),dict) or not data['services']:
        raise ValueError('Compose must declare services.')
    evidence={selected:text}; services=[]
    for name, service in data['services'].items():
        if not isinstance(service,dict):raise ValueError('Invalid Compose service.')
        build=service.get('build');dockerfile=None
        if build:
            context=build if isinstance(build,str) else build.get('context','.')
            filename='Dockerfile' if isinstance(build,str) else build.get('dockerfile','Dockerfile')
            path=(root/context/filename).resolve()
            if not path.is_relative_to(root):raise ValueError('Build configuration points outside this repository.')
            dockerfile=str(path.relative_to(root));evidence[dockerfile]=read_text(root,dockerfile)
        services.append({'name':name,'dockerfile':dockerfile,'image':service.get('image'),
                         'ports':service.get('ports',[]),'mounts':service.get('volumes',[])})
    # Root startup scripts are evidence only. Never source or execute them during inspection.
    for path in sorted(root.glob('*.sh'))[:12]:
        evidence[path.name]=read_text(root,path.name)
    for path in sorted(root.glob('*Dockerfile'))[:12]:
        evidence[path.name]=read_text(root,path.name)
    for path in sorted(root.glob('*/*/urls.py'))[:4]:
        evidence[str(path.relative_to(root))]=read_text(root,str(path.relative_to(root)))
    routes={}; admin_routes=[]
    for name,content in evidence.items():
        if not name.endswith('/urls.py'):continue
        try:
            tree=ast.parse(content)
            routes[name]=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='path' and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str)][:20]
            for n in ast.walk(tree):
                if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='path' and len(n.args)>1 and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str) and ast.unparse(n.args[1])=='admin.site.urls':
                    admin_routes.append('/'+n.args[0].value.strip('/')+'/login/')
        except SyntaxError:routes[name]=[]
    startup='\n'.join(evidence.values())
    readiness={}
    django_ports=set(re.findall(r'runserver\s+(?:0\.0\.0\.0|127\.0\.0\.1):([0-9]+)',startup))
    if len(set(admin_routes))==1 and len(django_ports)==1:
        port=int(next(iter(django_ports)))
        owners=[s['name'] for s in services if any((isinstance(p,dict) and str(p.get('target'))==str(port)) or (isinstance(p,str) and p.split(':')[-1].split('/')[0]==str(port)) for p in s['ports'])]
        if len(owners)==1:readiness={'service':owners[0],'container_port':port,'health_path':admin_routes[0]}
    return Redactor(root).clean({'compose_file':selected,'services':services,'evidence':evidence,
        'route_evidence':routes,'suggested_readiness':readiness,
        'required_variables':sorted(set(re.findall(r'\$\{([A-Za-z_][A-Za-z_0-9]*)',text))),
        'startup_database_effects':bool(re.search(r'\bmigrate\b|create_superuser|\bseed\b',startup)),
        'notice':'Existing configuration may start multiple processes in one container. Static evidence is not runtime verification. Isolated stack validation copies source mounts, creates fresh project-scoped volumes, and executes existing startup including migrations/seeding only after review. It does not adopt existing database data.'})


def stack_blockers(blockers):
    # Generation limitations do not invalidate an explicitly inspected Compose setup.
    template={'application_selection','unsupported_framework','package_manager','unknown_runtime','runtime','runtime_conflict','docker_runtime_conflict','startup','startup_options','startup_binding','startup_hooks','missing_lockfile','lockfile_format','lockfile_mismatch','service_dependency','environment_missing','compose_selection','partial_docker_setup'}
    return [b for b in blockers if b['code'] not in template]


def copy_mounts(config, root, destination):
    """Replace repository bind mounts with bounded private copies, never host links."""
    import shutil
    from agent.scanner import IGNORED_DIRS
    root=Path(root).resolve();destination=Path(destination)
    total=0; count=0; copied={}
    def copy(source, target):
        nonlocal total,count
        if source.is_symlink():raise ValueError('Source snapshots refuse symlinks; no external targets are copied.')
        count+=1
        if count>250000:raise ValueError('Source snapshot exceeds file limit.')
        if source.is_dir():
            target.mkdir()
            for child in sorted(source.iterdir()):
                if child.name not in IGNORED_DIRS:copy(child,target/child.name)
        elif source.is_file():
            total+=source.stat().st_size
            if total>1024**3:raise ValueError('Source snapshot exceeds 1 GiB.')
            shutil.copy2(source,target)
        else:raise ValueError('Source snapshot only supports regular files and directories.')
    for service in config['services'].values():
        for mount in service.get('volumes',[]):
            if mount.get('type')!='bind':continue
            source=Path(mount.get('source',''))
            if source.is_symlink() or not source.resolve().is_relative_to(root) or any(p.is_symlink() for p in [source,*source.parents] if p!=root and p.is_relative_to(root)):
                raise ValueError('Source mounts must stay inside the repository without symlinks.')
            source=source.resolve()
            if any(part in IGNORED_DIRS for part in source.relative_to(root).parts):
                raise ValueError('Source mounts cannot directly target excluded metadata, dependency or cache directories.')
            if source not in copied:
                target=destination/str(len(copied));copy(source,target);copied[source]=target
            mount['source']=str(copied[source])
    return {'copied_mounts':len(copied),'bytes':total,'path':str(destination)}
