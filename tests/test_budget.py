import pytest

from src.evaluation.runner import BudgetClient
from src.llm.client import InferenceFailure, LLMClient
from src.query.plan import TASKS


def test_budget_reserves_retries_and_counts_actual_attempts(monkeypatch):
    monkeypatch.setenv('MISTRAL_API_KEY','fixture')
    requests=[]
    def transport(*args):
        requests.append(1)
        return dict(model='fixture',choices=[dict(message={'content':'YES'},finish_reason='stop')])
    client=LLMClient({'model':'fixture','max_attempts':2},transport)
    budget={'remaining':3}
    wrapper=BudgetClient(client,budget)
    wrapper.infer(TASKS['shipping'],'text')
    assert budget['remaining']==2
    wrapper.infer(TASKS['shipping'],'text')
    assert budget['remaining']==1
    with pytest.raises(RuntimeError,match='budget exhausted'):
        wrapper.infer(TASKS['shipping'],'text')
    assert len(requests)==2


def test_failed_attempts_consume_budget(monkeypatch):
    monkeypatch.setenv('MISTRAL_API_KEY','fixture')
    def transport(*args):raise TimeoutError()
    client=LLMClient({'model':'fixture','max_attempts':2,'backoff_seconds':0},transport)
    budget={'remaining':2}
    with pytest.raises(InferenceFailure):
        BudgetClient(client,budget).infer(TASKS['shipping'],'text')
    assert budget['remaining']==0


def test_budget_ledger_records_reservation_before_network(tmp_path,monkeypatch):
    import json
    monkeypatch.setenv('MISTRAL_API_KEY','fixture')
    path=tmp_path/'ledger.json'
    def transport(*args):
        assert json.loads(path.read_text())['remaining']==0
        return dict(model='fixture',choices=[dict(message={'content':'YES'},finish_reason='stop')])
    client=LLMClient({'model':'fixture','max_attempts':1},transport)
    budget={'remaining':1,'limit':1,'ledger':str(path)}
    BudgetClient(client,budget).infer(TASKS['shipping'],'text')
    assert json.loads(path.read_text())['remaining']==0


def test_concurrent_clients_share_one_persistent_budget(tmp_path,monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv('MISTRAL_API_KEY','fixture')
    path=tmp_path/'ledger.json'
    def transport(*args):return dict(model='fixture',choices=[dict(message={'content':'YES'},finish_reason='stop')])
    def job(_):
        client=LLMClient({'model':'fixture','max_attempts':1},transport)
        wrapper=BudgetClient(client,{'remaining':3,'limit':3,'ledger':str(path)})
        try:wrapper.infer(TASKS['shipping'],'text');return True
        except RuntimeError:return False
    with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(job,range(10)))
    assert sum(results)==3 and json.loads(path.read_text())['remaining']==0
