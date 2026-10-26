"""Generate cache-independent labels with explicit task/row budgets; resumable."""
import argparse
from collections import Counter
import json
from pathlib import Path

from src.database.db import connect
from src.llm.client import LLMClient
from src.llm.references import ReferenceStore
from src.query.plan import TASKS, selected_version
from src.settings import load_config


def generate(config, predicates, limit, offset=0, retry_failed=False):
    if limit <= 0 or offset < 0:
        raise ValueError('Provide a positive row limit and nonnegative offset')
    client = LLMClient(config['llm'])
    counts = Counter()
    with connect(config['dataset']['database']) as db:
        version = selected_version(config, db)
        store = ReferenceStore(db)
        rows = db.execute('SELECT * FROM reviews WHERE dataset_version=? ORDER BY review_id LIMIT ? OFFSET ?',
                          (version, limit, offset)).fetchall()
        for row in rows:
            for predicate in predicates:
                counts[store.generate(version, row, TASKS[predicate], client, retry_failed)] += 1
    return dict(mode='offline_reference_generation', dataset_version=version,
                model_id=client.model_id, rows=len(rows), predicates=predicates,
                offset=offset, limit=limit, status_counts=dict(counts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/default.json')
    parser.add_argument('--predicates', nargs='+', choices=sorted(TASKS), default=sorted(TASKS))
    parser.add_argument('--limit', type=int, default=10, help='Maximum reviews, not requests; multiplied by task count')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--output', default='data/reference_labels/generation_summary.json')
    args = parser.parse_args()
    result = generate(load_config(args.config), args.predicates, args.limit, args.offset, args.retry_failed)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
