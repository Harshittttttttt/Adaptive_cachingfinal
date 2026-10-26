"""Unified policies; P2 retains paper-v1 region/posterior/sampling rules."""
import hashlib
import json
import random
from contextlib import contextmanager
from time import perf_counter

from src.controller.selectivity import SelectivityController
from src.query.executor import Evaluation


POLICIES={'P0':'no_cache','P1':'fixed_threshold','P2':'vectorq_paper_v1',
          'P3':'vectorq_selectivity_gate','P4':'vectorq_reverse_gate',
          'P5':'vectorq_selectivity_audit','P6':'exact_key'}


@contextmanager
def accounted_write(db,result):
    """A failed cache write must not hide an already completed inference."""
    try:
        with db:
            yield
    except Exception as exc:
        exc.attempts=result.llm_calls
        exc.records=result.details.get('requests',[])
        raise


class CachePolicy:
    def __init__(self,policy,store,encoder,oracle,config=None,seed=17):
        if policy not in POLICIES:raise ValueError('Unknown policy')
        self.policy,self.store,self.encoder,self.oracle=policy,store,encoder,oracle
        self.config=config or {}
        self.seed=seed
        self.rng=random.Random(seed)
        self.controller_rng=random.Random(seed+1)
        self.controller=SelectivityController(**{k:v for k,v in self.config.items()
                                               if k in {'tau_min','tau_max','gamma','audit_min','audit_max'}})
        self.selectivity_kind=self.config.get('selectivity_kind','global')
        if self.selectivity_kind not in {'global','stage'}:raise ValueError('Invalid selectivity kind')
        store.db.execute('''CREATE TABLE IF NOT EXISTS policy_configuration (
            run_id TEXT PRIMARY KEY REFERENCES experiment_runs(run_id), fingerprint TEXT NOT NULL)''')
        fingerprint=hashlib.sha256(json.dumps([policy,self.config,seed],sort_keys=True).encode()).hexdigest()
        prior=store.db.execute('SELECT fingerprint FROM policy_configuration WHERE run_id=?',(store.run_id,)).fetchone()
        if prior and prior['fingerprint']!=fingerprint:
            raise ValueError('Policy configuration changed; use a fresh isolated run')
        store.db.execute('INSERT OR IGNORE INTO policy_configuration VALUES (?,?)',(store.run_id,fingerprint))
        store.db.commit()

    def reset(self):
        self.store.reset()
        self.rng.seed(self.seed)
        self.controller_rng.seed(self.seed+1)

    def evaluate(self,task,row,context):
        if self.policy=='P0':return self.oracle.evaluate(task,row,context)
        started=perf_counter()
        text=task.input_text(row['review_text'])
        key=hashlib.sha256(text.encode()).hexdigest()
        tick=perf_counter()
        vector=[1.0] if self.policy=='P6' else self.encoder.embed(text)
        embedding_seconds=perf_counter()-tick
        tick=perf_counter()
        if self.policy=='P6':
            entry=self.store.exact(context.dataset_version,task,key)
            score=1.0 if entry else None
        else:
            entry,score=self.store.nearest(context.dataset_version,task,vector)
        search_seconds=perf_counter()-tick
        reason='no_neighbor'
        region=None
        audit=False
        if entry:
            if self.policy=='P6':reason='exact_match'
            elif self.policy=='P1':
                reason='fixed_match' if score>=self.config.get('fixed_threshold',.82) else 'below_fixed_threshold'
            else:
                region=entry.state.region(score)
                reason=region
                if region=='R3':
                    s=context.global_selectivity if self.selectivity_kind=='global' else context.stage_selectivity
                    forced=self.controller.force_check(region,score,s,self.policy,self.controller_rng)
                    audit=forced or entry.state.sample_check(score,self.rng,self.config.get('uncertainty_gate',1))
                    reason=('selectivity_audit' if self.policy=='P5' else 'selectivity_gate') if forced else (
                        'posterior_audit' if audit else 'posterior_reuse')
                elif region=='R2':audit=True
            direct=reason in {'exact_match','fixed_match','posterior_reuse'}
            if direct:
                return Evaluation(entry.response,'hit',reason,0,0,score,
                                  {'embedding_seconds':embedding_seconds,'search_seconds':search_seconds,
                                   'policy_seconds':perf_counter()-started-embedding_seconds-search_seconds},
                                  {'region':region,'entry_id':entry.entry_id,'mode':getattr(self.oracle,'mode','unknown')})
        result=self.oracle.evaluate(task,row,context)
        # Only validated inference reaches this transaction. Persistence errors
        # propagate; there is no fallback that pretends a response was cached.
        tick=perf_counter()
        with accounted_write(self.store.db,result):
            if entry and self.policy in {'P2','P3','P4','P5'}:
                if region=='R1':
                    entry.state.reject(score)
                    insert=True
                else:
                    correct=result.label==entry.response
                    entry.state.observe(score,correct)
                    insert=not correct
                    result.details['validation_correct']=correct
                self.store.update(entry,task)
            else:insert=True
            if insert:
                self.store.insert(context.dataset_version,task,text,result.label,vector,
                                  self.config.get('grid_size',1001),self.config.get('decay',10))
        update_seconds=perf_counter()-tick
        result.decision='audit' if audit else 'miss'
        result.reason=reason
        result.similarity=score
        result.audit_calls=result.llm_calls if audit else 0
        if audit and 'simulated_llm_calls' in result.details:
            result.details['simulated_audit_calls']=result.details['simulated_llm_calls']
        result.details.update(region=region,entry_id=entry.entry_id if entry else None)
        result.timings.update(embedding_seconds=embedding_seconds,search_seconds=search_seconds,
                              cache_update_seconds=update_seconds,
                              policy_seconds=max(0,perf_counter()-started-embedding_seconds-search_seconds
                                                 -result.timings.get('llm_seconds',0)))
        return result
