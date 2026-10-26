import json
from urllib.error import HTTPError, URLError

import pytest

from src.database.db import connect
from src.data.load_reviews import import_reviews
from src.llm.client import InferenceFailure, InvalidResponse, LLMClient, NoCacheEvaluator, validate_label
from src.llm.references import ReferenceStore, ReplayEvaluator
from src.query.executor import Executor
from src.query.plan import QueryPlan, TASKS, Task
from src.settings import load_env


def response(label='YES', model='fixture-model', finish='stop'):
    return dict(model=model, choices=[dict(message=dict(content=label), finish_reason=finish)],
                usage=dict(prompt_tokens=40, completion_tokens=1))


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv('MISTRAL_API_KEY', 'fixture-never-sent')
    return dict(provider='mistral', model='fixture-model', max_attempts=2, backoff_seconds=0,
                pricing=dict(input_per_million_usd=.1, output_per_million_usd=.1))


def test_valid_request_token_limit_and_usage(cfg):
    calls = []
    def transport(url, payload, headers, timeout):
        calls.append((url, payload, timeout))
        return response(' NO ')
    client = LLMClient(cfg, transport)
    result = client.infer(TASKS['shipping'], 'Review body')
    assert result.label == 'NO' and result.attempts == 1
    assert result.estimated_cost_usd == pytest.approx(.0000041)
    assert calls[0][1]['max_tokens'] == 4
    assert calls[0][1]['temperature'] == 0
    assert calls[0][1]['random_seed'] == 17
    assert calls[0][1]['messages'][1]['content'] == 'Review body'
    assert 'fixture-never-sent' not in json.dumps(result.requests)


@pytest.mark.parametrize('value', ['yes', 'YES.', 'Probably YES', '', None, {'label': 'YES'}])
def test_malformed_labels_rejected(value):
    with pytest.raises(InvalidResponse):
        validate_label(value)


@pytest.mark.parametrize('first', [TimeoutError(), URLError('offline'), HTTPError('fixture',429,'limit',{},None),
                                  HTTPError('fixture',503,'unavailable',{},None)])
def test_retry_transport_and_rate_limit(cfg, first):
    calls = []
    sleeps = []
    def transport(*args):
        calls.append(1)
        if len(calls) == 1:
            raise first
        return response()
    result = LLMClient(cfg, transport, sleeps.append).infer(TASKS['defect'], 'body')
    assert result.attempts == 2 and len(sleeps) == 1
    assert result.requests[0]['status'] == 'failed'
    assert result.estimated_cost_usd is None  # Failed request usage is unknown.


def test_authentication_failure_is_not_retried(cfg):
    def transport(*args):
        raise HTTPError('fixture',401,'secret must not be logged',{},None)
    with pytest.raises(InferenceFailure) as error:
        LLMClient(cfg, transport).infer(TASKS['defect'], 'body')
    assert error.value.attempts == 1
    assert 'secret' not in str(error.value)


def test_timeout_exhaustion_has_exact_attempts(cfg):
    def transport(*args):
        raise TimeoutError()
    with pytest.raises(InferenceFailure) as error:
        LLMClient(cfg, transport).infer(TASKS['defect'], 'body')
    assert error.value.attempts == 2
    assert all(r['error'] == 'transport_timeout_or_unavailable' for r in error.value.records)


@pytest.mark.parametrize('resp', [response('YES because'), response('YES', finish='length'),
                                 response(model='unconfigured-model'), {}, {'choices': []}])
def test_invalid_responses_not_silently_used(cfg, resp):
    with pytest.raises(InferenceFailure) as error:
        LLMClient(cfg, lambda *args: resp).infer(TASKS['shipping'], 'body')
    assert error.value.attempts == 1


def test_opt_in_invalid_response_retry(cfg):
    responses = iter([response('bad'), response('NO')])
    result = LLMClient(dict(cfg,retry_invalid_response=True), lambda *args: next(responses)).infer(TASKS['shipping'], 'body')
    assert result.attempts == 2
    assert result.estimated_cost_usd == pytest.approx(.0000082)


def test_missing_text_and_key_prevent_requests(cfg, monkeypatch):
    calls = []
    client = LLMClient(cfg, lambda *args: calls.append(1))
    with pytest.raises(ValueError, match='review text'):
        client.infer(TASKS['shipping'], '')
    monkeypatch.delenv('MISTRAL_API_KEY')
    with pytest.raises(ValueError, match='MISTRAL_API_KEY'):
        client.infer(TASKS['shipping'], 'body')
    assert calls == []


def test_ollama(cfg):
    recorded = []
    def transport(url, payload, headers, timeout):
        recorded.append((url,payload))
        return dict(model='fixture-model', response='YES', done=True, done_reason='stop',
                    prompt_eval_count=25, eval_count=1)
    result = LLMClient(dict(cfg,provider='ollama'), transport).infer(TASKS['shipping'], 'body')
    assert result.label == 'YES' and result.estimated_cost_usd is None
    assert recorded[0][0].endswith('/api/generate')
    assert recorded[0][1]['stream'] is False


