import pytest

from src.data.load_reviews import import_reviews
from src.database.db import connect
from src.query.executor import Evaluation, ExecutionFailure, Executor
from src.query.plan import QueryPlan, TASKS, Task


@pytest.fixture
def dataset(tmp_path):
    # Deliberately synthetic unit/integration fixtures, not benchmark data.
    (tmp_path / 'a.csv').write_text('Review,Rate\nlate broken,1\nlate fine,2\ngreat,5\n', encoding='utf-8')
    report = import_reviews(dict(path='a.csv', database='a.db', name='fixture'), tmp_path)
    with connect(tmp_path / 'a.db') as db:
        yield db, report['dataset_version']


class FakeEvaluator:
    def __init__(self):
        self.seen = []

    def evaluate(self, task, row, context):
        self.seen.append((task.predicate_id, row['review_text'], context))
        word = {'shipping': 'late', 'defect': 'broken', 'sarcasm': 'sarcasm'}[task.predicate_id]
        return Evaluation('YES' if word in row['review_text'] else 'NO')


def test_sql_pushdown_then_multiple_semantic_stages(dataset):
    db, version = dataset
    evaluator = FakeEvaluator()
    plan = QueryPlan('q', version, (('rating', '<=', 2),),
                     (TASKS['defect'], TASKS['shipping']), 'rows')
    result = Executor(db, evaluator).execute(plan)
    assert [s['remaining_rows'] for s in result.stages] == [2, 1, 1]
    assert [s['entering_rows'] for s in result.stages] == [3, 2, 1]
    assert [s['global_selectivity'] for s in result.stages] == [2/3, 1/3, 1/3]
    assert [s['stage_selectivity'] for s in result.stages] == [2/3, 1/2, 1]
    assert [x[1] for x in evaluator.seen].count('great') == 0
    assert evaluator.seen[-1][2].global_selectivity == 1/3
    assert evaluator.seen[-1][2].stage_selectivity == 1/2
    assert result.rows[0]['review_text'] == 'late broken'
    assert sum(e['llm_calls'] for e in result.events) == 3


def test_empty_candidates_never_call_evaluator(dataset):
    db, version = dataset
    evaluator = FakeEvaluator()
    result = Executor(db, evaluator).execute(QueryPlan('q', version, (('rating', '<', 0),),
                                                        (TASKS['shipping'], TASKS['defect'])))
    assert result.row_ids == [] and evaluator.seen == [] and result.events == []
    assert [s['stage_selectivity'] for s in result.stages] == [0, 0, 0]


def test_multiple_sql_clauses_and_pure_sql(dataset):
    db, version = dataset
    result = Executor(db, None).execute(QueryPlan('q', version,
                                                 (('rating', '<=', 2), ('rating', '>', 1))))
    assert len(result.row_ids) == 1
    assert [s['stage_selectivity'] for s in result.stages] == [2/3, 1/2]


def test_empty_database_version_safe_denominators(dataset):
    db, version = dataset
    db.execute('DELETE FROM reviews')
    result = Executor(db, FakeEvaluator()).execute(QueryPlan('q', version, (), (TASKS['shipping'],)))
    assert all(s['global_selectivity'] == s['stage_selectivity'] == 0 for s in result.stages)


def test_task_input_contains_output_determining_fields():
    task = TASKS['shipping']
    assert all(x in task.input_text('actual review') for x in ['actual review', 'shipping', task.instruction, 'YES|NO', 'v1'])
    assert task.input_text('a') != task.input_text('b')
    assert task.fingerprint != Task('shipping', 'Changed instruction').fingerprint
    with pytest.raises(ValueError):
        task.input_text(' ')


def test_inference_failure_never_invents_label(dataset):
    db, version = dataset
    class Broken:
        def evaluate(self, *args):
            raise TimeoutError()
    with pytest.raises(ExecutionFailure) as error:
        Executor(db, Broken()).execute(QueryPlan('q', version, (), (TASKS['shipping'],)))
    assert error.value.events[-1]['label'] is None
    assert error.value.events[-1]['decision'] == 'failed'


def test_plan_versions_and_invalid_filters(dataset):
    db, version = dataset
    with pytest.raises(ValueError, match='differs'):
        QueryPlan.from_dict({'query_id': 'q', 'dataset_version': 'stale'}, version)
    with pytest.raises(ValueError, match='prompt version'):
        QueryPlan.from_dict({'query_id': 'q', 'semantic_tasks': [{'predicate_id': 'shipping', 'prompt_version': 'v99'}]}, version)
    with pytest.raises(ValueError, match='Numeric'):
        Executor(db, None).execute(QueryPlan('q', version, (('rating', '<=', 'invalid'),)))
    with pytest.raises(ValueError, match='Unknown dataset'):
        Executor(db, None).execute(QueryPlan('q', 'stale'))


def test_repeat_deterministic_and_predicate_namespaces(dataset):
    db, version = dataset
    executor = Executor(db, FakeEvaluator())
    plan = QueryPlan('q', version, (), (TASKS['shipping'], TASKS['sarcasm']))
    first, second = executor.execute(plan), executor.execute(plan)
    assert first.row_ids == second.row_ids == []
    assert [e['predicate_id'] for e in first.events] == [e['predicate_id'] for e in second.events]
    assert set(e['predicate_id'] for e in first.events) == {'shipping', 'sarcasm'}
