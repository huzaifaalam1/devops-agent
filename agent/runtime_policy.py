"""Shared distinction between generated-template gates and existing runtime checks."""

def existing_setup_blockers(blockers, *, run):
    deferred_codes = {'package_manager', 'unknown_runtime', 'runtime', 'runtime_conflict', 'docker_runtime_conflict', 'startup', 'startup_options', 'startup_binding', 'startup_hooks', 'missing_lockfile', 'lockfile_format', 'lockfile_mismatch'}
    if run:
        deferred_codes |= {'service_dependency', 'environment_missing'}
    return ([b for b in blockers if b['code'] not in deferred_codes],
            [b for b in blockers if b['code'] in deferred_codes])


def runtime_options(info):
    """Static candidates only; never resolve Compose or invoke Docker here."""
    from agent.detector import detect_stack
    options = []
    for selected in sorted(info.get('compose_files', []))[:12]:
        analysis = detect_stack({**info, 'selected_compose_file': selected})
        project = analysis['project']
        blocking, deferred = existing_setup_blockers(project['blockers'], run=True)
        if project.get('services') == ['PostgreSQL']:
            blocking = [*blocking, {'code':'database_initialization', 'message':'Existing PostgreSQL setups cannot bypass the separately approved disposable database workflow.'}]
        existing = None
        if info.get('path'):
            from agent.existing_compose import inspect_existing, stack_blockers
            try:
                existing = inspect_existing(info['path'], selected)
                blocking = stack_blockers(project['blockers'])
            except (ValueError, OSError, TypeError):
                pass
        options.append({'compose_file':selected, 'status':'blocked' if blocking else 'reviewable',
                        'parameters':{'compose_file':selected,'existing_setup':True,'run':True, **({'isolated_stack':True,**existing['suggested_readiness']} if existing else {})},
                        'existing_configuration':({k:v for k,v in existing.items() if k!='evidence'} | {'startup_evidence':{k:'\n'.join(line for line in v.splitlines() if any(word in line for word in ['migrate','npm run','runserver','create_superuser','exec ']))[:1400] for k,v in existing['evidence'].items() if k.endswith('.sh')}}) if existing else None,
                        'blockers':blocking, 'deferred_template_checks':[b['code'] for b in deferred],
                        'notice':'Static eligibility for requesting reviewed validation only. Docker configuration safety, build and runtime readiness are unverified.'})
    return options
