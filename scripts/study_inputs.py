"""Prepare study labels/vectors on the explicitly approved cohort manifests."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from time import sleep
from urllib.error import HTTPError,URLError

from src.database.db import connect
from src.embeddings.client import EmbeddingClient,normalized
from src.llm.client import LLMClient,InferenceFailure,post_json
from src.llm.references import ReferenceStore
from src.query.plan import tasks_for
from src.settings import load_config
from scripts.prepare_embeddings import SCHEMA

ROOT=Path('data/processed/study')


def save_outcome(db,key,outcome):
    if isinstance(outcome,InferenceFailure):
        label,status,error,requests=None,'failed',str(outcome),outcome.records
    else:
        label,status,error,requests=outcome.label,'success',None,outcome.requests
    with db:
        db.executemany('''INSERT INTO reference_requests
            (dataset_version,review_id,predicate_id,prompt_version,model_id,attempt_json) VALUES (?,?,?,?,?,?)''',
            [(*key,json.dumps(r)) for r in requests])
        db.execute('''INSERT INTO reference_labels
            (dataset_version,review_id,predicate_id,prompt_version,model_id,reference_label,generation_status,error)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(dataset_version,review_id,predicate_id,prompt_version,model_id)
            DO UPDATE SET reference_label=excluded.reference_label,generation_status=excluded.generation_status,
            error=excluded.error,created_at=CURRENT_TIMESTAMP''',(*key,label,status,error))
    return status


def prepare_labels(config):
    client=LLMClient(config['llm']);counts=Counter()
    tasks=tasks_for(config)
    for split in ('validation','test'):
        manifest=json.loads((ROOT/(split+'_manifest.json')).read_text())
        with connect(ROOT/(split+'.sqlite3')) as db:
            store=ReferenceStore(db)
            for task in tasks.values():store.register_task(task)
            db.commit()
            rows=db.execute('SELECT * FROM reviews WHERE dataset_version=? ORDER BY review_id',
                            (manifest['dataset_version'],)).fetchall()
            if [r['review_id'] for r in rows]!=manifest['review_ids']:raise ValueError('Cohort changed')
            work=[]
            for row in rows:
                for task in tasks.values():
                    key=(manifest['dataset_version'],row['review_id'],task.predicate_id,task.prompt_version,client.model_id)
                    exists=db.execute('''SELECT generation_status FROM reference_labels WHERE dataset_version=? AND
                        review_id=? AND predicate_id=? AND prompt_version=? AND model_id=?''',key).fetchone()
                    if exists and exists[0]=='success':counts['reused']+=1;continue
                    if exists:raise ValueError('Saved failure requires deliberate diagnosis before retrying the approved budget')
                    work.append((key,task,row['review_text']))
            # Two simultaneous fixed-task requests reduce elapsed setup time;
            # all SQLite writes remain on this single thread.
            def infer(item):
                _,task,text=item
                try:return client.infer(task,text)
                except InferenceFailure as exc:return exc
            with ThreadPoolExecutor(max_workers=2) as pool:
                for item,outcome in zip(work,pool.map(infer,work)):
                    counts[save_outcome(db,item[0],outcome)]+=1
            distribution=[tuple(r) for r in db.execute('''SELECT predicate_id,reference_label,count(*) FROM
                reference_labels WHERE model_id=? AND prompt_version=?
                GROUP BY predicate_id,reference_label ORDER BY predicate_id,reference_label''',
                (client.model_id,next(iter(tasks.values())).prompt_version))]
            print(json.dumps({'split':split,'labels':distribution,'statuses':dict(counts)}),flush=True)
    return dict(counts)


def prepare_vectors(config):
    import os
    encoder=EmbeddingClient(config['embedding'])
    tasks=tasks_for(config)
    key=os.environ.get(config['embedding'].get('api_key_env','MISTRAL_API_KEY'))
    if not key:raise ValueError('MISTRAL_API_KEY missing')
    total=Counter()
    for split in ('validation','test'):
        manifest=json.loads((ROOT/(split+'_manifest.json')).read_text())
        with connect(ROOT/(split+'.sqlite3')) as db:
            db.executescript(SCHEMA)
            rows=db.execute('SELECT * FROM reviews WHERE dataset_version=? ORDER BY review_id',
                            (manifest['dataset_version'],)).fetchall()
            if [r['review_id'] for r in rows]!=manifest['review_ids']:raise ValueError('Cohort changed')
            inputs={}
            for row in rows:
                for task in tasks.values():
                    text=task.input_text(row['review_text']);digest=hashlib.sha256(text.encode()).hexdigest()
                    if not db.execute('SELECT 1 FROM prepared_embeddings WHERE dataset_version=? AND model_id=? AND request_key=?',
                                      (manifest['dataset_version'],encoder.model_id,digest)).fetchone():inputs[digest]=text
            keys=list(inputs)
            for start in range(0,len(keys),48):
                batch=keys[start:start+48]
                ledger_path=ROOT/'corrected_embedding_budget.json'
                ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {'reserved_inputs':0,'limit':480}
                if ledger['reserved_inputs']+len(batch)>ledger['limit']:
                    raise ValueError('Corrected embedding input budget exhausted')
                ledger['reserved_inputs']+=len(batch)
                ledger_path.write_text(json.dumps(ledger,indent=2)+'\n',encoding='utf-8')
                for attempt in range(1):
                    try:
                        response=post_json(encoder.base+'/embeddings',
                            {'model':encoder.model,'input':[inputs[k] for k in batch],'encoding_format':'float'},
                            {'Authorization':'Bearer '+key},60)
                        break
                    except (HTTPError,URLError,TimeoutError):
                        raise
                data=sorted(response['data'],key=lambda r:r['index'])
                if [r['index'] for r in data]!=list(range(len(batch))):raise ValueError('Embedding batch indices missing or duplicated')
                tokens=response.get('usage',{}).get('prompt_tokens')
                metadata={'batch_input_tokens':tokens,'batch_size':len(batch),'attempts':attempt+1,
                          'batch_id':hashlib.sha256(''.join(batch).encode()).hexdigest(),
                          'token_allocation':'batch total counted once, not per vector','provider_model':response.get('model')}
                with db:
                    for digest,item in zip(batch,data):
                        db.execute('INSERT INTO prepared_embeddings VALUES (?,?,?,?,?)',
                            (manifest['dataset_version'],encoder.model_id,digest,json.dumps(normalized(item['embedding'])),json.dumps(metadata)))
                total['requests']+=attempt+1;total['inputs']+=len(batch);total['input_tokens']+=tokens or 0
            print(json.dumps({'split':split,'new_embedding_totals':dict(total)}),flush=True)
    return dict(total)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='config/default.json')
    p.add_argument('--stage',choices=['labels','embeddings','all'],default='all');args=p.parse_args()
    cfg=load_config(args.config);result={}
    if args.stage in ('labels','all'):result['labels']=prepare_labels(cfg)
    if args.stage in ('embeddings','all'):result['embeddings']=prepare_vectors(cfg)
    Path('results/study').mkdir(parents=True,exist_ok=True)
    Path('results/study/preparation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
