"""One runner for all seven policies, isolated cold/warm caches and modes."""
from dataclasses import asdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
from time import perf_counter
import uuid
import threading

from src.embeddings.client import EmbeddingClient
from src.llm.client import LLMClient, NoCacheEvaluator
from src.llm.references import ReferenceStore, ReplayEvaluator
from src.query.executor import ExecutionFailure, Executor
from src.query.plan import QueryPlan,tasks_for
from src.vectorq.algorithm import ALGORITHM_VERSION
from src.vectorq.policy import CachePolicy, POLICIES
from src.vectorq.store import CacheStore
from src.evaluation.metrics import summarize

_BUDGET_LOCKS={}
_BUDGET_LOCKS_GUARD=threading.Lock()


class PreparedEncoder:
    def __init__(self,db,version,model_id):
        self.model_id=model_id
        self.vectors={r['request_key']:json.loads(r['vector_json']) for r in db.execute(
            'SELECT * FROM prepared_embeddings WHERE dataset_version=? AND model_id=?',(version,model_id))}

    def embed(self,text):
        key=hashlib.sha256(text.encode()).hexdigest()
        if key not in self.vectors:raise LookupError('Missing prepared embedding; run prepare_embeddings')
        return self.vectors[key]


class BudgetClient:
    """Reserve worst-case retries before every live request; never exceed cap."""
    def __init__(self,client,budget):
        self.client,self.budget=client,budget
        self.model_id=client.model_id
        key=budget.get('ledger','memory-'+str(id(budget)))
        with _BUDGET_LOCKS_GUARD:
            self._lock=_BUDGET_LOCKS.setdefault(key,threading.Lock())

    def _sync(self):
        if self.budget.get('ledger') and Path(self.budget['ledger']).exists():
            current=json.loads(Path(self.budget['ledger']).read_text())
            if current.get('limit')!=self.budget.get('limit'):raise ValueError('Live budget changed')
            self.budget.update(current)

    def _persist(self):
        if self.budget.get('ledger'):
            path=Path(self.budget['ledger']);path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(self.budget,indent=2)+'\n',encoding='utf-8')

    def infer(self,*args):
        with self._lock:
            self._sync()
            if self.budget['remaining']<self.client.max_attempts:
                raise RuntimeError('Live request-attempt budget exhausted')
            self.budget['remaining']-=self.client.max_attempts
            self._persist()  # Reserve before transmission, including uncertain failures.
        try:
            result=self.client.infer(*args)
        except Exception as exc:
            attempts=getattr(exc,'attempts',self.client.max_attempts)
            with self._lock:
                self._sync()
                self.budget['remaining']+=self.client.max_attempts-attempts
                self._persist()
            raise
        with self._lock:
            self._sync()
            self.budget['remaining']+=self.client.max_attempts-result.attempts
            self._persist()
        return result


