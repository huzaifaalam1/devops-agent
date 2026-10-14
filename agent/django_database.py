"""Disposable PostgreSQL contract; never adopt an existing database."""
import ast
import hashlib
import json
import secrets
from pathlib import Path

FIELDS = {'NAME': 'sandboxdb', 'USER': 'sandboxuser', 'PASSWORD': 'generated-at-runtime',
          'HOST': 'db', 'PORT': '5432'}


def inspect_contract(root, settings):
    from agent.understanding import read_text
    try:
        tree = ast.parse(read_text(root, settings[0]))
        assignments = [n.value for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'DATABASES' for t in n.targets)]
        config = assignments[0]
        if not isinstance(config, ast.Dict) or len(config.keys) != 1 or ast.literal_eval(config.keys[0]) != 'default':
            raise ValueError()
        database = config.values[0]
        entries = {ast.literal_eval(k): v for k, v in zip(database.keys, database.values)}
        if set(entries) != {'ENGINE', *FIELDS} or len(database.keys) != len(entries):
            raise ValueError()
        names = {}
        for key in FIELDS:
            node = entries[key]
            if isinstance(node, ast.Subscript) and ast.unparse(node.value) == 'os.environ':
                name = ast.literal_eval(node.slice)
            elif isinstance(node, ast.Call) and ast.unparse(node.func) in {'os.getenv', 'os.environ.get'} and 1 <= len(node.args) <= 2 and not node.keywords:
                name = ast.literal_eval(node.args[0])
            else:
                raise ValueError()
            import re
            if not isinstance(name, str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]*', name) or name in {'DJANGO_SETTINGS_MODULE', 'PATH', 'PYTHONPATH'}:
                raise ValueError()
            names[key] = name
        if len(set(names.values())) != len(FIELDS):
            raise ValueError()
        return names
    except (OSError, ValueError, TypeError, AttributeError, IndexError, SyntaxError):
        raise ValueError('Disposable PostgreSQL requires one default database with ENGINE and five distinct direct environment references for NAME, USER, PASSWORD, HOST and PORT. Existing/literal database targets are not adopted.') from None


def compose_extension(compose, project, env_file=False):
    for key, name in project['database_environment'].items():
        compose += '      ' + name + ': "' + FIELDS[key] + '"\n'
    if env_file:
        compose += '    env_file:\n      - .env\n'
    compose += '''    networks: [default, ingress]
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: sandboxdb
      POSTGRES_USER: sandboxuser
      POSTGRES_PASSWORD: generated-at-runtime
    tmpfs:
      - /var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sandboxuser -d sandboxdb"]
      interval: 2s
      timeout: 3s
      retries: 30
'''
    compose += 'networks:\n  default:\n    internal: true\n  ingress: {}\n'
    return compose


def prepare_config(config, project, redactor):
    """Called only after exact generated files and fresh-run isolation checks."""
    password = secrets.token_urlsafe(32)
    redactor.add(password)
    config['services']['db']['environment']['POSTGRES_PASSWORD'] = password
    config['services']['app']['environment'][project['database_environment']['PASSWORD']] = password
    # Planning runs before application startup: no AppConfig.ready/runserver DB
    # writes can precede the separately reviewed initialization action.
    config['services']['app']['command'] = ['python', '-c', 'import threading; threading.Event().wait()']
    return config

# Fixed code runs inside the reviewed app container, never on the host. No model
# arguments can select SQL, a database alias, migration target, or shell command.
class DatabaseOperationError(ValueError):
    pass


