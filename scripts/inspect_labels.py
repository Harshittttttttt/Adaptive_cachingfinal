"""Export a seeded sample for human review; never assume model labels are truth."""
import argparse
import csv
import random
from pathlib import Path

from src.database.db import connect
from src.llm.client import LLMClient
from src.query.plan import TASKS, selected_version
from src.llm.references import ReferenceStore
from src.settings import load_config


def export(config, output, size=30, seed=17):
    client = LLMClient(config['llm'])
    with connect(config['dataset']['database']) as db:
        version = selected_version(config, db)
        store = ReferenceStore(db)
        for task in TASKS.values():
            store.register_task(task)
        rows = db.execute('''SELECT l.*,r.review_text FROM reference_labels l JOIN reviews r
            ON l.dataset_version=r.dataset_version AND l.review_id=r.review_id
            WHERE l.dataset_version=? AND l.model_id=? AND l.generation_status='success'
            ORDER BY l.review_id,l.predicate_id''', (version, client.model_id)).fetchall()
        rows = [r for r in rows if r['predicate_id'] in TASKS
                and r['prompt_version'] == TASKS[r['predicate_id']].prompt_version]
        selected = random.Random(seed).sample(rows, min(size, len(rows)))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['dataset_version', 'review_id', 'predicate_id', 'prompt_version',
                         'model_id', 'review_text', 'reference_label', 'human_label', 'notes'])
        for row in selected:
            writer.writerow([row[k] for k in ('dataset_version', 'review_id', 'predicate_id',
                             'prompt_version', 'model_id', 'review_text', 'reference_label')] + ['', ''])
    return len(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/default.json')
    parser.add_argument('--output', default='data/reference_labels/manual_review.csv')
    parser.add_argument('--size', type=int, default=30)
    parser.add_argument('--seed', type=int, default=17)
    args = parser.parse_args()
    if args.size < 0:
        parser.error('--size must be nonnegative')
    print('Exported', export(load_config(args.config), args.output, args.size, args.seed), 'labels')


if __name__ == '__main__':
    main()
