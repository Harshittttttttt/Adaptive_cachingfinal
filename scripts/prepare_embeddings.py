"""Precompute embeddings for the same approved pilot inputs, once per task."""
import argparse
import hashlib
import json
from pathlib import Path

from src.database.db import connect
from src.embeddings.client import EmbeddingClient
from src.query.plan import TASKS
from src.settings import load_config

SCHEMA='''CREATE TABLE IF NOT EXISTS prepared_embeddings (
 dataset_version TEXT NOT NULL, model_id TEXT NOT NULL, request_key TEXT NOT NULL,
 vector_json TEXT NOT NULL, request_json TEXT NOT NULL,
 PRIMARY KEY(dataset_version,model_id,request_key));'''


def prepare(config):
    exp=config['experiment']
    version=json.loads(Path(exp['pilot_manifest']).read_text())['dataset_version']
    encoder=EmbeddingClient(config['embedding'])
    with connect(exp['pilot_database']) as db:
        db.executescript(SCHEMA)
        rows=db.execute('SELECT * FROM reviews WHERE dataset_version=? ORDER BY review_id',(version,)).fetchall()
        if len(rows)!=10:raise ValueError('Embedding export limited to approved 10-review pilot')
        reused=0
        for row in rows:
            for task in TASKS.values():
                text=task.input_text(row['review_text'])
                key=hashlib.sha256(text.encode()).hexdigest()
                if db.execute('SELECT 1 FROM prepared_embeddings WHERE dataset_version=? AND model_id=? AND request_key=?',
                              (version,encoder.model_id,key)).fetchone():
                    reused+=1;continue
                vector=encoder.embed(text)
                db.execute('INSERT INTO prepared_embeddings VALUES (?,?,?,?,?)',
                           (version,encoder.model_id,key,json.dumps(vector),json.dumps(encoder.requests[-1])))
                db.commit()
        records=[json.loads(r[0]) for r in db.execute('SELECT request_json FROM prepared_embeddings WHERE dataset_version=? AND model_id=?',
                                                     (version,encoder.model_id))]
    result=dict(mode='offline_embedding_preparation',dataset_version=version,embedding_model=encoder.model_id,
                prepared_inputs=len(records),reused_this_invocation=reused,new_api_requests=len(encoder.requests),
                input_tokens=sum(r['input_tokens'] or 0 for r in records),
                estimated_cost_usd=sum(r['estimated_cost_usd'] or 0 for r in records),requests=records)
    output=Path('results/raw/embedding_preparation.json');output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return {k:v for k,v in result.items() if k!='requests'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config/default.json')
    print(json.dumps(prepare(load_config(p.parse_args().config)),indent=2))


if __name__=='__main__':main()
