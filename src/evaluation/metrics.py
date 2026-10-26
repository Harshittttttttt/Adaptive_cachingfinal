import math
import statistics


def percentile(values,q):
    if not values:return None
    values=sorted(values);position=(len(values)-1)*q
    lo=math.floor(position);hi=math.ceil(position)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def summarize(events,outputs,baseline_calls,mode):
    direct=[e for e in events if e['decision']=='hit']
    incorrect=sum(e['label']!=e['reference_label'] for e in direct)
    actual=sum(e['llm_calls'] for e in events)
    simulated=sum(e.get('details',{}).get('simulated_llm_calls',0) for e in events)
    calls=actual if mode=='live' else simulated
    times=[o['elapsed_seconds'] for o in outputs]
    costs=[r.get('estimated_cost_usd') for e in events for r in e.get('details',{}).get('requests',[])]
    return dict(candidates=len(events),direct_hits=len(direct),incorrect_direct_hits=incorrect,
                correct_direct_hits=len(direct)-incorrect,cache_hit_rate=len(direct)/len(events) if events else None,
                incorrect_reuse_rate=incorrect/len(direct) if direct else None,
                correct_reuse_precision=(len(direct)-incorrect)/len(direct) if direct else None,
                actual_llm_request_attempts=actual,simulated_llm_calls=simulated,
                actual_audit_attempts=sum(e['audit_calls'] for e in events),
                simulated_audit_calls=sum(e.get('details',{}).get('simulated_audit_calls',0) for e in events),
                actual_ordinary_miss_attempts=actual-sum(e['audit_calls'] for e in events),
                misses=sum(e['decision']!='hit' for e in events),
                call_reduction_percent=100*(baseline_calls-calls)/baseline_calls if baseline_calls else None,
                baseline_call_denominator=baseline_calls,
                cache_false_positives=sum(e['label']=='YES' and e['reference_label']=='NO' for e in direct),
                cache_false_negatives=sum(e['label']=='NO' and e['reference_label']=='YES' for e in direct),
                row_set_agreement=sum(o['row_set_agreement'] for o in outputs)/len(outputs) if outputs else None,
                incorrectly_included_rows=sum(len(o['incorrectly_included']) for o in outputs),
                incorrectly_excluded_rows=sum(len(o['incorrectly_excluded']) for o in outputs),
                total_query_seconds=sum(times),median_query_seconds=statistics.median(times) if times else None,
                p95_query_seconds=percentile(times,.95),
                median_candidate_seconds=statistics.median([e['elapsed_seconds'] for e in events]) if events else None,
                p95_candidate_seconds=percentile([e['elapsed_seconds'] for e in events],.95),
                estimated_inference_cost_usd=(sum(costs) if costs and all(c is not None for c in costs)
                                               else (0 if mode=='live' and actual==0 else None)),
                embedding_seconds=sum(e.get('timings',{}).get('embedding_seconds',0) for e in events),
                search_seconds=sum(e.get('timings',{}).get('search_seconds',0) for e in events),
                policy_seconds=sum(e.get('timings',{}).get('policy_seconds',0) for e in events),
                llm_seconds=sum(e.get('timings',{}).get('llm_seconds',0) for e in events))
