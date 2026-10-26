"""Export a reproducible validation-only audit sample; blanks are not annotations."""
import csv
import json
from pathlib import Path
import random

from src.database.db import connect
from src.llm.client import LLMClient
from src.settings import load_config


def main():
    config=load_config('config/study.json');client=LLMClient(config['llm'])
    with connect('data/processed/study/validation.sqlite3') as db:
        rows=[dict(r) for r in db.execute('''SELECT r.review_id,r.review_text,l.predicate_id,l.prompt_version,
            l.reference_label FROM reference_labels l JOIN reviews r
            ON l.dataset_version=r.dataset_version AND l.review_id=r.review_id
            WHERE l.model_id=? AND l.prompt_version='v2' AND l.generation_status='success'
            ORDER BY r.review_id,l.predicate_id''',(client.model_id,))]
    sample=random.Random(2252).sample(rows,24)
    path=Path('data/reference_labels/validation_audit.csv')
    with path.open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=[*sample[0],'reviewer_label','reviewer_type','notes'])
        writer.writeheader();writer.writerows(sample)
    Path('results/study/validation_audit_sample.json').write_text(json.dumps(sample,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
    print(json.dumps(sample,indent=2,ensure_ascii=True))


if __name__=='__main__':main()
