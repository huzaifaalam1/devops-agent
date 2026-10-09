"""Persistent bounded LangGraph loop with external approval grants and action ledger."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langsmith import tracing_context

from agent.tools import ToolRegistry, ToolRefused, MUTATIONS, inputs
from agent.safety import Redactor, state_directory
from agent.loop_model import NextActionModel, ModelUnavailable


class State(TypedDict, total=False):
    read_only_request: bool
    history: list
    request: str
    observations: list
    action: dict
    operation: str
    seen: list
    count: int
    failures: int
    model_calls: int
    status: str
    message: str


def compact(tool, result):
    """Only bounded facts and result summaries go to the planner, never raw logs."""
    if tool in {'read_file','runtime_status'}:
        return result
    if tool=='inspect_repository':
        project=result.get('project',{})
        return {k:project.get(k) for k in ['eligibility','discovery_status','setup','findings','blockers','unknowns']}
    if tool=='propose_docker':
        return {k:result.get(k) for k in ['status','id','blockers','preserved']}
    result=dict(result)
    if isinstance(result.get('cleanup'),dict):
        result['cleanup']={k:result['cleanup'][k] for k in ['status','project','stop_command'] if k in result['cleanup']}
    return {k:result.get(k) for k in ['success','phase','error','created','updated','session_id',
                                     'application_check','environment_state','cleanup','unverified','blockers','notice'] if k in result}


class AgentLoop:
    def __init__(self, root, model=None, emit=lambda text: None):
        self.registry=ToolRegistry(root)
        self.root=self.registry.root
        self.model=model or NextActionModel()
        self.redactor=Redactor(self.root)
        self.redactor.add(getattr(self.model,'key',''))
        self.emit=emit
        storage=state_directory()
        if storage.is_relative_to(self.root):
            raise ValueError('Session storage must be outside the repository.')
        self.path=storage/'conversations.sqlite'
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(fd)
        os.close(fd)
        if info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)&0o077:
            raise ValueError('Session database must be private and owned by this user.')
        self.conn=sqlite3.connect(str(self.path),check_same_thread=False)
        self.conn.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, root TEXT, identity TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, session TEXT, status TEXT, result TEXT)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS model_requests (id TEXT PRIMARY KEY, session TEXT)')
        self.conn.commit()
        self.checkpoint_conn=sqlite3.connect(str(self.path),check_same_thread=False,timeout=30)
        self.saver=SqliteSaver(self.checkpoint_conn,serde=JsonPlusSerializer(pickle_fallback=False,allowed_json_modules=[],allowed_msgpack_modules=[]))
        graph=StateGraph(State)
        for name,fn in [('observe',self._observe),('decide',self._decide),('review',self._review),('execute',self._execute)]:
            graph.add_node(name,fn)
        graph.add_edge(START,'observe')
        graph.add_conditional_edges('observe',lambda s: END if s['status']!='active' else 'decide')
        graph.add_conditional_edges('decide',lambda s: 'decide' if s['status']=='retry' else (END if s['status']!='active' else ('review' if s['action']['tool'] in MUTATIONS else 'execute')))
        graph.add_conditional_edges('review',lambda s: END if s['status']!='active' else 'execute')
        graph.add_conditional_edges('execute',lambda s: END if s['status']!='active' else 'decide')
        self.graph=graph.compile(checkpointer=self.saver)
        self.thread=None
        self.pending=None
        self.grant=None
        self.provider_allowed=False

    def close(self):
        self.checkpoint_conn.close()
        self.conn.close()

    def _clean(self,value):
        return self.redactor.clean(value)

    def _stop(self,message,status='blocked'):
        return {'status':status,'message':self._clean(message)}

    def _signature(self, tool, parameters, result=None):
        # Read-only actions depend on their bounded evidence, not every file in
        # the Docker build context. Mutations still require the full fingerprint.
        if tool in MUTATIONS:
            evidence=self.registry.action_fingerprint(tool, parameters)
        else:
            evidence=result if result is not None else self.registry.execute(tool,parameters)["result"]
        return hashlib.sha256(json.dumps([tool,parameters,evidence],sort_keys=True).encode()).hexdigest()

    def _observe(self,state):
        self.emit('Inspecting repository evidence...')
        try:
            result=self.registry.execute('inspect_repository',{})['result']
            signature=self._signature('inspect_repository',{},result)
            seen=list(state.get('seen',[]))
            if signature not in seen:seen.append(signature)
            return {'observations':[{'tool':'inspect_repository','result':self._clean(compact('inspect_repository',result))}],
                    'count':1,'status':'active','seen':seen}
        except (OSError,ValueError):
            return self._stop('Cannot inspect the selected repository. No execution performed.')

    def _decide(self,state):
        calls=self.conn.execute('SELECT count(*) FROM model_requests WHERE session=?',(self.thread,)).fetchone()[0]
        if state['count']>=12 or calls>=12 or state['failures']>=2:
            return self._stop('Action/request or failed-action limit reached. Review the evidence before a new request.')
        context=self._clean({'request':state['request'],'history':state.get('history',[]),'read_only_request':state.get('read_only_request',False),'observations':state['observations'][-6:],
                            'remaining_actions':12-state['count']})
        if len(json.dumps(context))>24000:
            return self._stop('Evidence exceeds the bounded model context; select a smaller application or use the CLI.')
        if not self.provider_allowed:
            self.pending={'kind':'provider','provider':getattr(self.model,'provider','test'),
                          'model':getattr(self.model,'model','test'), 'context':context,
                          'notice':'Authorize up to 12 bounded model calls for this request using sanitized request, repository facts and tool-result summaries. No keys or raw logs are sent.'}
            interrupt(self.pending)
            if not self.provider_allowed:
                return self._stop('Model request declined. No further actions performed.','cancelled')
        self.conn.execute('INSERT INTO model_requests VALUES (?,?)',(uuid.uuid4().hex,self.thread))
        self.conn.commit()
        self.emit('Selecting the next action...')
        try:
            action=self.model.choose(context)
            if set(action)!={'tool','parameters','reason'} or not isinstance(action['reason'],str) or len(action['reason'])>2000:
                raise ValueError()
            if action['tool']=='finish':
                if action['parameters'] != {}: raise ValueError()
                return {**self._stop(action['reason'],'finished'),
                        'model_calls':calls+1}
            inputs(action['tool'],action['parameters'])
            if action!=self._clean(action):
                return self._stop('Model action contains sensitive values; no execution performed.')
            if state.get('read_only_request') and action['tool'] in MUTATIONS:
                return self._stop('This request asked for advice, so I have not changed or run anything. Ask me to make the changes or start the app if that is what you want.')
            if action['tool'] in {'patch_file','apply_docker'} and state['count']+3>12:
                return self._stop('Not enough actions remain to edit and verify the updated evidence. Start a fresh request.')
            signature=self._signature(action['tool'],action['parameters'])
            if signature in state['seen']:
                return {'status':'retry','model_calls':calls+1,'failures':state['failures']+1,
                        'observations':state['observations']+[{'tool':'agent_feedback','result':{'message':'This action already has current evidence in the observations. Do not repeat it. Use those findings to choose a different necessary action, or finish with your answer if the task is complete.'}}]}
            self.emit('Next: '+action['tool']+' — '+action['reason'])
            return {'action':action,'operation':uuid.uuid4().hex,'seen':state['seen']+[signature],
                    'model_calls':calls+1,'status':'active'}
        except ToolRefused as error:
            return {**self._stop('Action refused: '+str(error)+' Read-only inspection remains available with /inspect. For setup, use a clean application copy without installed dependencies or build output; preserve required configuration.'), 'model_calls':calls+1}
        except ModelUnavailable as error:
            return {**self._stop(str(error)), 'model_calls':calls+1}
        except (OSError,ValueError,TypeError):
            return {**self._stop('Model selection unavailable or invalid. No action executed; use the CLI or start a new request after correcting provider/configuration issues.'),
                    'model_calls':calls+1}

    def _review(self,state):
        try:
            if not self.pending or self.pending.get('operation')!=state['operation']:
                review=self.registry.review(state['action']['tool'],state['action']['parameters'])
                self.pending={'kind':'action','operation':state['operation'],'review':review}
        except ValueError as error:
            return self._stop('Proposed change was refused before execution: '+str(error))
        except OSError:
            return self._stop('Action review could not read its inputs. No change was applied.')
        # File previews remain ephemeral; checkpoints carry only the action ID.
        interrupt({'kind':'action','tool':state['action']['tool'],'operation':state['operation']})
        if not self.grant:
            return self._stop('Action declined or approval unavailable. No mutation performed.','cancelled')
        return {'status':'active'}

    def _execute(self,state):
        action=state['action'];operation=state['operation']
        existing=self.conn.execute('SELECT status,result FROM operations WHERE id=? AND session=?',(operation,self.thread)).fetchone()
        if existing:
            if existing[0]=='complete':
                return json.loads(existing[1])
            return self._stop('Interrupted action has an uncertain outcome. Inspect history and owned Docker resources before any retry; it was not replayed.','reconcile')
        if action['tool'] in MUTATIONS and not self.grant:
            return self._stop('Restart invalidated execution approval. No action replayed; start a fresh reviewed request.','reconcile')
        self.conn.execute('INSERT INTO operations VALUES (?,?,?,?)',(operation,self.thread,'started',None))
        self.conn.commit()
        self.emit('Executing '+action['tool']+'...')
        grant,self.grant=self.grant,None
        try:
            result=self.registry.execute(action['tool'],action['parameters'],approval=grant)['result']
            summary=self._clean(compact(action['tool'],result))
            failed=result.get('success') is False or result.get('status')=='blocked'
            update={'observations':state['observations']+[{'tool':action['tool'],'result':summary}],
                    'count':state['count']+1,'failures':state['failures']+int(failed),'status':'active'}
            if action['tool'] in {'patch_file','apply_docker'} and not failed:
                # Old blockers and file text must not remain in the next planning
                # context after an edit. Verification is part of this ledger entry.
                try:
                    fresh=self.registry.execute('inspect_repository',{})['result']
                    observations=[item for item in state['observations'] if item['tool'] not in {'inspect_repository','read_file'}]
                    observations.extend([{'tool':action['tool'],'result':summary},
                        {'tool':'inspect_repository','result':self._clean(compact('inspect_repository',fresh))}])
                    update.update(observations=observations,count=state['count']+2)
                    seen=list(state['seen'])
                    seen.append(self._signature('inspect_repository',{},fresh))
                    if action['tool']=='patch_file':
                        params={'path':action['parameters']['path']}
                        current=self.registry.execute('read_file',params)['result']
                        observations.append({'tool':'read_file','result':self._clean(current)})
                        update['count']+=1
                        seen.append(self._signature('read_file',params,current))
                    update['seen']=seen
                    self.emit('Change applied. Refreshed repository findings'+(' and file contents.' if action['tool']=='patch_file' else '.'))
                except (OSError,ValueError,TypeError):
                    update.update(self._stop('Change applied, but refreshing the evidence failed. Inspect the file before continuing; the edit will not be replayed.'))
            if action['tool']=='stop_runtime' and result.get('success'):
                update.update(status='finished',message='The agent-owned containers are stopped. Volumes and data were preserved.')
            if action['tool']=='validate_runtime' and result.get('phase')=='eligibility':
                blockers=result.get('blockers',result.get('project',{}).get('blockers',[]))
                details=' '.join(item.get('message','')+' '+item.get('next_action','') for item in blockers)
                update.update(self._stop('Runtime validation did not start. '+(details or result.get('error','Eligibility checks failed.'))))
            if action['tool']=='validate_runtime' and action['parameters'].get('run') and result.get('success'):
                update.update(status='verified',message='Runtime readiness verified. Environment: '+result.get('environment_state','unknown')+'. See retained validation evidence and cleanup status.')
            if result.get('phase')=='cancelled':
                update.update(status='cancelled',message='Execution cancelled; inspect the recorded cleanup result.')
        except KeyboardInterrupt:
            update=self._stop('Interrupted during execution. Check action history and owned resources; no automatic retry.','reconcile')
        except (OSError,ValueError,TypeError):
            update=self._stop('Tool failed or refused the action. Inspect action history before retrying; no automatic replay.')
        self.conn.execute('UPDATE operations SET status=?,result=? WHERE id=?',('complete',json.dumps(self._clean(update)),operation))
        self.conn.commit()
        return update

    def _config(self):
        return {'configurable':{'thread_id':self.thread},'recursion_limit':60}

    @contextlib.contextmanager
    def _locked(self):
        # All checkpoint read/modify/resume operations share this process lock.
        lock=self.path.parent/(self.thread+'.conversation.lock')
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(fd)
            if info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)&0o077:
                raise ValueError('Unsafe conversation lock.')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def _invoke_unlocked(self,value):
        with tracing_context(enabled=False):
            self.graph.invoke(value,self._config(),durability='sync')
        return self.snapshot()

    def _invoke(self,value):
        with self._locked():
            return self._invoke_unlocked(value)

    def start(self,request,history=None):
        if not isinstance(request,str) or not request.strip() or len(request)>4000:
            raise ValueError('Provide a request between 1 and 4000 characters.')
        self.thread=uuid.uuid4().hex
        self.pending=self.grant=None
        self.provider_allowed=False
        self.conn.execute('INSERT INTO sessions VALUES (?,?,?)',(self.thread,str(self.root),json.dumps(self.registry.identity)))
        self.conn.commit()
        return self._invoke({'request':self._clean(request),'read_only_request':bool(re.match(r'^\s*(can (?:i|we|this)|how (?:do|can|would) (?:i|we)|is (?:this|it)|does (?:this|it)|would (?:this|it))\b',request,re.I)),'history':self._clean((history or [])[-6:]),'observations':[],'seen':[],'count':0,
                             'failures':0,'model_calls':0,'status':'active','message':''})

    def resume(self,thread):
        if not isinstance(thread,str) or not re.fullmatch('[0-9a-f]{32}',thread):
            raise ValueError('Invalid conversation ID.')
        row=self.conn.execute('SELECT root,identity FROM sessions WHERE id=?',(thread,)).fetchone()
        if row!=(str(self.root),json.dumps(self.registry.identity)):
            raise ValueError('Conversation does not belong to this repository identity.')
        self.thread=thread
        self.pending=self.grant=None
        self.provider_allowed=False
        with self._locked():
            state=self.graph.get_state(self._config())
            if not state.next:
                result=self.snapshot()
                result['resume_notice']='Recorded outcome only; current service health has not been rechecked.'
                return result
            if state.next == ('decide',):
                fresh=self._observe(state.values)
                fresh['count']=state.values.get('count',0)+1
                self.graph.update_state(self._config(),fresh,as_node='observe')
            # Never supply an old approval response on resume. Interrupts execute
            # again and present a fresh review; completed ledger operations reconcile.
            return self._invoke_unlocked(None)

    def answer(self,approved):
        with self._locked():
            if type(approved) is not bool or not self.pending or not self.graph.get_state(self._config()).interrupts:
                raise ValueError('No pending review or invalid approval response.')
            kind=self.pending['kind']
            if approved:
                if kind=='provider':
                    self.provider_allowed=True
                else:
                    self.grant=self.registry.approve(self.pending['review']['review_id'])
            result=self._invoke_unlocked(Command(resume=approved))
            return result

    def snapshot(self):
        snapshot=self.graph.get_state(self._config())
        return {'id':self.thread,'state':dict(snapshot.values),
                'pending':self._clean(self.pending) if snapshot.interrupts else None}
