import pytest

from src.evaluation.metrics import percentile, summarize


def event(label,reference,decision='hit',calls=0,simulated=0):
    return dict(label=label,reference_label=reference,decision=decision,llm_calls=calls,
                audit_calls=0,elapsed_seconds=.1,timings={},details={'simulated_llm_calls':simulated})


def test_denominators_undefined_rates_and_offline_calls():
    empty=summarize([],[],0,'offline')
    assert empty['incorrect_reuse_rate'] is None and empty['cache_hit_rate'] is None
    assert empty['call_reduction_percent'] is None
    events=[event('YES','YES'),event('YES','NO'),event('NO','YES'),event('NO','NO','miss',0,1)]
    summary=summarize(events,[],4,'offline')
    assert summary['direct_hits']==3
    assert summary['incorrect_reuse_rate']==2/3
    assert summary['correct_reuse_precision']==1/3
    assert summary['cache_false_positives']==summary['cache_false_negatives']==1
    assert summary['actual_llm_request_attempts']==0 and summary['simulated_llm_calls']==1
    assert summary['call_reduction_percent']==75
    assert summary['estimated_inference_cost_usd'] is None


def test_live_audits_are_not_hits_and_query_set_errors():
    events=[event('NO','NO','audit',2)]
    events[0]['audit_calls']=2
    events[0]['details']['requests']=[{'estimated_cost_usd':.01},{'estimated_cost_usd':.02}]
    outputs=[dict(elapsed_seconds=1,row_set_agreement=False,incorrectly_included=['a'],incorrectly_excluded=['b'])]
    summary=summarize(events,outputs,3,'live')
    assert summary['direct_hits']==0 and summary['incorrect_reuse_rate'] is None
    assert summary['actual_llm_request_attempts']==summary['actual_audit_attempts']==2
    assert summary['actual_ordinary_miss_attempts']==0
    assert summary['row_set_agreement']==0
    assert summary['incorrectly_included_rows']==summary['incorrectly_excluded_rows']==1
    assert summary['estimated_inference_cost_usd']==pytest.approx(.03)
    assert summary['call_reduction_percent']==pytest.approx(100/3)


def test_percentile_interpolation():
    assert percentile([0,10],.95)==9.5
    assert percentile([], .95) is None
