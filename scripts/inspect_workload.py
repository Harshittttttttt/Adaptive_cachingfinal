"""Measure real SQL candidate counts without LLM or embedding requests."""
import argparse
import json
from pathlib import Path
from time import perf_counter

from src.database.db import connect, filter_reviews
from src.query.plan import QueryPlan, selected_version
from src.settings import load_config


def inspect(config):
    results = []
    with connect(config['dataset']['database']) as db:
        version = selected_version(config, db)
        total = db.execute('SELECT count(*) FROM reviews WHERE dataset_version=?', (version,)).fetchone()[0]
        for spec in config['workload']:
            plan = QueryPlan.from_dict(spec, version)
            started = perf_counter()
            candidates = len(filter_reviews(db, version, plan.sql_filters))
            results.append(dict(query_id=plan.query_id, group=plan.group, total_rows=total,
                                sql_candidate_rows=candidates,
                                global_selectivity=candidates / total if total else 0,
                                semantic_tasks=[t.predicate_id for t in plan.semantic_tasks],
                                sql_seconds=perf_counter() - started))
    return dict(dataset_version=version, mode='sql_only_inspection', live_llm_calls=0,
                embedding_calls=0, queries=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/default.json')
    parser.add_argument('--output', default='results/raw/phase2_sql_workload.json')
    args = parser.parse_args()
    result = inspect(load_config(args.config))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
