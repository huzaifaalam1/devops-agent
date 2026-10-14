"""Development policy for isolated Django databases."""
import ast
from pathlib import Path
from agent.understanding import read_text

IGNORE = '''# DevOps Agent: Django development exclusions
**/__pycache__
*.pyc
.venv
venv
**/*.sqlite3
**/*.sqlite3-*
**/*.db
**/*.db-*
'''


def runtime_policy(root, project, info):
    blockers=[];database_files=[]
    def block(code,message):
        blockers.append({'code':code,'message':message,'evidence':[{'path':'.'}],
                         'next_action':message,'needs_input':True})
    env=root/'.env'
    if env.is_symlink() or (env.exists() and (not env.is_file() or env.stat().st_nlink!=1)):
        block('django_environment_file','Use a regular, unlinked .env file for runtime environment values.')
    if project['services'] not in (['SQLite'], ['PostgreSQL']):
        block('django_database_scope','Only SQLite or a newly created disposable PostgreSQL database is supported.')
    settings=[f['value'] for f in project['findings'] if f['name']=='settings_file']
    if len(settings)==1 and project['services']==['SQLite']:
        try:
            tree=ast.parse(read_text(root,settings[0]))
            assignments=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DATABASES' for t in n.targets)]
            config=assignments[0].value
            if not isinstance(config,ast.Dict) or len(config.keys)!=1 or not isinstance(config.keys[0],ast.Constant) or config.keys[0].value!='default':
                raise ValueError()
            values=config.values[0]
            names=[v for k,v in zip(values.keys,values.values) if isinstance(k,ast.Constant) and k.value=='NAME']
            if len(names)!=1:raise ValueError()
            name=names[0]
            if isinstance(name,ast.Constant) and isinstance(name.value,str):
                value=name.value
            elif isinstance(name,ast.BinOp) and isinstance(name.op,ast.Div) and isinstance(name.left,ast.Name) and name.left.id=='BASE_DIR' and isinstance(name.right,ast.Constant) and isinstance(name.right.value,str):
                value=name.right.value
            else:raise ValueError()
            if value!=':memory:':
                candidate=Path(value)
                if candidate.is_absolute() or len(candidate.parts)!=1 or candidate.suffix not in {'.sqlite3','.db'}:
                    raise ValueError()
                database_files.append(value)
        except (OSError,ValueError,SyntaxError,IndexError,AttributeError,TypeError):
            block('django_sqlite_path','Use a reviewed default SQLite :memory: database or a simple .sqlite3/.db filename (optionally BASE_DIR / filename); dynamic/shared database paths require review.')
    if project['services']==['PostgreSQL']:
        from agent.django_database import inspect_contract
        try:
            project['database_environment']=inspect_contract(root,settings)
        except ValueError as error:
            block('django_postgres_contract',str(error))
    if project['setup']=='partial':block('partial_setup','Preserve and complete the existing Docker setup before validation; partial setups are not overwritten.')
    if project['setup']=='ambiguous':block('compose_selection','Select the intended Compose file explicitly before validation.')
    project['sqlite_files']=database_files
    return blockers


def files(project, env_file=False):
    dockerfile=('''# Local Django development only; not a production deployment image.
FROM python:'''+project['python_version']+'''-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE='''+project['settings_module']+'''
COPY . .
RUN python -m pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]
''')
    compose=('''# Disposable local development. No migrations or host database mounts.
services:
  app:
    build: .
    ports:
      - "127.0.0.1:8000:8000"
''')
    compose+='    environment:\n      DJANGO_SETTINGS_MODULE: '+project['settings_module']+'\n'
    if project['services']==['PostgreSQL']:
        from agent.django_database import compose_extension
        compose=compose_extension(compose,project,env_file)
    if env_file and project['services']==['SQLite']:compose+='    env_file:\n      - .env\n'
    return {'Dockerfile':(dockerfile,'Install the declared pip requirements under the selected Python version and run the explicit Django settings module on port 8000.'),
            'docker-compose.yml':(compose,'Expose Django on loopback port 8000. Database initialization is separately reviewed; PostgreSQL uses disposable tmpfs and its data is lost when stopped.' if project['services']==['PostgreSQL'] else 'Expose Django on loopback port 8000; keep SQLite inside the disposable container. Existing .env values are passed only at runtime; no migrations are run.')}
