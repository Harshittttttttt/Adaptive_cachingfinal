"""Sequential AND pipeline. Policies see selectivity of preceding stages."""
from dataclasses import asdict, dataclass, field
from time import perf_counter

from src.database.db import filter_reviews


def ratio(after, before):
    return after / before if before else 0.0


@dataclass(frozen=True)
class StageContext:
    query_id: str
    dataset_version: str
    stage: int
    total_rows: int
    entering_rows: int
    global_selectivity: float
    stage_selectivity: float


@dataclass
class Evaluation:
    label: str
    decision: str = 'miss'
    reason: str = 'no_cache'
    llm_calls: int = 1
    audit_calls: int = 0
    similarity: float | None = None
    timings: dict = field(default_factory=dict)
    details: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.label not in {'YES', 'NO'}:
            raise ValueError('Evaluator must return a validated YES or NO')


class ExecutionFailure(RuntimeError):
    def __init__(self, message, stages, events):
        super().__init__(message)
        self.stages = stages
        self.events = events


@dataclass
class QueryResult:
    query_id: str
    row_ids: list[str]
    rows: list[dict]
    stages: list[dict]
    events: list[dict]
    elapsed_seconds: float


class Executor:
    def __init__(self, db, evaluator):
        self.db = db
        self.evaluator = evaluator

    def execute(self, plan):
        started = perf_counter()
        known = self.db.execute('SELECT 1 FROM dataset_versions WHERE dataset_version=?',
                                (plan.dataset_version,)).fetchone()
        if not known:
            raise ValueError('Unknown dataset version')
        total = self.db.execute('SELECT count(*) FROM reviews WHERE dataset_version=?',
                                (plan.dataset_version,)).fetchone()[0]
        stages, events = [], []
        cumulative, rows, before = [], [], total

        def stage_record(kind, name, n_before, n_after, seconds):
            return dict(stage=len(stages), kind=kind, name=name, total_rows=total,
                        entering_rows=n_before, remaining_rows=n_after,
                        global_selectivity=ratio(n_after, total),
                        stage_selectivity=ratio(n_after, n_before), elapsed_seconds=seconds)

        # Each SQL clause is pushed down and measured, including an explicit
        # scan stage for plans with no structured filter.
        for sql_filter in (plan.sql_filters or (None,)):
            stage_start = perf_counter()
            if sql_filter is not None:
                cumulative.append(sql_filter)
            rows = [dict(row) for row in filter_reviews(self.db, plan.dataset_version, cumulative)]
            stages.append(stage_record('sql', str(sql_filter or 'all'), before,
                                       len(rows), perf_counter() - stage_start))
            before = len(rows)
        for task in plan.semantic_tasks:
            stage_start = perf_counter()
            entering = len(rows)
            context = StageContext(plan.query_id, plan.dataset_version, len(stages), total,
                                   entering, ratio(entering, total), stages[-1]['stage_selectivity'])
            survivors = []
            for row in rows:
                base = dict(query_id=plan.query_id, dataset_version=plan.dataset_version,
                            review_id=row['review_id'], predicate_id=task.predicate_id,
                            prompt_version=task.prompt_version, stage=context.stage,
                            global_selectivity=context.global_selectivity,
                            stage_selectivity=context.stage_selectivity)
                candidate_start = perf_counter()
                try:
                    task.input_text(row['review_text'])  # Validate before any inference.
                    result = self.evaluator.evaluate(task, row, context)
                    if not isinstance(result, Evaluation):
                        raise ValueError('Evaluator returned an invalid result type')
                except Exception as exc:
                    # Failure remains a failure. No NO label or partial answer is returned.
                    base.update(decision='failed', reason=type(exc).__name__, label=None,
                                llm_calls=getattr(exc, 'attempts', 0),
                                details={'requests': getattr(exc, 'records', [])},
                                elapsed_seconds=perf_counter() - candidate_start)
                    events.append(base)
                    raise ExecutionFailure(f'Inference failed for {task.predicate_id}', stages, events) from exc
                base.update(asdict(result), elapsed_seconds=perf_counter() - candidate_start)
                events.append(base)
                if result.label == 'YES':
                    survivors.append(row)
            rows = survivors
            stages.append(stage_record('semantic', task.predicate_id, entering, len(rows),
                                       perf_counter() - stage_start))
        return QueryResult(plan.query_id, [r['review_id'] for r in rows],
                           rows if plan.output_format == 'rows' else [], stages, events,
                           perf_counter() - started)
