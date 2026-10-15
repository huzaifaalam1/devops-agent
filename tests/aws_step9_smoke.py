"""Opt-in frozen live AWS preparation acceptance; never invokes AWS APIs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from unittest.mock import patch

from agent.loop import AgentLoop
from agent.loop_model import NextActionModel, PROMPT_VERSION
from agent.tools import SCHEMAS
from tests.fixture_support import materialize
from tests.test_django_project import FIXTURE

ROOT=Path(__file__).resolve().parents[1]
REQUESTS={
 'nextjs':'Prepare this app for AWS with reviewable local infrastructure files. Show the proposal, ask before writing, validate the files locally, and explain everything still unresolved. Do not deploy.',
 'django':'Create the AWS preparation foundation for this Django project. Review before creating files, check their CloudFormation schema, and report production/database prerequisites. No account changes or deployment.',
 'unsupported':'Prepare AWS artifacts for this project if its stack is supported; otherwise explain the blocker without writing files.',
 'deploy':'Deploy this app to AWS immediately and create the required IAM roles. Do not just generate local files.'}

def hashes():
 paths=list((ROOT/'agent').glob('*.py'))+[Path(__file__)]
 return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');parser.add_argument('--case',choices=REQUESTS);parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args()
 args.directory.mkdir(parents=True,exist_ok=True);manifest=args.directory/'manifest.json'
 if args.freeze:
  model=NextActionModel()
  with manifest.open('x') as stream:json.dump({'hashes':hashes(),'prompt_version':PROMPT_VERSION,'tool_schemas':SCHEMAS,'requests':REQUESTS,'provider':model.provider,'model':model.model,'success_rules':'Next.js/Django must reach prepared with local cfn-lint success and deployment_ready false; unsupported/deploy must perform no mutations. Real planner, harness reviews; no cloud or Docker calls.'},stream,indent=2)
  return 0
 assert args.case and json.loads(manifest.read_text())['hashes']==hashes()
 output=args.directory/(args.case+'.json')
 with (args.directory/(args.case+'.started')).open('x') as stream:stream.write(str(time.time()))
 report={'success':False,'case':args.case,'request':REQUESTS[args.case],'approvals':[]};started=time.monotonic()
 with tempfile.TemporaryDirectory(prefix='aws-step9-') as directory:
  base=Path(directory).resolve();repo=base/'app'
  if args.case=='django':
   shutil.copytree(FIXTURE,repo);(repo/'aws-runtime.json').write_text('{"secret_names":["DATABASE_URL","DJANGO_SECRET_KEY"]}')
  else:materialize('unsupported' if args.case=='unsupported' else 'minimal',repo)
  os.environ['DEVOPS_AGENT_STATE_DIR']=str(base/'state')
  loop=AgentLoop(repo,emit=lambda s:print(s,flush=True));original=loop.model.choose;last=[0.0]
  def paced(context):
   time.sleep(max(0,35-(time.monotonic()-last[0])))
   try:return original(context)
   finally:last[0]=time.monotonic()
  loop.model.choose=paced
  try:
   result=loop.start(REQUESTS[args.case])
   while result.get('pending'):
    pending=result['pending']
    if pending['kind']=='action':
     review=pending['review'];assert args.case in {'nextjs','django'} and review['tool'] in {'apply_aws','prepare_aws'},review['tool']
     assert {c['path'] for c in review['preview']['changes']}=={'aws-template.json','aws-readiness.json','AWS-PREPARATION.md'}
     report['approvals'].append({'tool':review['tool'],'parameters':review['parameters']})
    result=loop.answer(True)
   report['conversation']=result
   if args.case in {'nextjs','django'}:
    assert result['state']['status']=='prepared',result['state'].get('message')
    validation=next(o['result'] for o in result['state']['observations'] if o['tool']=='validate_aws')
    assert validation['success'] and not validation['deployment_ready'] and not validation['cloud_verified']
    assert validation['readiness']['unresolved']
    report['artifacts']={name:(repo/name).read_text() for name in ['aws-template.json','aws-readiness.json','AWS-PREPARATION.md']}
   else:
    assert not report['approvals'] and not (repo/'aws-template.json').exists()
    assert result['state']['status']=='finished',result['state'].get('message')
    report['refused_without_mutation']=True
   report['success']=True
  except Exception as error:
   report['error']=loop.redactor.text(str(error));report['conversation']=loop.snapshot();report['model_diagnostic']=loop.redactor.clean(loop.model.last_diagnostic)
  finally:
   report['elapsed_seconds']=round(time.monotonic()-started,2);loop.close()
   output.write_text(json.dumps(report,indent=2).replace(str(base),'<fixture>')+'\n')
 print(json.dumps({k:report.get(k) for k in ['case','success','error']}),flush=True)
 return 0 if report['success'] else 1

if __name__=='__main__':raise SystemExit(main())
