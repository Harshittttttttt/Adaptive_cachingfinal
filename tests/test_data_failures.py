import csv
import sqlite3

import pytest

from src.data.load_reviews import import_reviews
from src.database.db import connect, filter_reviews


def config():
    return dict(path='a.csv', database='a.db', name='fixture')


def test_canonical_duplicates_after_whitespace_cleaning(tmp_path):
    (tmp_path / 'a.csv').write_text('Review,Rate\n body ,2\nbody,2\n', encoding='utf-8')
    report = import_reviews(config(), tmp_path)
    assert report['exact_duplicate_rows'] == 0
    assert report['canonical_duplicate_rows'] == 1
    assert report['output_rows'] == 1


def test_corrupt_stored_count_is_rejected(tmp_path):
    (tmp_path / 'a.csv').write_text('Review\nbody\n', encoding='utf-8')
    import_reviews(config(), tmp_path)
    with connect(tmp_path / 'a.db') as db:
        db.execute('DELETE FROM reviews')
    with pytest.raises(ValueError, match='inconsistent'):
        import_reviews(config(), tmp_path)


def test_missing_file_has_no_database_side_effect(tmp_path):
    with pytest.raises(FileNotFoundError):
        import_reviews(config(), tmp_path)
    assert not (tmp_path / 'a.db').exists()


def test_unterminated_quote_is_rejected(tmp_path):
    (tmp_path / 'a.csv').write_text('Review\n"unterminated\n', encoding='utf-8')
    with pytest.raises(csv.Error):
        import_reviews(config(), tmp_path)


def test_database_write_failure_is_not_reported_as_success(tmp_path):
    (tmp_path / 'a.csv').write_text('Review\nbody\n', encoding='utf-8')
    first = import_reviews(config(), tmp_path)
    with connect(tmp_path / 'a.db') as db:
        db.execute('DELETE FROM reviews')
        db.execute('DELETE FROM dataset_versions')
        db.execute("CREATE TRIGGER deny_review BEFORE INSERT ON reviews BEGIN SELECT RAISE(ABORT,'injected persistence failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='persistence failure'):
        import_reviews(config(), tmp_path)
    with connect(tmp_path / 'a.db') as db:
        assert db.execute('SELECT count(*) FROM dataset_versions').fetchone()[0] == 0
        assert not filter_reviews(db, first['dataset_version'])
