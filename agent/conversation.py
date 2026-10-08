"""Interactive driver: human responses stay outside model tool dispatch."""
import json
from agent.loop import AgentLoop
from agent.session import Session

HELP = ('Ask for a local task. /inspect is local-only; /status shows the last request; '
        '/resume ID reopens a conversation; /repo PATH switches repositories; '
        '/cancel stops the current request; /exit exits. At approval: yes, no, or pause.')


def run_chat(path, read, emit, resume=None):
    local=Session(emit)
    loop=None
    result=None

    def show(value):
        local.say(json.dumps(value,indent=2) if isinstance(value,dict) else value)

    def drive(current):
        nonlocal result
        result=current
        show('Conversation: '+result['id'])
        if result.get('resume_notice'):show(result['resume_notice'])
        while result.get('pending'):
            show(result['pending'])
            answer=read('Approve this review? [yes/no/pause]').strip().lower()
            if answer in {'pause','/pause','/exit','exit'}:
                show('Paused. Resume with /resume '+result['id']+'. Approval is not retained across restart.')
                return
            if answer in {'no','n','/cancel','cancel','stop'}:
                result=loop.answer(False)
            elif answer in {'yes','y'}:
                result=loop.answer(True)
            else:
                show('Enter yes, no, or pause. No approval was issued.')
        show(result['state'].get('message') or result['state']['status'])
        for item in result['state'].get('observations',[]):
            if item['tool'] in {'apply_docker','validate_runtime'}:
                show(item)

    try:
        emit('DevOps Agent — bounded LangGraph session. Model requests and mutations require review.')
        emit(HELP)
        if path is not None: local.select(path)
        while local.repo is None:
            value=read('Application directory (or /exit)')
            if value.strip() in {'/exit','exit'}:return
            local.select(value)
        loop=AgentLoop(local.repo,emit=local.say)
        if resume:drive(loop.resume(resume))
        while True:
            text=read('You').strip()
            if not text:continue
            if text.lower() in {'/exit','exit','quit'}:break
            try:
                if text=='/help':show(HELP)
                elif text=='/inspect':local.inspect()
                elif text=='/status':show(result or 'No conversation started.')
                elif text.startswith('/resume '):drive(loop.resume(text[8:].strip()))
                elif text.startswith('/repo '):
                    if result and result.get('pending'):
                        show('Pause is retained under its conversation ID; changing repositories does not execute it.')
                    if local.select(text[6:].strip()):
                        loop.close();loop=AgentLoop(local.repo,emit=local.say);result=None
                elif text in {'/cancel','cancel','stop'}:
                    if result and result.get('pending'):drive(loop.answer(False))
                    else:show('No action is currently executing. Existing retained services are not stopped by cancelling a request.')
                elif text.startswith('/'):
                    show('Unknown command. '+HELP)
                else:drive(loop.start(text))
            except (OSError,ValueError) as error:
                # Avoid raw provider/OS exceptions potentially containing secrets.
                show('Request could not continue safely. Use /status, inspect local configuration, or start a fresh reviewed request. No automatic retry.')
    except (EOFError,KeyboardInterrupt):
        show('Session interrupted. Use the conversation ID to resume; uncertain mutations are never automatically replayed.')
    except (OSError,ValueError):
        show('Cannot open the session. Check provider settings and private state-directory permissions. Existing CLI commands remain available.')
    finally:
        if loop:
            if loop.thread:show('Conversation ID: '+loop.thread)
            loop.close()
        show('Session ended. Inspect recorded environment/cleanup status; successfully retained services may still be running.')
