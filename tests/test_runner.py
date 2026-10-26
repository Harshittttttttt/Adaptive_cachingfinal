import hashlib
import json

from src.data.load_reviews import import_reviews
from src.database.db import connect
from src.embeddings.client import EmbeddingClient
from src.evaluation.runner import run
from src.llm.client import LLMClient
from src.llm.references import ReferenceStore
from src.query.plan import TASKS
from scripts.prepare_embeddings import SCHEMA


def test_all_policies_end_to_end_replay_and_isolated_runs(tmp_path,monkeypatch):
    monkeypatch.setenv('MISTRAL_API_KEY','fixture-key-never-sent')
    # Mixed labels are intentional test fixtures; the real pilot is separate.
    path=tmp_path/'a.csv'
    path.write_text('Review,Rate\n'+''.join(f'row {i},{1 if i<5 else 5}\n' for i in range(10)),encoding='utf-8')
    report=import_reviews(dict(path='a.csv',database='a.db',name='fixture'),tmp_path)
    version=report['dataset_version']
    config=dict(llm={'provider':'mistral','model':'fixture'},embedding={'model':'fixture'},
                policies={},logging={'directory':str(tmp_path/'logs')},
                workload=[dict(query_id='q',sql_filters=[['rating','<=',2]],semantic_tasks=['shipping'])],
                experiment={'pilot_manifest':str(tmp_path/'manifest.json'),'max_live_request_attempts':0})
    client=LLMClient(config['llm'])
    model=EmbeddingClient(config['embedding']).model_id
    with connect(tmp_path/'a.db') as db:
        refs=ReferenceStore(db)
        db.executescript(SCHEMA)
        rows=db.execute('SELECT * FROM reviews ORDER BY review_id').fetchall()
        (tmp_path/'manifest.json').write_text(json.dumps({'dataset_version':version,'review_ids':[r['review_id'] for r in rows]}))
        for row in rows:
            task=TASKS['shipping'];refs.register_task(task)
            label='YES' if int(row['review_text'].split()[1])%2 else 'NO'
            db.execute('INSERT INTO reference_labels VALUES (?,?,?,?,?,?,?,NULL,CURRENT_TIMESTAMP)',
                       (version,row['review_id'],task.predicate_id,task.prompt_version,client.model_id,label,'success'))
            text=task.input_text(row['review_text']);key=hashlib.sha256(text.encode()).hexdigest()
            # Orthogonal per-record vectors keep this integration test's reuse
            # mathematically unambiguous and independent of a learned encoder.
            vector=[int(i==int(row['review_text'].split()[1])) for i in range(10)]
            db.execute('INSERT INTO prepared_embeddings VALUES (?,?,?,?,?)',(version,model,key,json.dumps(vector),'{}'))
        db.commit()
        summaries=run(config,db)
        assert len(summaries)==14
        assert all(s['actual_llm_request_attempts']==0 for s in summaries)
        assert all(s['row_set_agreement']==1 for s in summaries)
        assert next(s for s in summaries if s['policy']=='P0' and s['cache_state']=='cold')['simulated_llm_calls']==5
        assert next(s for s in summaries if s['policy']=='P6' and s['cache_state']=='warm')['direct_hits']==5
        assert len({s['run_id'] for s in summaries})==14
        assert db.execute('SELECT count(*) FROM experiment_runs').fetchone()[0]==14
        assert db.execute('SELECT count(*) FROM experiment_events').fetchone()[0]==105
        logs=list((tmp_path/'logs').glob('*.jsonl'))
        assert len(logs)==14
        assert all(json.loads(p.read_text().splitlines()[-1])['kind']=='summary' for p in logs)