SCRIPT = r'''
import hashlib, json, os, sys
from pathlib import Path
from django.conf import settings
expected_ip, mode, expected_digest = sys.argv[1:]
db = settings.DATABASES
if set(db) != {'default'} or settings.DATABASE_ROUTERS:
    raise RuntimeError('Only one default database without routers is supported')
cfg = db['default']
if (cfg.get('ENGINE') != 'django.db.backends.postgresql' or cfg.get('HOST') != 'db'
    or str(cfg.get('PORT')) != '5432' or cfg.get('NAME') != 'sandboxdb'
    or cfg.get('USER') != 'sandboxuser' or cfg.get('OPTIONS')):
    raise RuntimeError('Effective database target is outside the disposable contract')
# Pin the already ownership-checked container address instead of relying on
# Docker Desktop DNS, which can stall on internal networks.
cfg['HOST'] = expected_ip
print('DEVOPS_STAGE=setup', flush=True)
import django
django.setup()
from django.db import connection, models
from django.db.migrations.executor import MigrationExecutor
# Recheck after app initialization too.
if set(settings.DATABASES) != {'default'} or settings.DATABASE_ROUTERS or connection.settings_dict['ENGINE'] != 'django.db.backends.postgresql' or connection.settings_dict['HOST'] != expected_ip or connection.settings_dict['NAME'] != 'sandboxdb' or connection.settings_dict.get('OPTIONS'):
    raise RuntimeError('Database configuration changed during setup')
print('DEVOPS_STAGE=connect', flush=True)
with connection.cursor() as cursor:
    cursor.execute('SELECT host(inet_server_addr()), current_database(), current_user')
    actual = tuple(v.decode('ascii') if isinstance(v, bytes) else v for v in cursor.fetchone())
    if actual != (expected_ip, 'sandboxdb', 'sandboxuser'):
        raise RuntimeError('Connection does not reach the owned database')
print('DEVOPS_STAGE=plan', flush=True)
executor = MigrationExecutor(connection)
executor.loader.check_consistent_history(connection)
if executor.loader.detect_conflicts():
    raise RuntimeError('Conflicting migrations require source repair')
targets = executor.loader.graph.leaf_nodes()
plan = executor.migration_plan(targets)
if any(backwards for migration, backwards in plan):
    raise RuntimeError('Reverse migrations are not supported')
items = [{'app': m.app_label, 'name': m.name, 'operations': [o.__class__.__name__ for o in m.operations]} for m, _ in plan]
source = hashlib.sha256()
for path in sorted(Path('/app').rglob('*.py')):
    source.update(str(path).encode()); source.update(path.read_bytes())
state = {'pending': items, 'applied': sorted(executor.loader.applied_migrations), 'source': source.hexdigest()}
digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
if mode == 'apply':
    if digest != expected_digest:
        raise RuntimeError('Migration plan or source changed; request a fresh review')
    # Only forward migrations from the captured graph; never makemigrations,
    # fake, reset, flush, reverse, or a model-supplied management command.
    from django.core.management import call_command
    from django.core.management.commands.migrate import Command
    print('DEVOPS_STAGE=migrate', flush=True)
    call_command(Command(), database='default', interactive=False, verbosity=0, run_syncdb=False)
    if MigrationExecutor(connection).migration_plan(targets):
        raise RuntimeError('Pending migrations remain')
    print('DEVOPS_STAGE=orm', flush=True)
    import uuid
    table = 'devops_probe_' + uuid.uuid4().hex
    class Probe(models.Model):
        value = models.CharField(max_length=64)
        class Meta:
            app_label = 'devops_probe'
            db_table = table
    with connection.schema_editor() as editor:
        editor.create_model(Probe)
    try:
        token = uuid.uuid4().hex
        row = Probe.objects.using('default').create(value=token)
        if Probe.objects.using('default').get(pk=row.pk).value != token:
            raise RuntimeError('ORM read did not match the write')
        row.delete(using='default')
        if Probe.objects.using('default').exists():
            raise RuntimeError('ORM delete failed')
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Probe)
print('DEVOPS_DATABASE_RESULT=' + json.dumps({'digest': digest, 'pending': items, 'orm_verified': mode == 'apply'}))
'''


def database_target(root, record):
    from agent.runtime_control import command
    ids = record['containers']
    if set(ids) != {'app', 'db'}:
        raise ValueError('Expected only the prepared app and database containers.')
    details = json.loads(command(root, ['inspect', ids['app'], ids['db']]))
    app, db = details
    for item in details:
        labels = item['Config'].get('Labels', {})
        service='app' if item is app else 'db'
        if item['Id']!=ids[service] or labels.get('com.docker.compose.service')!=service or labels.get('com.docker.compose.project') != record['project'] or not item['State']['Running']:
            raise ValueError('Prepared database ownership or running state changed.')
    if set(db['HostConfig'].get('Tmpfs', {})) != {'/var/lib/postgresql/data'} or db['HostConfig'].get('PortBindings') or any(m.get('Type') != 'tmpfs' or m.get('Destination') != '/var/lib/postgresql/data' for m in db.get('Mounts', [])):
        raise ValueError('Database has persistent storage or published ports; migration refused.')
    if db['State'].get('Health', {}).get('Status') != 'healthy':
        raise ValueError('Disposable PostgreSQL is not healthy.')
    network = record['project'] + '_default'
    ingress=record['project']+'_ingress'
    if set(app['NetworkSettings']['Networks']) != {network,ingress} or set(db['NetworkSettings']['Networks']) != {network}:
        raise ValueError('Database network ownership changed.')
    networks=json.loads(command(root,['network','inspect',network,ingress]))
    if len(networks)!=2 or any(n.get('Name')!=name or n.get('Labels',{}).get('com.docker.compose.project')!=record['project'] for n,name in zip(networks,[network,ingress])) or not networks[0].get('Internal') or networks[1].get('Internal'):
        raise ValueError('Database network must be private and owned by this session.')
    return db['NetworkSettings']['Networks'][network]['IPAddress']


