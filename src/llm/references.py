"""Version-safe saved reference outputs. Never consult a semantic cache."""
from dataclasses import asdict
import json

from src.llm.client import InferenceFailure

SCHEMA = '''
CREATE TABLE IF NOT EXISTS task_definitions (
 predicate_id TEXT NOT NULL, prompt_version TEXT NOT NULL, fingerprint TEXT NOT NULL,
 definition_json TEXT NOT NULL, PRIMARY KEY(predicate_id,prompt_version)
);
CREATE TABLE IF NOT EXISTS reference_requests (
 request_id INTEGER PRIMARY KEY, dataset_version TEXT NOT NULL, review_id TEXT NOT NULL,
 predicate_id TEXT NOT NULL, prompt_version TEXT NOT NULL, model_id TEXT NOT NULL,
 purpose TEXT NOT NULL DEFAULT 'offline_reference' CHECK(purpose='offline_reference'),
 attempt_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(dataset_version,review_id) REFERENCES reviews(dataset_version,review_id)
);
CREATE INDEX IF NOT EXISTS reference_requests_key ON reference_requests
 (dataset_version,review_id,predicate_id,prompt_version,model_id);
'''


class ReferenceStore:
    def __init__(self, db):
        self.db = db
        db.executescript(SCHEMA)

    def register_task(self, task):
        prior = self.db.execute('SELECT fingerprint FROM task_definitions WHERE predicate_id=? AND prompt_version=?',
                                (task.predicate_id, task.prompt_version)).fetchone()
        if prior and prior['fingerprint'] != task.fingerprint:
            raise ValueError('Task changed without a new prompt version; stale labels forbidden')
        if prior:
            return
        self.db.execute('INSERT OR IGNORE INTO task_definitions VALUES (?,?,?,?)',
                        (task.predicate_id, task.prompt_version, task.fingerprint,
                         json.dumps(asdict(task), sort_keys=True)))

    def get(self, version, review_id, task, model_id):
        self.register_task(task)
        row = self.db.execute('''SELECT reference_label FROM reference_labels WHERE
            dataset_version=? AND review_id=? AND predicate_id=? AND prompt_version=?
            AND model_id=? AND generation_status='success' ''',
            (version, review_id, task.predicate_id, task.prompt_version, model_id)).fetchone()
        if not row:
            raise LookupError('No successful reference for exact dataset/task/prompt/model version')
        return row['reference_label']

    def generate(self, version, row, task, client, retry_failed=False):
        self.register_task(task)
        stored = self.db.execute('SELECT review_text FROM reviews WHERE dataset_version=? AND review_id=?',
                                 (version, row['review_id'])).fetchone()
        if not stored or stored['review_text'] != row['review_text']:
            raise ValueError('Reference input does not match the selected dataset record')
        key = (version, row['review_id'], task.predicate_id, task.prompt_version, client.model_id)
        saved = self.db.execute('''SELECT generation_status FROM reference_labels WHERE
            dataset_version=? AND review_id=? AND predicate_id=? AND prompt_version=? AND model_id=?''', key).fetchone()
        if saved and (saved['generation_status'] == 'success' or not retry_failed):
            return 'reused' if saved['generation_status'] == 'success' else 'saved_failure'
        label, error = None, None
        try:
            result = client.infer(task, row['review_text'])
            label, requests, status = result.label, result.requests, 'success'
        except InferenceFailure as exc:
            error, requests, status = str(exc), exc.records, 'failed'
        # An interrupted network call never writes a made-up label. Each review's
        # records and terminal status commit together for resumable generation.
        with self.db:
            self.db.executemany('''INSERT INTO reference_requests
                (dataset_version,review_id,predicate_id,prompt_version,model_id,attempt_json)
                VALUES (?,?,?,?,?,?)''', [(*key, json.dumps(r, sort_keys=True)) for r in requests])
            self.db.execute('''INSERT INTO reference_labels
                (dataset_version,review_id,predicate_id,prompt_version,model_id,reference_label,generation_status,error)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(dataset_version,review_id,predicate_id,prompt_version,model_id)
                DO UPDATE SET reference_label=excluded.reference_label,
                generation_status=excluded.generation_status,error=excluded.error,created_at=CURRENT_TIMESTAMP''',
                (*key, label, status, error))
        return status


class ReplayEvaluator:
    """Oracle replay simulates a requested inference; makes zero live calls."""
    mode = 'offline'
    def __init__(self, store, model_id):
        self.store, self.model_id = store, model_id

    def evaluate(self, task, row, context):
        from src.query.executor import Evaluation
        label = self.store.get(context.dataset_version, row['review_id'], task, self.model_id)
        return Evaluation(label, reason='offline_replay', llm_calls=0,
                          details={'mode': 'offline', 'simulated_llm_calls': 1})
