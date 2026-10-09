"""Bounded Django discovery. Never imports project code or authorizes execution."""
import ast
import re
from pathlib import Path
from packaging.requirements import Requirement, InvalidRequirement
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version
from agent.understanding import read_text

# Version compatibility only, not an assertion of lifecycle/security support.
# https://docs.djangoproject.com/en/6.0/faq/install/
PYTHON_MINORS = {(4,2):range(8,13),(5,0):range(10,13),(5,1):range(10,14),
                 (5,2):range(10,15),(6,0):range(12,15)}
BACKENDS={'django.db.backends.sqlite3':'SQLite','django.db.backends.postgresql':'PostgreSQL',
          'django.db.backends.postgresql_psycopg2':'PostgreSQL','django.db.backends.mysql':'MySQL',
          'django.db.backends.oracle':'Oracle'}


def inspect_django_project(info):
    root=Path(info['path']).resolve();findings=[];issues=[];unknowns=[];requirements={};inspected=set()
    candidates=[str(Path(c['path']).relative_to(root)) for c in info.get('components',[])]
    def fact(name,value,path,line=None,certainty='confirmed'):
        source={'path':path}
        if line is not None:source['line']=line
        findings.append({'name':name,'value':value,'certainty':certainty,'evidence':[source]})
    def block(code,message,path='.',needs_input=True):
        issues.append({'code':code,'message':message,'evidence':[{'path':path}],
                       'next_action':message,'needs_input':needs_input})
    def read(name):
        inspected.add(name)
        try:
            target=root/name
            if not target.is_file() or target.is_symlink() or any(p.is_symlink() for p in target.parents if p!=root and p.is_relative_to(root)):
                raise ValueError()
            return read_text(root,name)
        except (OSError,ValueError,RuntimeError):
            block('django_metadata','Make this metadata a readable, bounded file inside the app.',name)
            return None
    visited=set();active=set();total=0;django_declared=False
    def pip_file(name,depth=0):
        nonlocal total, django_declared
        if depth>8 or len(visited)>=32:
            block('requirements_limit','Requirements exceed the 32-file / 8-level inspection bound.',name);return
        if name in active:
            block('requirements_cycle','Resolve the requirements include cycle.',name);return
        if name in visited:return
        visited.add(name);active.add(name)
        text=read(name)
        if text is None:active.remove(name);return
        total+=len(text.encode())
        if total>2*1024*1024:
            block('requirements_limit','Requirements exceed the combined 2 MiB inspection bound.',name);active.remove(name);return
        for line_no,line in enumerate(text.splitlines(),1):
            line=line.split(' #',1)[0].strip()
            if not line or line.startswith('#'):continue
            include=re.fullmatch(r'(?:-r\s*|--requirement(?:=|\s+))([^\s]+)',line)
            if include:
                relative=Path(name).parent/include[1]
                if relative.is_absolute() or '..' in relative.parts or ':' in str(relative):
                    block('requirements_include','Requirements includes must stay inside the selected app.',name);continue
                pip_file(str(relative),depth+1);continue
            if line.startswith('-') or '\\' in line:
                block('dependency_format','Review unsupported pip options, constraints, editable or multiline declarations.',name);continue
            try:req=Requirement(line)
            except InvalidRequirement:
                block('dependency_format','Use inspectable public PEP 508 dependency declarations.',name);continue
            key=re.sub('[-_.]+','-',req.name).lower()
            if key=='django':django_declared=True
            if req.url or req.marker:
                block('dependency_format','URL/VCS/local dependencies and conditional markers need explicit review.',name);continue
            key=re.sub('[-_.]+','-',req.name).lower()
            specs=list(req.specifier)
            if len(specs)!=1 or specs[0].operator!='==' or not re.fullmatch(r'\d+(?:\.\d+){1,2}',specs[0].version):
                block('dependency_pin','Pin a stable explicit version for each dependency in this bounded workflow.',name);continue
            version=specs[0].version
            if key in requirements and requirements[key][0]!=version:
                block('dependency_conflict','Resolve conflicting versions for '+key+'.',name);continue
            requirements[key]=(version,name,line_no)
        active.remove(name)
    if (root/'requirements.txt').exists():pip_file('requirements.txt')
    if 'manage.py' not in info['found_files'] and not django_declared:return None
    fact('framework','Django','manage.py' if 'manage.py' in info['found_files'] else 'requirements.txt',certainty='inferred')
    if candidates:block('application_selection','Select one standalone app: '+', '.join(candidates))
    if (root/'package.json').exists():block('mixed_stack','Select the Django component separately from the JavaScript application.','package.json')
    if not (root/'requirements.txt').exists():block('requirements_missing','Provide the app\'s pip requirements.txt.','requirements.txt')
    for marker in ('poetry.lock','uv.lock','Pipfile','Pipfile.lock'):
        if (root/marker).exists():block('dependency_manager','This checkpoint supports pip requirements, not '+marker+'.',marker)
    django=requirements.get('django')
    if not django:block('django_requirement','Declare an explicit stable Django pin in the inspected requirements.','requirements.txt')
    else:fact('django_version',django[0],django[1],django[2])
    fact('dependency_manifest','pip requirements.txt','requirements.txt')
    fact('dependency_count',len(requirements),'requirements.txt')

    versions=[];python_spec=None
    for filename,prefix in (('.python-version',''),('runtime.txt','python-')):
        if not (root/filename).exists():continue
        value=read(filename)
        if value is None:continue
        value=value.strip()
        if prefix and value.startswith(prefix):value=value[len(prefix):]
        if not re.fullmatch(r'3\.\d{1,2}(?:\.\d{1,3})?',value):
            block('python_version','Declare one numeric Python 3 version.',filename);continue
        versions.append(value);fact('python_requirement',value,filename)
    if (root/'pyproject.toml').exists():
        value=read('pyproject.toml')
        try:
            try:import tomllib
            except ImportError:import tomli as tomllib
            metadata=tomllib.loads(value) if value is not None else {}
            for manager in ('poetry','uv'):
                if manager in metadata.get('tool',{}):block('dependency_manager','Review '+manager+' configuration; only pip requirements are supported.','pyproject.toml')
            if metadata.get('project',{}).get('dependencies') or metadata.get('project',{}).get('optional-dependencies'):
                block('dependency_manifests','Reconcile pyproject dependency declarations with the selected pip requirements.','pyproject.toml')
            declared=metadata.get('project',{}).get('requires-python')
            if declared is not None:
                python_spec=SpecifierSet(declared);fact('python_constraint',str(python_spec),'pyproject.toml')
        except (ValueError,TypeError,AttributeError,InvalidSpecifier):block('python_metadata','Repair requires-python / TOML metadata.','pyproject.toml')
    selected=None
    if not versions:block('python_selection','Declare the intended Python version in .python-version or runtime.txt.','.python-version')
    elif len({tuple(v.split('.')[:2]) for v in versions})!=1 or len({v for v in versions if len(v.split('.'))==3})>1:
        block('python_conflict','Resolve conflicting Python version declarations.')
    else:
        selected=max(versions,key=lambda v:len(v.split('.')))
        if python_spec is not None and Version(selected) not in python_spec:
            block('python_conflict','Selected Python does not satisfy requires-python.','pyproject.toml')
        if django:
            dv=Version(django[0]);minor=int(selected.split('.')[1]);series=dv.release[:2]
            supported=minor in PYTHON_MINORS.get(series,())
            if series==(4,2) and minor==12 and dv<Version('4.2.8'):supported=False
            if series==(5,1) and minor==13 and dv<Version('5.1.3'):supported=False
            if series==(5,2) and minor==14 and dv<Version('5.2.8'):supported=False
            if not supported:block('python_django_compatibility','Python/Django combination is outside the documented compatibility matrix.','.python-version')
            else:fact('python_django_compatibility','Version combination is documented; dependency installability is unverified.','.python-version')

    modules=set();tree=None
    source=read('manage.py') if 'manage.py' in info['found_files'] else None
    if source is None:block('manage_missing','Select the application directory containing manage.py.','manage.py')
    else:
        try:tree=ast.parse(source)
        except (SyntaxError,ValueError,RecursionError):block('manage_syntax','Repair manage.py syntax.','manage.py')
    if tree:
        for node in ast.walk(tree):
            if isinstance(node,(ast.If,ast.IfExp)) and 'DJANGO_SETTINGS_MODULE' in ast.unparse(node) and '__name__' not in ast.unparse(node.test):
                block('settings_conditional','Review conditional settings-module selection.','manage.py')
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and ast.unparse(node.func)=='os.environ.setdefault' and len(node.args)==2:
                a,b=node.args
                if isinstance(a,ast.Constant) and a.value=='DJANGO_SETTINGS_MODULE':
                    if isinstance(b,ast.Constant) and isinstance(b.value,str) and re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',b.value):
                        modules.add(b.value);fact('settings_module_candidate',b.value,'manage.py',node.lineno,'inferred')
                    else:block('settings_dynamic','Select an explicit settings module; computed defaults are unresolved.','manage.py')
            if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                if any('DJANGO_SETTINGS_MODULE' in ast.unparse(t) for t in targets):
                    block('settings_override','Review settings-module assignment/override in manage.py.','manage.py')
    module=next(iter(modules)) if len(modules)==1 else None
    services=[]
    if module is None:block('settings_selection','Identify one unambiguous settings module.','manage.py')
    else:
        base=Path(*module.split('.'));paths=[str(base.with_suffix('.py')),str(base/'__init__.py')]
        paths=[p for p in paths if (root/p).exists()]
        if len(paths)!=1:block('settings_source','Settings module must resolve to one local source file.',str(base))
        else:
            filename=paths[0];text=read(filename);settings=None
            if text is not None:
                try:settings=ast.parse(text)
                except (SyntaxError,ValueError,RecursionError):block('settings_syntax','Repair settings source syntax.',filename)
            if settings:
                fact('settings_file',filename,filename)
                assignments=[n for n in settings.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DATABASES' for t in n.targets)]
                all_assignments=[n for n in ast.walk(settings) if isinstance(n,(ast.Assign,ast.AnnAssign,ast.AugAssign)) and any('DATABASES' in ast.unparse(t) for t in (n.targets if isinstance(n,ast.Assign) else [n.target]))]
                if len(assignments)!=1 or len(all_assignments)!=1 or not isinstance(assignments[0].value,ast.Dict):
                    block('database_dynamic','Review computed, conditional, missing or multiple DATABASES assignments.',filename)
                else:
                    databases=assignments[0].value
                    for alias,config in zip(databases.keys,databases.values):
                        if not isinstance(alias,ast.Constant) or not isinstance(alias.value,str) or not isinstance(config,ast.Dict):
                            block('database_dynamic','Review dynamic database aliases/configuration.',filename);continue
                        if any(k is None for k in config.keys):
                            block('database_dynamic','Review unpacked database configuration.',filename)
                        engines=[v for k,v in zip(config.keys,config.values) if isinstance(k,ast.Constant) and k.value=='ENGINE']
                        if len(engines)!=1 or not isinstance(engines[0],ast.Constant) or not isinstance(engines[0].value,str) or engines[0].value not in BACKENDS:
                            block('database_dynamic','Review a dynamic or custom database engine.',filename);continue
                        backend=BACKENDS[engines[0].value];services.append(backend)
                        fact('database_backend',backend,filename,engines[0].lineno,'inferred')
                        if backend not in {'SQLite','PostgreSQL'}:block('database_backend','Only SQLite and disposable PostgreSQL are in the v2 workflow.',filename)
                    if not databases.keys:block('database_missing','Declare the intended database configuration.',filename)
                for node in ast.walk(settings):
                    if isinstance(node,ast.ImportFrom) and (node.level or not (node.module or '').startswith(('django.','pathlib','os','typing'))):
                        block('settings_import','Imported settings require review; imports are never executed.',filename)
                    if isinstance(node,ast.Call):
                        function=ast.unparse(node.func)
                        if 'DATABASES' in function or function in {'exec','eval','globals','locals'}:
                            block('settings_dynamic','Dynamic settings mutation requires review.',filename)
                        if function in {'os.getenv','os.environ.get','os.environ.setdefault','env','config'} and node.args:
                            value=node.args[0]
                            if isinstance(value,ast.Constant) and isinstance(value.value,str) and re.fullmatch('[A-Z_][A-Z0-9_]*',value.value):
                                fact('environment_variable_reference',value.value,filename,node.lineno,'inferred')
                    if isinstance(node,ast.Subscript) and ast.unparse(node.value)=='os.environ' and isinstance(node.slice,ast.Constant) and isinstance(node.slice.value,str) and re.fullmatch('[A-Z_][A-Z0-9_]*',node.slice.value):
                        fact('environment_variable_reference',node.slice.value,filename,node.lineno,'inferred')
    discovery='understood' if not issues else 'needs_input'
    blockers=list(issues)
    unknowns.extend(['Static settings evidence does not prove effective runtime configuration; environment overrides and arbitrary Python effects are not executed.',
                     'Dependency installability, migrations, service connectivity and application health are unverified.',
                     'Compatibility is version compatibility only, not a security or lifecycle certification.'])
    result={'framework':'Django','eligibility':'blocked','discovery_status':discovery,'findings':findings,'blockers':blockers,
            'assumptions':[],'unknowns':unknowns,'application_candidates':candidates,
            'setup':('ambiguous' if (len(info['dockerfiles'])>1 or len(info['compose_files'])>1) and not info.get('selected_compose_file') else 'existing' if info['dockerfiles'] and info['compose_files'] else 'partial' if info['dockerfiles'] or info['compose_files'] else 'none'),'startup_command':'python manage.py runserver 0.0.0.0:8000 --noreload',
            'startup_candidate':'python manage.py runserver','python_version':selected,'settings_module':module,
            'services':sorted(set(services)),'scope':'Reviewed local Django/pip development with disposable SQLite; no migrations or production support.',
            'inspected_files':sorted(inspected)}
    from agent.django_runtime import runtime_policy
    result['blockers'].extend(runtime_policy(root,result,info))
    result['eligibility']='eligible' if not result['blockers'] else 'blocked'
    return result