@pytest.fixture
def database(tmp_path):
    (tmp_path/'a.csv').write_text('Review,Rate\nbody,1\nsecond,5\n',encoding='utf-8')
    report = import_reviews(dict(path='a.csv',database='a.db',name='fixture'),tmp_path)
    with connect(tmp_path/'a.db') as db:
        yield db, report['dataset_version']


def test_reference_generation_persistence_and_reuse(database,cfg):
    db, version = database
    store=ReferenceStore(db)
    calls=[]
    def transport(*args):
        calls.append(1)
        return response()
    client=LLMClient(cfg,transport)
    row=db.execute('SELECT * FROM reviews ORDER BY review_id LIMIT 1').fetchone()
    assert store.generate(version,row,TASKS['shipping'],client)=='success'
    assert store.generate(version,row,TASKS['shipping'],client)=='reused'
    assert store.get(version,row['review_id'],TASKS['shipping'],client.model_id)=='YES'
    assert calls==[1]
    assert db.execute('SELECT count(*) FROM reference_labels').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM reference_requests').fetchone()[0]==1
    assert db.execute('SELECT count(*) FROM experiment_events').fetchone()[0]==0
    assert ReferenceStore(db).get(version,row['review_id'],TASKS['shipping'],client.model_id)=='YES'


def test_failed_generation_saved_and_explicit_retry(database,cfg):
    db,version=database
    store=ReferenceStore(db)
    row=db.execute('SELECT * FROM reviews LIMIT 1').fetchone()
    broken=LLMClient(cfg,lambda *args: response('malformed'))
    assert store.generate(version,row,TASKS['shipping'],broken)=='failed'
    saved=db.execute('SELECT * FROM reference_labels').fetchone()
    assert saved['reference_label'] is None and saved['error']
    assert store.generate(version,row,TASKS['shipping'],broken)=='saved_failure'
    valid=LLMClient(cfg,lambda *args: response('NO'))
    assert store.generate(version,row,TASKS['shipping'],valid,retry_failed=True)=='success'
    assert store.get(version,row['review_id'],TASKS['shipping'],valid.model_id)=='NO'
    assert db.execute('SELECT count(*) FROM reference_requests').fetchone()[0]==2


def test_stale_labels_model_prompt_task_dataset_isolation(database,cfg):
    db,version=database
    store=ReferenceStore(db)
    row=db.execute('SELECT * FROM reviews LIMIT 1').fetchone()
    client=LLMClient(cfg,lambda *args: response())
    store.generate(version,row,TASKS['shipping'],client)
    for v,task,model in [('stale',TASKS['shipping'],client.model_id),
                         (version,TASKS['defect'],client.model_id),
                         (version,Task('shipping','Changed instruction','v2'),client.model_id),
                         (version,TASKS['shipping'],'different')]:
        with pytest.raises(LookupError):
            store.get(v,row['review_id'],task,model)
    with pytest.raises(ValueError,match='stale labels'):
        store.get(version,row['review_id'],Task('shipping','Changed instruction'),client.model_id)
    assert LLMClient(dict(cfg,temperature=.1),lambda *args: response()).model_id != client.model_id


def test_live_and_replay_query_results_match(database,cfg):
    db,version=database
    client=LLMClient(cfg,lambda *args: response())
    store=ReferenceStore(db)
    for row in db.execute('SELECT * FROM reviews').fetchall():
        store.generate(version,row,TASKS['shipping'],client)
    plan=QueryPlan('q',version,(('rating','<=',2),),(TASKS['shipping'],))
    live=Executor(db,NoCacheEvaluator(client)).execute(plan)
    offline=Executor(db,ReplayEvaluator(store,client.model_id)).execute(plan)
    assert live.row_ids==offline.row_ids and len(live.row_ids)==1
    assert sum(e['llm_calls'] for e in live.events)==1
    assert sum(e['llm_calls'] for e in offline.events)==0
    assert sum(e['details']['simulated_llm_calls'] for e in offline.events)==1


def test_env_literal_parsing_no_execution(tmp_path,monkeypatch):
    monkeypatch.delenv('FIXTURE_ENV',raising=False)
    path=tmp_path/'.env'
    path.write_text('# comment\nFIXTURE_ENV="literal$(test)`value"\n',encoding='utf-8')
    load_env(path)
    import os
    assert os.environ['FIXTURE_ENV']=='literal$(test)`value'
    path.write_text('FIXTURE_ENV=override',encoding='utf-8')
    load_env(path)
    assert os.environ['FIXTURE_ENV']=='literal$(test)`value'
