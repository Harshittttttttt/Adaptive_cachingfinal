import json
from pathlib import Path

import pytest

from src.evaluation.cohorts import select,text_key
from src.evaluation.freeze import read_freeze,write_freeze
from scripts.study import objective


def rows():
    return [dict(review_id=str(i),review_text=f'Realistic fixture review body number {i} about a product.',
                 rating=i%5+1,price=50 if i%2 else 25000) for i in range(400)]


def test_text_disjoint_selection_deterministic_and_no_source_mutation():
    source=rows();original=json.dumps(source)
    selected,diagnostics=select(source,{'validation':16,'test':24})
    again,_=select(source,{'validation':16,'test':24})
    assert selected==again and json.dumps(source)==original
    assert [len(selected[k]) for k in ['validation','test']]==[16,24]
    assert not ({text_key(r['review_text']) for r in selected['validation']} &
                {text_key(r['review_text']) for r in selected['test']})
    assert sum(diagnostics['test']['selected'].values())==24


def test_duplicate_bodies_and_excluded_pilot_texts_cannot_leak():
    source=rows();source.extend([{**r,'review_id':'copy'+r['review_id']} for r in source[:20]])
    excluded={text_key(source[0]['review_text'])}
    selected,_=select(source,{'validation':16,'test':24},excluded_texts=excluded)
    keys=[text_key(r['review_text']) for rs in selected.values() for r in rs]
    assert len(keys)==len(set(keys)) and not excluded & set(keys)


def test_freeze_rejects_test_selection_and_tampering(tmp_path):
    p=tmp_path/'frozen.json'
    with pytest.raises(ValueError):write_freeze(p,{'selection_split':'test'})
    doc=write_freeze(p,{'selection_split':'validation','tau':.9})
    assert read_freeze(p)==doc
    doc['payload']['tau']=.1;p.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='modified'):read_freeze(p)


def test_validation_objective_accounts_for_errors_and_calls():
    def summary(calls,errors,hits,agreement=1):
        return {'simulated_llm_calls':calls,'incorrect_direct_hits':errors,'direct_hits':hits,'row_set_agreement':agreement}
    assert objective([summary(50,0,100)]) < objective([summary(20,10,100)])
    assert objective([summary(20,0,100)]) < objective([summary(50,0,100)])
