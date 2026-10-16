"""Live read-only scope explanation for the user's multi-application repository."""
import os,json,tempfile,hashlib,argparse,time
from agent.loop_model import NextActionModel
from pathlib import Path
from agent.loop import AgentLoop

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    choose=NextActionModel.choose;last=[0.0]
    def paced(model,context):
        time.sleep(max(0,35-(time.monotonic()-last[0])))
        try:return choose(model,context)
        finally:last[0]=time.monotonic()
    NextActionModel.choose=paced
    root=Path(__file__).resolve().parents[1]
    report={'scope':'Real model, read-only clarification at media-facility multi-app root; no mutation approvals.'}
    report['source_sha256']={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'agent').glob('*.py')}
    with tempfile.TemporaryDirectory(prefix='node-scope-') as d:
        os.environ['DEVOPS_AGENT_STATE_DIR']=d
        loop=AgentLoop(root.parent/'media-facility',emit=lambda s:print(s,flush=True))
        try:
            result=loop.start('The backend media_facility_backend is Django and media_facility_frontend is Vue. I want both together. Can this agent currently run the entire existing stack without adopting or changing my database? Explain the actual scope and how to select a single component.')
            if result.get('pending'):
                assert result['pending']['kind']=='provider';result=loop.answer(True)
            report['conversation']=result
            report['requires_manual_answer_review']=True
            report['success']=not result.get('pending') and result['state']['status']=='finished' and all(o['tool'] in {'inspect_repository','read_file','agent_feedback'} for o in result['state']['observations'])
        finally:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            with args.output.open('x') as f:json.dump(loop.redactor.clean(report),f,indent=2)
            loop.close()
    print('scope pass:',report.get('success'));return 0 if report['success'] else 1
if __name__=='__main__':raise SystemExit(main())
