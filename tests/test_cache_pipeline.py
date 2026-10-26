from dataclasses import replace
import json

import pytest

from src.data.load_reviews import import_reviews
from src.database.db import connect
from src.embeddings.client import EmbeddingClient, cosine
from src.query.executor import Evaluation, ExecutionFailure, Executor, StageContext
from src.query.plan import QueryPlan, TASKS, Task
from src.vectorq.policy import CachePolicy
from src.vectorq.store import CacheStore


@pytest.fixture
def setup(tmp_path):
    (tmp_path/'a.csv').write_text('Review,Rate\none,1\ntwo,2\nthree,5\n',encoding='utf-8')
    report=import_reviews(dict(path='a.csv',database='a.db',name='fixture'),tmp_path)
    with connect(tmp_path/'a.db') as db:
        for run in ['a','b']:
            db.execute('INSERT INTO experiment_runs VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                       (run,'test','{}',report['dataset_version'],'model','cold',17))
        yield db,report['dataset_version']


class Encoder:
    model_id='fixture-embedding'
    def __init__(self,vector=None):self.calls=0;self.vector=vector or [1,0]
    def embed(self,text):self.calls+=1;return self.vector


class Oracle:
    mode='live'
    def __init__(self,label='YES'):self.label=label;self.calls=0
    def evaluate(self,*args):self.calls+=1;return Evaluation(self.label)


def parts(setup,policy='P2',config=None,run='a'):
    db,version=setup
    store=CacheStore(db,run,'model','fixture-embedding')
    encoder,oracle=Encoder(),Oracle()
    p=CachePolicy(policy,store,encoder,oracle,config)
    row=dict(db.execute('SELECT * FROM reviews LIMIT 1').fetchone())
    context=StageContext('q',version,1,3,1,1/3,1/3)
    return p,store,encoder,oracle,row,context


def test_insertion_lookup_similarity_and_persistence(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    first=p.evaluate(TASKS['shipping'],row,c)
    assert first.decision=='miss' and oracle.calls==1
    saved=CacheStore(store.db,'a','model','fixture-embedding')
    entry,score=saved.nearest(c.dataset_version,TASKS['shipping'],[1,0])
    assert entry.response=='YES' and score==1
    assert entry.state.region(1)=='R2'
    assert cosine([1,0],[0,1])==0
    assert cosine([1,0],[-1,0])==0
    assert cosine([3,0],[2,0])==1


def test_r2_audit_then_permissible_reuse(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    p.evaluate(TASKS['shipping'],row,c)
    second=p.evaluate(TASKS['shipping'],row,c)
    assert second.decision=='audit' and second.reason=='R2' and second.audit_calls==1
    # Seeded posterior rule eventually permits reuse, retaining all checks.
    subsequent=[p.evaluate(TASKS['shipping'],row,c) for _ in range(12)]
    assert any(x.decision=='hit' for x in subsequent)
    assert oracle.calls==2+sum(x.llm_calls for x in subsequent)
    assert all(x.audit_calls==x.llm_calls for x in subsequent if x.decision=='audit')


def test_selectivity_forces_actual_call_and_updates_metadata(setup):
    p,store,encoder,oracle,row,c=parts(setup,'P3')
    p.evaluate(TASKS['shipping'],row,c)
    entry,_=store.nearest(c.dataset_version,TASKS['shipping'],[1,0])
    entry.state.observe(.7,True)
    store.update(entry,TASKS['shipping'])
    encoder.vector=[.8,.6]  # cosine .8 in R3 but below threshold at s=0.
    c=replace(c,global_selectivity=0)
    result=p.evaluate(TASKS['shipping'],row,c)
    assert result.decision=='audit' and result.reason=='selectivity_gate'
    assert result.llm_calls==result.audit_calls==1 and oracle.calls==2
    updated=store.entries(c.dataset_version,TASKS['shipping'])[0]
    assert updated.state.validations==2 and .8 in updated.state.correct


def test_incorrect_r3_check_updates_regions_and_inserts_response(setup):
    p,store,encoder,oracle,row,c=parts(setup,'P3')
    p.evaluate(TASKS['shipping'],row,c)
    entry,_=store.nearest(c.dataset_version,TASKS['shipping'],[1,0])
    entry.state.observe(.7,True);store.update(entry,TASKS['shipping'])
    oracle.label='NO';encoder.vector=[.8,.6]
    result=p.evaluate(TASKS['shipping'],row,replace(c,global_selectivity=0))
    assert result.label=='NO' and result.details['validation_correct'] is False
    entries=store.entries(c.dataset_version,TASKS['shipping'])
    assert len(entries)==2 and entries[0].state.region(.8)=='R1'
    assert entries[0].state.correct==[] and entries[1].response=='NO'


@pytest.mark.parametrize('region,score',[('R1',.4),('R2',.6)])
@pytest.mark.parametrize('policy',['P2','P3','P4','P5'])
def test_controllers_do_not_bypass_rejected_or_uncertain(setup,region,score,policy):
    p,store,encoder,oracle,row,c=parts(setup,policy)
    p.evaluate(TASKS['shipping'],row,c)
    entry,_=store.nearest(c.dataset_version,TASKS['shipping'],[1,0])
    entry.state.observe(.5,False)
    entry.state.observe(.8,True)
    store.update(entry,TASKS['shipping'])
    encoder.vector=[score,(1-score**2)**.5]
    result=p.evaluate(TASKS['shipping'],row,c)
    assert result.reason==region and result.llm_calls==1
    assert result.decision==('audit' if region=='R2' else 'miss')


def test_namespaces_no_valid_neighbor_and_run_reset(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    p.evaluate(TASKS['shipping'],row,c)
    assert store.nearest(c.dataset_version,TASKS['defect'],[1,0])==(None,None)
    assert store.nearest(c.dataset_version,Task('shipping','changed','v2'),[1,0])==(None,None)
    other=CacheStore(store.db,'b','model','fixture-embedding')
    assert other.nearest(c.dataset_version,TASKS['shipping'],[1,0])==(None,None)
    different=CacheStore(store.db,'a','new-model','fixture-embedding')
    assert different.nearest(c.dataset_version,TASKS['shipping'],[1,0])==(None,None)
    for _ in range(5):p.evaluate(TASKS['shipping'],row,c)
    p.reset()
    assert store.entries(c.dataset_version,TASKS['shipping'])==[]
    result=p.evaluate(TASKS['shipping'],row,c)
    assert result.reason=='no_neighbor'


@pytest.mark.parametrize('policy',['P0','P1','P2','P3','P4','P5','P6'])
def test_unified_pipeline_matches_oracle_on_constant_fixture(setup,policy):
    p,store,encoder,oracle,row,c=parts(setup,policy)
    plan=QueryPlan('q',c.dataset_version,(('rating','<=',2),),(TASKS['shipping'],TASKS['defect']))
    result=Executor(store.db,p).execute(plan)
    assert len(result.row_ids)==2
    assert len(result.events)==4
    if policy in {'P0','P6'}:assert encoder.calls==0
    empty=Executor(store.db,p).execute(QueryPlan('empty',c.dataset_version,(('rating','<',0),),(TASKS['shipping'],)))
    assert empty.row_ids==[] and empty.events==[]


def test_corrupt_metadata_and_vector_search_failure_propagate(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    p.evaluate(TASKS['shipping'],row,c)
    store.db.execute("UPDATE cache_entries SET metadata_json='{}'")
    with pytest.raises(ValueError,match='task definition'):p.evaluate(TASKS['shipping'],row,c)
    assert oracle.calls==1
    with pytest.raises(ValueError,match='dimensions'):cosine([1,0],[1])
    with pytest.raises(ValueError,match='nonzero'):cosine([0,0],[1,0])


def test_failed_persistence_rolls_back_and_does_not_return_fake_hit(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    store.db.execute("CREATE TRIGGER deny_cache BEFORE INSERT ON cache_entries BEGIN SELECT RAISE(ABORT,'cache write failed'); END")
    with pytest.raises(Exception,match='cache write failed'):p.evaluate(TASKS['shipping'],row,c)
    assert store.entries(c.dataset_version,TASKS['shipping'])==[] and oracle.calls==1


def test_failed_cache_write_preserves_actual_call_accounting(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    store.db.execute("CREATE TRIGGER deny_cache BEFORE INSERT ON cache_entries BEGIN SELECT RAISE(ABORT,'cache write failed'); END")
    plan=QueryPlan('failed',c.dataset_version,(),(TASKS['shipping'],))
    with pytest.raises(ExecutionFailure) as error:
        Executor(store.db,p).execute(plan)
    assert error.value.events[-1]['llm_calls']==1
    assert error.value.events[-1]['label'] is None


def test_cache_decisions_reproduce_after_reset(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    first=[p.evaluate(TASKS['shipping'],row,c).decision for _ in range(20)]
    p.reset()
    assert first==[p.evaluate(TASKS['shipping'],row,c).decision for _ in range(20)]


def test_changed_policy_configuration_requires_new_run(setup):
    p,store,encoder,oracle,row,c=parts(setup)
    with pytest.raises(ValueError,match='configuration changed'):
        CachePolicy('P3',store,encoder,oracle)


def test_embedding_client_never_embeds_only_instruction(monkeypatch):
    monkeypatch.setenv('MISTRAL_API_KEY','fixture')
    calls=[]
    def transport(url,payload,*args):
        calls.append(payload)
        return {'data':[{'embedding':[3,4]}],'usage':{'prompt_tokens':10}}
    client=EmbeddingClient({'model':'fixture'},transport)
    text=TASKS['shipping'].input_text('Actual review')
    assert client.embed(text)==[.6,.8]
    assert calls[0]['input']==[text] and 'Actual review' in text