def run_database(root, record, mode='plan', digest='none'):
    from agent.validator import run_command
    ip = database_target(root, record)
    options = ['--env', 'PGOPTIONS=-c default_transaction_read_only=on'] if mode=='plan' else []
    result = run_command(['docker', 'exec', *options, record['containers']['app'], 'python', '-c', SCRIPT, ip, mode, digest], root, timeout=120)
    if not result['success']:
        # Tracebacks can contain credentials/source. Do not expose raw output.
        import re
        categories=re.findall(r'^([A-Za-z][A-Za-z0-9_.]*(?:Error|Exception)):', result['stderr'], re.M)
        category=categories[-1] if categories else 'command failure'
        for node in ast.walk(ast.parse(SCRIPT)):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name) and node.exc.func.id=='RuntimeError' and node.exc.args and isinstance(node.exc.args[0],ast.Constant):
                message=node.exc.args[0].value
                if ('RuntimeError: '+message) in result['stderr']:
                    raise DatabaseOperationError(message) from None
        stages=[stage for stage in ['setup','connect','plan','migrate','orm'] if 'DEVOPS_STAGE='+stage in result['stdout']]
        category += ' at '+(stages[-1] if stages else 'startup')
        if result.get('timed_out'):category='Timeout '+category
        raise DatabaseOperationError(category+': Django database planning/migration failed. No success is claimed; inspect the owned container locally. No automatic retry or rollback.')
    lines = [line.removeprefix('DEVOPS_DATABASE_RESULT=') for line in result['stdout'].splitlines() if line.startswith('DEVOPS_DATABASE_RESULT=')]
    if len(lines) != 1:
        raise ValueError('Missing unambiguous database evidence.')
    return json.loads(lines[0])


def prepared_report(root, session):
    from agent.runtime_control import evidence
    from agent.safety import state_directory
    evidence(root, session)  # private, canonical and ownership-checked journal
    report = json.loads((state_directory(create=False)/(session+'.json')).read_text())['events'][-1]
    if report.get('phase') != 'database_prepared' or not report.get('database_plan'):
        raise ValueError('Select a freshly prepared disposable database session.')
    return report


def migration_preview(root, session):
    from agent.runtime_control import snapshot
    report = prepared_report(root, session)
    from agent.safety import state_directory
    if (state_directory(create=False)/(session+'.migration-started')).exists():
        raise ValueError('This session has already attempted migrations; no replay. Inspect it or prepare a new disposable session.')
    current = snapshot(root, session)
    if any(s['state'] != 'running' for s in current['states'].values()):
        raise ValueError('Prepared containers must still be running.')
    database_target(root, current)
    return {'runtime': current, 'plan': report['database_plan'],
            'effect': 'Apply these forward migrations to the disposable database, verify ORM create/read/delete, then start Django. Stopping this tmpfs database destroys its data.'}


def migrate(root, session, expected):
    from agent.runtime_control import command
    from agent.safety import Journal, authorize, project_lock, state_directory
    with project_lock(root):
        if migration_preview(root, session) != expected:
            raise ValueError('Prepared runtime changed; request a fresh migration review.')
        # Persistent once-only fence: interrupted/failed migrations are never
        # automatically replayed, including after a new conversation is opened.
        marker = state_directory() / (session + '.migration-started')
        import os
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        journal = Journal(root, 'migrate', authorize('migrate', explicit=True))
        try:
            outcome = run_database(root, expected['runtime'], 'apply', expected['plan']['digest'])
            cid = expected['runtime']['containers']['app']
            ip=database_target(root,expected['runtime'])
            startup="import sys;from django.conf import settings;settings.DATABASES['default']['HOST']=sys.argv[1];from django.core.management import execute_from_command_line;execute_from_command_line(['django','runserver','0.0.0.0:8000','--noreload'])"
            command(root, ['exec', '-d', cid, 'python', '-c', startup, ip])
            from agent.validator import service_snapshot, application_endpoint, check_application_url
            import time
            check = {'healthy': False}
            deadline = time.monotonic()+30
            while time.monotonic()<deadline:
                containers = json.loads(command(root, ['inspect', *expected['runtime']['containers'].values()]))
                records, ready = service_snapshot(containers, {'app':{},'db':{'healthcheck':{'test':['CMD','pg_isready']}}}, expected['runtime']['project'])
                if ready:
                    url = application_endpoint(records, 'app', 8000, '/')
                    check = check_application_url(url, timeout=2)
                    if check['healthy']:
                        after=json.loads(command(root,['inspect',*expected['runtime']['containers'].values()]))
                        latest,still_ready=service_snapshot(after,{'app':{},'db':{'healthcheck':{'test':['CMD','pg_isready']}}},expected['runtime']['project'])
                        if not still_ready or latest!=records:
                            raise ValueError('Runtime changed during the HTTP check.')
                        break
                time.sleep(.5)
            result = {'success': check['healthy'], 'application_check': check, 'phase': 'database_migrated', 'session_id': session,
                      'orm_verified': outcome['orm_verified'], 'environment_state': 'running',
                      'unverified': ['Business-specific data operations beyond the diagnostic ORM table'],
                      'notice': 'Forward migrations and a disposable diagnostic ORM table were verified. No application data is retained when the database stops.'}
            journal.finish('succeeded' if result['success'] else 'failed', result)
            return result
        except (Exception, KeyboardInterrupt) as error:
            journal.finish('failed', {'success': False, 'session_id': session, 'phase': 'migration',
                'error': 'Migration interrupted or failed; environment retained for inspection. No replay or rollback. Stop the owned session when finished.'})
            if isinstance(error, KeyboardInterrupt):
                raise
            message=str(error) if isinstance(error,DatabaseOperationError) else 'Database initialization or verification failed; inspect the retained environment. No automatic retry or rollback.'
            raise ValueError(message) from None
