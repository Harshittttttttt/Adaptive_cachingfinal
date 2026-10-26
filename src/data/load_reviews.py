"""Reconstructible CSV -> SQLite import. Source bytes are never modified."""
import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from src.data.validate_dataset import clean_record, resolve_columns
from src.database.db import connect, initialize

PIPELINE_VERSION = 'reviews-cleaning-v1'


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def import_reviews(config, base_dir='.'):
    """Return a quality manifest. Same source/config is an idempotent import."""
    cfg = config.get('dataset', config)
    if cfg.get('missing_review', 'drop') not in {'drop', 'error'}:
        raise ValueError('missing_review must be drop or error')
    if cfg.get('rating_min', 1) > cfg.get('rating_max', 5):
        raise ValueError('Invalid rating bounds')
    base = Path(base_dir)
    source = base / cfg['path']
    source_bytes = source.read_bytes()
    source_sha = digest(source_bytes)
    # Fail on incompatible encoding instead of replacing undecodable characters.
    encoding = cfg.get('encoding', 'utf-8-sig')
    source_bytes.decode(encoding, errors='strict')
    cleaning = {k: cfg[k] for k in ('columns', 'rating_min', 'rating_max',
                'numeric_prefixes', 'missing_review', 'deduplicate') if k in cfg}
    cleaning.update(pipeline_version=PIPELINE_VERSION, encoding=encoding,
                    source_dataset=cfg['name'])
    version = digest((source_sha + canonical_json(cleaning)).encode())
    report = {
        'dataset_version': version, 'source_sha256': source_sha,
        'source_dataset': cfg['name'], 'source_path': str(source.resolve()),
        'source_description': cfg.get('source', 'Unknown upstream source'),
        'cleaning_config': cleaning, 'input_rows': 0, 'output_rows': 0,
        'exact_duplicate_rows': 0, 'canonical_duplicate_rows': 0,
        'missing_review_rows': 0, 'dropped_missing_review_rows': 0,
        'missing_values': {}, 'invalid_numeric_values': {},
    }
    records, seen_raw, seen_clean = [], set(), Counter()
    missing_counts, invalid_counts = Counter(), Counter()
    # Parse the very bytes hashed above, even if another process replaces the file.
    with io.TextIOWrapper(io.BytesIO(source_bytes), encoding=encoding, newline='') as file:
        reader = csv.DictReader(file, strict=True)
        mapping = resolve_columns(reader.fieldnames, cfg.get('columns'))
        report['source_columns'] = reader.fieldnames
        report['column_mapping'] = mapping
        for line, row in enumerate(reader, 2):
            report['input_rows'] += 1
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'Malformed CSV record near line {line}')
            raw_key = digest(canonical_json(row).encode())
            if raw_key in seen_raw:
                report['exact_duplicate_rows'] += 1
            seen_raw.add(raw_key)
            record, missing, invalid = clean_record(row, mapping, cfg)
            missing_counts.update(missing)
            invalid_counts.update(invalid)
            if record['review_text'] is None:
                report['missing_review_rows'] += 1
                if cfg.get('missing_review', 'drop') == 'error':
                    raise ValueError(f'Missing review text near line {line}')
                report['dropped_missing_review_rows'] += 1
                continue
            identity = digest(canonical_json(record).encode())
            occurrence = seen_clean[identity]
            seen_clean[identity] += 1
            if occurrence:
                report['canonical_duplicate_rows'] += 1
                if cfg.get('deduplicate', True):
                    continue
            # Content IDs survive relocation and row reordering. With duplicates
            # retained, the multiset of occurrence IDs remains stable.
            review_id = identity if cfg.get('deduplicate', True) else f'{identity}:{occurrence}'
            records.append((version, review_id, record['product_name'], record['price'],
                            record['rating'], record['review_text'], record['summary'],
                            record['category'], cfg['name']))
    report.update(output_rows=len(records), missing_values=dict(missing_counts),
                  invalid_numeric_values=dict(invalid_counts))
    with connect(base / cfg['database']) as db:
        initialize(db)
        existing = db.execute('SELECT row_count FROM dataset_versions WHERE dataset_version=?',
                              (version,)).fetchone()
        if existing:
            count = db.execute('SELECT count(*) FROM reviews WHERE dataset_version=?', (version,)).fetchone()[0]
            if count != len(records) or count != existing['row_count']:
                raise ValueError('Stored dataset is inconsistent; refusing silent repair')
            report['already_imported'] = True
        else:
            db.execute('''INSERT INTO dataset_versions
                (dataset_version,source_dataset,source_sha256,source_path,source_description,
                 cleaning_config,row_count,cleaning_summary) VALUES (?,?,?,?,?,?,?,?)''',
                (version, cfg['name'], source_sha, str(source.resolve()), report['source_description'],
                 canonical_json(cleaning), len(records), canonical_json(report)))
            db.executemany('INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?)', records)
            report['already_imported'] = False
    if cfg.get('report'):
        destination = base / cfg['report']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config/default.json')
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    print(json.dumps(import_reviews(config, Path.cwd()), indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
