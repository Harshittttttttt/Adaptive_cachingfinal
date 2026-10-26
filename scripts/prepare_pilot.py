"""Derive a separate, provenance-tracked 10-review development cohort."""
import argparse
import hashlib
import json
from pathlib import Path

from src.database.db import connect, initialize
from src.llm.client import LLMClient
from src.llm.references import ReferenceStore
from src.query.plan import TASKS, selected_version
from src.settings import load_config


def prepare(config):
    cfg=config['experiment']
    limit=cfg['pilot_rows']
    if limit!=10:raise ValueError('This approved pilot is fixed to the first 10 reviews')
    with connect(config['dataset']['database']) as source:
        parent=selected_version(config,source)
        reviews=source.execute('SELECT * FROM reviews WHERE dataset_version=? ORDER BY review_id LIMIT ?',
                               (parent,limit)).fetchall()
        if len(reviews)!=limit:raise ValueError('Not enough real rows for pilot')
        ids=[r['review_id'] for r in reviews]
        version=hashlib.sha256(json.dumps([parent,ids,'pilot-v1']).encode()).hexdigest()
        provenance=dict(parent_dataset_version=parent,selection='first 10 ORDER BY review_id',review_ids=ids,
                        purpose='development pilot; not final validation or test')
        client=LLMClient(config['llm'])
        refs=ReferenceStore(source)
        labels=[(version,r['review_id'],t.predicate_id,t.prompt_version,client.model_id,
                 refs.get(parent,r['review_id'],t,client.model_id),'success')
                for r in reviews for t in TASKS.values()]
        parent_info=source.execute('SELECT * FROM dataset_versions WHERE dataset_version=?',(parent,)).fetchone()
        with connect(cfg['pilot_database']) as target:
            initialize(target)
            store=ReferenceStore(target)
            for task in TASKS.values():store.register_task(task)
            target.execute('''INSERT OR IGNORE INTO dataset_versions
                (dataset_version,source_dataset,source_sha256,source_path,source_description,
                cleaning_config,row_count,cleaning_summary) VALUES (?,?,?,?,?,?,?,?)''',
                (version,'pilot-real-reviews',parent_info['source_sha256'],parent_info['source_path'],
                 'Derived real-data pilot; upstream provenance remains unknown',json.dumps(provenance),limit,json.dumps(provenance)))
            target.executemany('INSERT OR IGNORE INTO reviews VALUES (?,?,?,?,?,?,?,?,?)',
                               [(version,*tuple(r)[1:]) for r in reviews])
            target.executemany('''INSERT OR IGNORE INTO reference_labels
                (dataset_version,review_id,predicate_id,prompt_version,model_id,reference_label,generation_status)
                VALUES (?,?,?,?,?,?,?)''',labels)
    manifest=dict(dataset_version=version,row_count=limit,**provenance)
    path=Path(cfg['pilot_manifest']);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config/default.json')
    print(json.dumps(prepare(load_config(p.parse_args().config)),indent=2))


if __name__=='__main__':main()
