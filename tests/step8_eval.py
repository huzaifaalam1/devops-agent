"""Freeze and run each live step-8 regression exactly once per output directory.

Established fixtures are regression evidence, not an unseen-repository benchmark.
The trusted harness supplies scoped mutation reviews; the planner is the real model.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import re
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
CASES={
    'nextjs': ('tests.agent_loop_smoke', [], 'Prompted generated Next.js, independent page marker, scoped cleanup'),
    'django': ('tests.django_step6_smoke', [], 'Prompted SQLite Django, independent page and host-data isolation, scoped cleanup'),
    'postgres': ('tests.django_step7_smoke', ['--live'], 'Prompted disposable PostgreSQL, separate migration review, ORM and page checks, scoped cleanup'),
    'recovery': ('tests.step8_recovery_smoke', ['--live'], 'Real 401 setup then prompted reviewed /health recovery, one attempt, unchanged Compose, scoped cleanup'),
    'unsupported': ('tests.agent_loop_smoke', ['--case','unsupported'], 'Unsupported-stack stop with no mutation'),
}

# Frozen new phrasings on established fixtures, not unseen-repository coverage.
REQUESTS={
    'nextjs':'Get a working local Docker environment for this app. Create its missing Docker files, build it, confirm an HTTP response, and keep the verified service running so I can use it.',
    'django':'Please containerize this Django app for local testing with the declared Python version and its existing SQLite setup. Check the unauthenticated / page and leave the app up. No migrations.',
    'postgres':'Set up a new disposable PostgreSQL environment for this Django app. Prepare the migration plan and ask for approval before applying it. Confirm ORM operations and HTTP readiness, and retain the successful environment.',
    'recovery':'Validation {session_id} failed because / requires authentication (401). Its resources were cleaned up. Please recover using the existing public /health route: show the proposal, get approval, and verify once with cleanup afterward. Preserve app authentication, repository files and port 8000.',
    'unsupported':'Please inspect this project and get it running locally with Docker if its stack is supported. If it is outside your supported workflows, tell me why and leave the repository and Docker untouched.',
}

def frozen_inputs():
    paths=list((ROOT/'agent').glob('*.py'))+list((ROOT/'tests').glob('*.py'))
    paths += [p for p in (ROOT/'tests/fixtures').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--case',choices=CASES)
    parser.add_argument('--directory',type=Path,default=ROOT/'work/v2-step8/eval-01');args=parser.parse_args()
    args.directory.mkdir(parents=True,exist_ok=True);manifest=args.directory/'manifest.json'
    if args.freeze:
        from agent.loop_model import PROMPT_VERSION
        from agent.tools import SCHEMAS
        from agent.config import settings
        config=settings()
        record={'source_sha256':frozen_inputs(),'prompt_version':PROMPT_VERSION,'tool_schemas':SCHEMAS,
            'provider':config['DEVOPS_AGENT_PROVIDER'],'model':config['DEVOPS_AGENT_MODEL'],'cases':CASES,'requests':REQUESTS,
            'limits':{'model_calls_per_request':12,'tool_actions_per_request':12,'failures_per_request':2,'repair_attempts_per_unchanged_input':1},
            'request_spacing_seconds':35,'retry_429':False,'scope':'Held-out request phrasings on established fixtures, not unseen-repository generalization. Harness-approved actions; no independent human reviewer.',
            'success_rule':'All five reports success=true, exact frozen source, no unauthorized mutation, no credential exposure; retain failures and do not selectively relabel reruns.'}
        with manifest.open('x') as stream:json.dump(record,stream,indent=2);stream.write('\n')
        return 0
    assert args.case,'Select a case or --freeze'
    assert json.loads(manifest.read_text())['source_sha256']==frozen_inputs(),'Candidate changed; freeze and rerun the full set.'
    output=args.directory/(args.case+'.json')
    with (args.directory/(args.case+'.started')).open('x') as marker:marker.write(str(time.time()))
    from agent.loop_model import NextActionModel
    original=NextActionModel.choose;last=[0.0]
    def paced(model,context):
        time.sleep(max(0,35-(time.monotonic()-last[0])))
        try:return original(model,context)
        finally:last[0]=time.monotonic()
    module,extra,_=CASES[args.case]
    from agent.loop import AgentLoop
    start=AgentLoop.start
    def request(loop,original_request,*a,**kw):
        prompt=REQUESTS[args.case]
        if args.case=='recovery':
            prompt=prompt.format(session_id=re.search(r'\b[a-f0-9]{32}\b',original_request).group())
        return start(loop,prompt,*a,**kw)
    with patch.object(NextActionModel,'choose',paced),patch.object(AgentLoop,'start',request),patch.object(sys,'argv',[module,'--output',str(output),*extra]):
        return importlib.import_module(module).main()

if __name__=='__main__':raise SystemExit(main())
