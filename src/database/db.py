"""Transactional, version-aware storage shared by future pipeline phases."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset_versions (
 dataset_version TEXT PRIMARY KEY, source_dataset TEXT NOT NULL,
 source_sha256 TEXT NOT NULL, source_path TEXT NOT NULL, source_description TEXT NOT NULL,
 cleaning_config TEXT NOT NULL, row_count INTEGER NOT NULL,
 cleaning_summary TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS reviews (
 dataset_version TEXT NOT NULL REFERENCES dataset_versions(dataset_version),
 review_id TEXT NOT NULL, product_name TEXT, price REAL, rating REAL,
 review_text TEXT NOT NULL CHECK(length(trim(review_text)) > 0), summary TEXT,
 category TEXT, source_dataset TEXT NOT NULL,
 PRIMARY KEY(dataset_version, review_id)
);
CREATE INDEX IF NOT EXISTS reviews_rating ON reviews(dataset_version, rating);
CREATE INDEX IF NOT EXISTS reviews_price ON reviews(dataset_version, price);
CREATE INDEX IF NOT EXISTS reviews_product ON reviews(dataset_version, product_name);
CREATE INDEX IF NOT EXISTS reviews_category ON reviews(dataset_version, category);
CREATE TABLE IF NOT EXISTS reference_labels (
 dataset_version TEXT NOT NULL, review_id TEXT NOT NULL, predicate_id TEXT NOT NULL,
 prompt_version TEXT NOT NULL, model_id TEXT NOT NULL,
 reference_label TEXT CHECK(reference_label IN ('YES','NO')),
 generation_status TEXT NOT NULL CHECK(generation_status IN ('success','failed')),
 error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK((generation_status='success' AND reference_label IS NOT NULL)
 OR (generation_status='failed' AND reference_label IS NULL)),
 PRIMARY KEY(dataset_version,review_id,predicate_id,prompt_version,model_id),
 FOREIGN KEY(dataset_version,review_id) REFERENCES reviews(dataset_version,review_id)
);
CREATE TABLE IF NOT EXISTS experiment_runs (
 run_id TEXT PRIMARY KEY, policy_name TEXT NOT NULL, configuration TEXT NOT NULL,
 dataset_version TEXT NOT NULL REFERENCES dataset_versions(dataset_version),
 model_version TEXT NOT NULL, cache_state TEXT NOT NULL, random_seed INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cache_entries (
 entry_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
 dataset_version TEXT NOT NULL, predicate_id TEXT NOT NULL, prompt_version TEXT NOT NULL,
 model_id TEXT NOT NULL, embedding_model TEXT NOT NULL, request_key TEXT NOT NULL,
 request_text TEXT NOT NULL, response TEXT NOT NULL, embedding_json TEXT NOT NULL,
 metadata_json TEXT NOT NULL, algorithm_version TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS cache_namespace ON cache_entries
 (run_id,dataset_version,predicate_id,prompt_version,model_id,embedding_model);
CREATE TABLE IF NOT EXISTS experiment_events (
 event_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
 query_id TEXT NOT NULL, review_id TEXT, predicate_id TEXT, stage INTEGER,
 similarity REAL, global_selectivity REAL, stage_selectivity REAL,
 policy_decision TEXT NOT NULL, decision_reason TEXT NOT NULL,
 llm_calls INTEGER NOT NULL DEFAULT 0, audit_calls INTEGER NOT NULL DEFAULT 0,
 correct INTEGER, timings_json TEXT NOT NULL, details_json TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS events_run_query ON experiment_events(run_id,query_id);
"""


@contextmanager
def connect(path):
    """Enable foreign keys on every connection; commit only on success."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=NORMAL')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(db):
    db.executescript(SCHEMA)


def filter_reviews(db, dataset_version, filters=()):
    """Allowlisted structured filters; values always use SQL parameters."""
    allowed = {'rating', 'price', 'product_name', 'category', 'review_id'}
    numeric = {'rating', 'price'}
    import math
    clauses, values = ['dataset_version = ?'], [dataset_version]
    for column, operator, value in filters:
        if column not in allowed or operator not in {'=', '!=', '<', '<=', '>', '>='}:
            raise ValueError('Unsupported structured filter')
        if value is None:
            raise ValueError('Null filter values require an explicit null operator')
        if column in numeric:
            if isinstance(value, bool):
                raise ValueError('Numeric filter must be finite')
            try:
                value = float(value)
            except (ValueError, TypeError) as exc:
                raise ValueError('Numeric filter must be finite') from exc
            if not math.isfinite(value):
                raise ValueError('Numeric filter must be finite')
        clauses.append(f'{column} {operator} ?')
        values.append(value)
    return db.execute('SELECT * FROM reviews WHERE ' + ' AND '.join(clauses)
                      + ' ORDER BY review_id', values).fetchall()
