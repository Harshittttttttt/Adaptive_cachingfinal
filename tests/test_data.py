import csv
import hashlib
import json
import sqlite3

import pytest

from src.data.load_reviews import import_reviews
from src.data.validate_dataset import parse_numeric, resolve_columns
from src.database.db import connect, filter_reviews


def write_csv(path, rows, headers=('ProductName', 'Price', 'Rate', 'Review', 'Summary')):
    with path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)


@pytest.fixture
def prepared(tmp_path):
    # Synthetic fixtures test cleaning only; never used as experimental data.
    write_csv(tmp_path / 'reviews.csv', [
        ['Fan', '$1,200', '2', '  Arrived broken  ', 'Bad'],
        ['Fan', '$1,200', '2', '  Arrived broken  ', 'Bad'],
        ['Cup', 'bad', '9', 'Works', ''],
        ['', '', '', '  ', 'Missing'],
        ['Cup', '20', '5', 'Nice', 'Good'],
    ])
    cfg = dict(path='reviews.csv', database='reviews.db', report='report.json',
               name='test-fixture', encoding='utf-8', missing_review='drop', deduplicate=True)
    return tmp_path, cfg


def test_import_quality_and_source_preservation(prepared):
    root, cfg = prepared
    before = (root / 'reviews.csv').read_bytes()
    report = import_reviews(cfg, root)
    assert report['input_rows'] == 5
    assert report['output_rows'] == 3
    assert report['exact_duplicate_rows'] == report['canonical_duplicate_rows'] == 1
    assert report['dropped_missing_review_rows'] == 1
    assert report['missing_values']['review_text'] == 1
    assert report['invalid_numeric_values'] == {'price': 1, 'rating': 1}
    assert (root / 'reviews.csv').read_bytes() == before
    assert report['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert json.loads((root / 'report.json').read_text()) == report
    with connect(root / cfg['database']) as db:
        rows = filter_reviews(db, report['dataset_version'])
        assert len(rows) == 3
        broken = next(r for r in rows if r['product_name'] == 'Fan')
        assert broken['price'] == 1200 and broken['review_text'] == 'Arrived broken'
        invalid = next(r for r in rows if r['review_text'] == 'Works')
        assert invalid['price'] is None and invalid['rating'] is None
        assert invalid['category'] is None
        assert len(filter_reviews(db, report['dataset_version'], [('rating', '<=', 2)])) == 1
        assert len(filter_reviews(db, report['dataset_version'], [('rating', '>', 99)])) == 0


def test_repeated_import_and_reconstruction(prepared):
    root, cfg = prepared
    first = import_reviews(cfg, root)
    second = import_reviews(cfg, root)
    assert second['already_imported'] is True
    assert first['dataset_version'] == second['dataset_version']
    with connect(root / cfg['database']) as db:
        original = [tuple(row) for row in filter_reviews(db, first['dataset_version'])]
        assert db.execute('SELECT count(*) FROM dataset_versions').fetchone()[0] == 1
    rebuilt = import_reviews(dict(cfg, database='rebuilt.db'), root)
    with connect(root / 'rebuilt.db') as db:
        assert original == [tuple(row) for row in filter_reviews(db, rebuilt['dataset_version'])]


def test_ids_stable_under_reordering(prepared):
    root, cfg = prepared
    report = import_reviews(cfg, root)
    with connect(root / cfg['database']) as db:
        ids = {r['review_id'] for r in filter_reviews(db, report['dataset_version'])}
    with (root / cfg['path']).open(newline='', encoding='utf-8') as file:
        rows = list(csv.reader(file))
    write_csv(root / 'reordered.csv', reversed(rows[1:]), rows[0])
    other = import_reviews(dict(cfg, path='reordered.csv'), root)
    assert other['dataset_version'] != report['dataset_version']
    with connect(root / cfg['database']) as db:
        assert ids == {r['review_id'] for r in filter_reviews(db, other['dataset_version'])}


def test_required_columns_and_aliases():
    with pytest.raises(ValueError, match='Required'):
        resolve_columns(['Product', 'Price'])
    assert resolve_columns(['reviewText', 'overall'])['rating'] == 'overall'
    with pytest.raises(ValueError, match='Ambiguous'):
        resolve_columns(['review', 'review_text'])
    with pytest.raises(ValueError, match='missing'):
        resolve_columns(['Review'], {'review_text': 'Absent'})
    with pytest.raises(ValueError, match='non-duplicate'):
        resolve_columns(['Review', 'Review'])


def test_real_header_mapping(tmp_path):
    write_csv(tmp_path / 'a.csv', [['Fan', '10', '2', 'Headline', 'Actual body']],
              ['Product_name', 'Price', 'Rate', 'Review', 'Summary'])
    cfg = dict(path='a.csv', database='a.db', name='fixture',
               columns={'review_text': 'Summary', 'summary': 'Review'})
    report = import_reviews(cfg, tmp_path)
    with connect(tmp_path / 'a.db') as db:
        row = filter_reviews(db, report['dataset_version'])[0]
        assert row['review_text'] == 'Actual body' and row['summary'] == 'Headline'


def test_missing_review_strict_rolls_back(prepared):
    root, cfg = prepared
    with pytest.raises(ValueError, match='Missing review'):
        import_reviews(dict(cfg, missing_review='error'), root)
    assert not (root / cfg['database']).exists()


@pytest.mark.parametrize('value', ['nan', 'inf', '-1', '1,20', 'nonsense', '9e999'])
def test_invalid_price(value):
    assert parse_numeric(value, 'price', {}) == (None, True)


def test_optional_columns_and_duplicate_retention(tmp_path):
    write_csv(tmp_path / 'a.csv', [['Body'], ['Body']], ['Review'])
    cfg = dict(path='a.csv', database='a.db', name='fixture', deduplicate=False)
    report = import_reviews(cfg, tmp_path)
    assert report['output_rows'] == 2
    with connect(tmp_path / 'a.db') as db:
        rows = filter_reviews(db, report['dataset_version'])
        assert rows[0]['review_id'] != rows[1]['review_id']
        assert rows[0]['product_name'] is None


def test_configuration_versions_and_namespaces(prepared):
    root, cfg = prepared
    first = import_reviews(cfg, root)
    second = import_reviews(dict(cfg, rating_max=10), root)
    assert first['dataset_version'] != second['dataset_version']
    with connect(root / cfg['database']) as db:
        assert len(filter_reviews(db, first['dataset_version'])) == 3
        assert len(filter_reviews(db, second['dataset_version'])) == 3


@pytest.mark.parametrize('field,op,value', [
    ('rating', '<=', 'oops'), ('rating', '=', float('nan')),
    ('price', '=', True), ('price', '=', None),
    ('DROP TABLE reviews', '=', 1), ('rating', 'OR 1=1', 2),
])
def test_invalid_filters(prepared, field, op, value):
    root, cfg = prepared
    report = import_reviews(cfg, root)
    with connect(root / cfg['database']) as db:
        with pytest.raises(ValueError):
            filter_reviews(db, report['dataset_version'], [(field, op, value)])


def test_reference_label_unique_key_and_foreign_keys(prepared):
    root, cfg = prepared
    report = import_reviews(cfg, root)
    with connect(root / cfg['database']) as db:
        row = filter_reviews(db, report['dataset_version'])[0]
        values = (report['dataset_version'], row['review_id'], 'shipping', 'v1', 'model', 'YES', 'success')
        statement = '''INSERT INTO reference_labels
            (dataset_version,review_id,predicate_id,prompt_version,model_id,reference_label,generation_status)
            VALUES (?,?,?,?,?,?,?)'''
        db.execute(statement, values)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statement, values)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statement, ('stale', *values[1:]))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(statement, (*values[:3], 'v2', 'model', None, 'success'))
        db.execute(statement, (*values[:3], 'v2', *values[4:]))


def test_malformed_csv_and_encoding(tmp_path):
    path = tmp_path / 'a.csv'
    path.write_text('Review,Rate\nbody,2,extra\n')
    cfg = dict(path='a.csv', database='a.db', name='fixture')
    with pytest.raises(ValueError, match='Malformed'):
        import_reviews(cfg, tmp_path)
    path.write_bytes(b'Review\n\x98\n')
    with pytest.raises(UnicodeDecodeError):
        import_reviews(cfg, tmp_path)


def test_database_transaction_rollback(tmp_path):
    from src.database.db import initialize
    with connect(tmp_path / 'a.db') as db:
        initialize(db)
    with pytest.raises(RuntimeError):
        with connect(tmp_path / 'a.db') as db:
            db.execute("INSERT INTO dataset_versions VALUES ('v','a','b','c','d','{}',0,'{}',CURRENT_TIMESTAMP)")
            raise RuntimeError('abort')
    with connect(tmp_path / 'a.db') as db:
        assert db.execute('SELECT count(*) FROM dataset_versions').fetchone()[0] == 0
