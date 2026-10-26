"""Verify the real import, repeat import and independent reconstruction."""
import argparse
import hashlib
import json
import platform
import sqlite3
import sys
from pathlib import Path
from time import perf_counter

from src.data.load_reviews import import_reviews
from src.database.db import connect, filter_reviews


def fingerprint(db, version):
    digest = hashlib.sha256()
    cursor = db.execute('SELECT * FROM reviews WHERE dataset_version=? ORDER BY review_id', (version,))
    for row in cursor:
        digest.update((json.dumps(tuple(row), ensure_ascii=True) + '\n').encode())
    return digest.hexdigest()


def verify(config, output):
    started = perf_counter()
    cfg = config['dataset']
    repeated = import_reviews(config)
    version = repeated['dataset_version']
    reconstruction = dict(cfg, database='data/processed/reconstruction.sqlite3',
                          report='data/processed/reconstruction_report.json')
    rebuilt = import_reviews(reconstruction)
    if rebuilt['dataset_version'] != version:
        raise AssertionError('Reconstruction changed dataset version')
    with connect(cfg['database']) as primary, connect(reconstruction['database']) as replica:
        primary_fingerprint = fingerprint(primary, version)
        reconstructed_fingerprint = fingerprint(replica, version)
        assert primary_fingerprint == reconstructed_fingerprint
        assert primary.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not primary.execute('PRAGMA foreign_key_check').fetchall()
        count = primary.execute('SELECT count(*) FROM reviews WHERE dataset_version=?', (version,)).fetchone()[0]
        assert count == repeated['output_rows']
        filters = [('rating', '<=', 2)]
        selected = filter_reviews(primary, version, filters)
        assert all(row['rating'] is not None and row['rating'] <= 2 for row in selected)
        expected = primary.execute('SELECT count(*) FROM reviews WHERE dataset_version=? AND rating<=2', (version,)).fetchone()[0]
        assert len(selected) == expected
        assert not filter_reviews(primary, version, [('rating', '<', 0)])
    result = {
        'dataset_version': version, 'row_count': count,
        'repeat_import_was_idempotent': repeated['already_imported'],
        'reconstruction_matches': True, 'ordered_records_sha256': primary_fingerprint,
        'integrity_check': 'ok', 'foreign_key_check': 'ok',
        'rating_at_most_two_count': expected, 'empty_filter_count': 0,
        'duration_seconds': perf_counter() - started,
        'python': sys.version, 'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/default.json')
    parser.add_argument('--output', default='results/raw/phase1_verification.json')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    print(json.dumps(verify(config, Path(args.output)), indent=2))


if __name__ == '__main__':
    main()