def run(config,db,mode='offline',states=('cold','warm'),policies=None,order='fixed',repeat=0):
    if mode not in {'offline','live'}:raise ValueError('Unknown benchmark mode')
    if not set(states)<={'cold','warm'}:raise ValueError('Invalid cache state')
    exp=config['experiment']
    manifest=json.loads(Path(exp.get('manifest',exp.get('pilot_manifest'))).read_text(encoding='utf-8'))
    version=manifest['dataset_version']
    rows=db.execute('SELECT review_id FROM reviews WHERE dataset_version=? ORDER BY review_id',(version,)).fetchall()
    if [r['review_id'] for r in rows]!=manifest['review_ids'] or len(rows)!=manifest.get('row_count',10):
        raise ValueError('Database records differ from the explicit cohort manifest')
    if manifest.get('text_group_hashes'):
        from src.evaluation.cohorts import text_key
        actual=[text_key(r[0]) for r in db.execute('SELECT review_text FROM reviews WHERE dataset_version=? ORDER BY review_id',(version,))]
        if actual!=manifest['text_group_hashes']:raise ValueError('Cohort review text changed after selection')
    if len({p['query_id'] for p in config['workload']})!=len(config['workload']):
        raise ValueError('Workload query IDs must be unique')
    client=LLMClient(config['llm'])
    store=ReferenceStore(db)
    replay=ReplayEvaluator(store,client.model_id)
    plans=[QueryPlan.from_dict(spec,version,tasks_for(config)) for spec in config['workload']]
    seed=exp.get('seed',17)+repeat
    if order=='reverse':plans.reverse()
    elif order=='shuffled':random.Random(seed).shuffle(plans)
    elif order!='fixed':raise ValueError('Unknown workload order')
    # Preflight every task/review reference before executing any measured calls.
    for row in rows:
        for task in {t.predicate_id:t for p in plans for t in p.semantic_tasks}.values():
            store.get(version,row['review_id'],task,client.model_id)
    expected={p.query_id:Executor(db,replay).execute(p) for p in plans}
    baseline=sum(len(r.events) for r in expected.values())
    budget={'remaining':exp.get('max_live_request_attempts',500)}
    if mode=='live' and exp.get('budget_ledger'):
        ledger=Path(exp['budget_ledger'])
        budget.update(ledger=str(ledger),limit=budget['remaining'])
        # Each request synchronizes under the shared ledger lock. Reading here
        # would race another condition's atomic budget reservation.
    oracle=NoCacheEvaluator(BudgetClient(client,budget)) if mode=='live' else replay
    model=EmbeddingClient(config['embedding']).model_id
    encoder=PreparedEncoder(db,version,model)
    output_dir=Path(config['logging']['directory']);output_dir.mkdir(parents=True,exist_ok=True)
    summaries=[]
    for state in states:
        selected=list(policies or POLICIES)
        if 'P0' in selected:selected=['P0']+[p for p in selected if p!='P0']
        state_baseline=baseline
        baseline_definition='no-cache reference pipeline, one call per candidate; retries excluded'
        for policy in selected:
            if policy not in POLICIES:raise ValueError('Unknown policy')
            run_id=f'{mode}-{policy}-{state}-{order}-{repeat}-{uuid.uuid4().hex[:12]}'
            saved=dict(config=deepcopy(config),mode=mode,state=state,order=order,repeat=repeat,
                       algorithm_version=ALGORITHM_VERSION,embedding_mode='precomputed',
                       cohort_manifest=manifest,
                       sqlite_settings={'journal_mode':db.execute('PRAGMA journal_mode').fetchone()[0],
                                        'synchronous':db.execute('PRAGMA synchronous').fetchone()[0]})
            db.execute('''INSERT INTO experiment_runs
                (run_id,policy_name,configuration,dataset_version,model_version,cache_state,random_seed)
                VALUES (?,?,?,?,?,?,?)''',(run_id,POLICIES[policy],json.dumps(saved,sort_keys=True),version,
                                           client.model_id,state,seed))
            db.commit()
            cache=CacheStore(db,run_id,client.model_id,model)
            evaluator=CachePolicy(policy,cache,encoder,oracle,config['policies'],seed)
            # A distinct run's empty cache is warmed through the intended order.
            passes=('warmup','measure') if state=='warm' else ('measure',)
            measured_events=[];outputs=[];warmup_events=[]
            with (output_dir/(run_id+'.jsonl')).open('w',encoding='utf-8') as file:
                def log(value):
                    file.write(json.dumps(value,sort_keys=True)+'\n');file.flush()
                log(dict(kind='run',run_id=run_id,policy=policy,**saved))
                for pass_kind in passes:
                    for plan in plans:
                        try:
                            result=Executor(db,evaluator).execute(plan)
                        except ExecutionFailure as exc:
                            for event in exc.events:
                                log(dict(kind='event',run_id=run_id,policy=policy,mode=mode,
                                         pass_kind=pass_kind,**event))
                            log(dict(kind='failure',run_id=run_id,query_id=plan.query_id,
                                     reason=str(exc),status='incomplete'))
                            raise
                        for event in result.events:
                            task=next(t for t in plan.semantic_tasks if t.predicate_id==event['predicate_id'])
                            event.update(run_id=run_id,policy=policy,cache_state=state,mode=mode,group=plan.group,
                                         pass_kind=pass_kind,
                                         reference_label=store.get(version,event['review_id'],task,client.model_id))
                            event['correct']=event['label']==event['reference_label']
                            log(dict(kind='event',**event))
                            db.execute('''INSERT INTO experiment_events
                                (run_id,query_id,review_id,predicate_id,stage,similarity,global_selectivity,
                                stage_selectivity,policy_decision,decision_reason,llm_calls,audit_calls,correct,timings_json,details_json)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                (run_id,event['query_id'],event['review_id'],event['predicate_id'],event['stage'],
                                 event['similarity'],event['global_selectivity'],event['stage_selectivity'],
                                 event['decision'],event['reason'],event['llm_calls'],event['audit_calls'],
                                 int(event['correct']),json.dumps(event['timings']),json.dumps(event)))
                            (measured_events if pass_kind=='measure' else warmup_events).append(event)
                        actual=set(result.row_ids);reference=set(expected[plan.query_id].row_ids)
                        output=dict(query_id=plan.query_id,row_ids=result.row_ids,
                                    row_set_agreement=actual==reference,incorrectly_included=sorted(actual-reference),
                                    incorrectly_excluded=sorted(reference-actual),stages=result.stages,
                                    elapsed_seconds=result.elapsed_seconds,pass_kind=pass_kind,group=plan.group)
                        log(dict(kind='query',**output))
                        if pass_kind=='measure':outputs.append(output)
                        db.commit()
                if policy=='P0' and mode=='live':
                    state_baseline=sum(e['llm_calls'] for e in measured_events)
                    baseline_definition='observed no-cache request attempts in the same live cache-state workload, including retries'
                summary=dict(run_id=run_id,policy=policy,mode=mode,cache_state=state,order=order,repeat=repeat,
                             seed=seed,algorithm_version=ALGORITHM_VERSION,cohort_rows=len(rows),
                             cohort_split=manifest.get('split','pilot'),dataset_version=version,
                             embedding_mode='precomputed',baseline_definition=baseline_definition,
                             warmup_actual_calls=sum(e['llm_calls'] for e in warmup_events),
                             warmup_simulated_calls=sum(e['details'].get('simulated_llm_calls',0) for e in warmup_events),
                             **summarize(measured_events,outputs,state_baseline,mode))
                log(dict(kind='summary',**summary))
            summaries.append(summary)
    filename=f'summary-{mode}-{order}-{repeat}-'+uuid.uuid4().hex[:8]+'.json'
    (output_dir/filename).write_text(json.dumps(summaries,indent=2)+'\n',encoding='utf-8')
    return summaries
