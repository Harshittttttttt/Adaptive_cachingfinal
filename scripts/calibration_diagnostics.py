"""Post-hoc offline calibration study; never changes the original freeze or calls an API."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scripts.analyze_results import read_runs, write_csv
from scripts.study import settings
from src.database.db import connect
from src.evaluation.runner import run
from src.settings import load_config
from src.evaluation.freeze import read_freeze

ROOT=Path('results/study')
OUT=ROOT/'calibration'

def compatible_runs(directory, config):
    """Reject stale or mixed experiments rather than silently resume wrong results."""
    runs=read_runs(directory)
    expected_config={k:config[k] for k in ['policies','llm','embedding','workload','semantic_prompt_version']}
    unique={}
    for r in runs:
        header,summary,events,queries=r
        actual={k:header['config'][k] for k in expected_config}
        if actual!=expected_config or header['mode']!='offline' or header['policy']!='P3':
            raise ValueError('Incompatible saved calibration run: '+summary['run_id'])
        manifest=json.loads(Path(config['experiment']['manifest']).read_text())
        if header['cohort_manifest']!=manifest or summary['order']!='fixed':
            raise ValueError('Calibration cohort or order changed')
        state,repeat=summary['cache_state'],summary['repeat']
        if state not in {'cold','warm'} or repeat not in range(3) or summary['seed']!=17+repeat:
            raise ValueError('Unexpected calibration state or seed')
        if summary['actual_llm_request_attempts'] or any(e['llm_calls'] for e in events):
            raise ValueError('Calibration evidence contains API requests')
        if len(queries)!=len(config['workload']):raise ValueError('Incomplete query coverage')
        unique[(state,repeat)]=r
    return list(unique.values())

def main():
    OUT.mkdir(exist_ok=True)
    frozen_bytes=(ROOT/'frozen_configuration.json').read_bytes()
    freeze=read_freeze(ROOT/'frozen_configuration.json');frozen=freeze['payload']
    main_runs=[r for r in read_runs(ROOT/'test/raw') if r[0]['config']['policies']==frozen['policy_settings'] and r[1]['order']=='fixed']
    main_runs=list({(r[1]['policy'],r[1]['cache_state'],r[1]['repeat']):r for r in main_runs}.values())
    validation=[r for r in read_runs(ROOT/'validation/raw') if r[1]['policy']=='P2' and r[0]['config']['policies']['uncertainty_gate']==.5]
    # One deterministic validation trajectory, no repeated weighting from warm passes.
    validation=[r for r in validation if r[1]['cache_state']=='cold'][-1:]
    vs=[e['similarity'] for r in validation for e in r[2] if e['details'].get('region')=='R3']
    lo,hi=map(float,np.quantile(vs,[.1,.9]))
    variants=[('constant_'+str(t),t,t) for t in [.92,.96,.98,.99,.995,1.0]]
    variants.append(('validation_q10_q90',lo,hi))
    plan=dict(status='exploratory post-hoc; original test already inspected; no new held-out claim',
        original_freeze_file_sha256=hashlib.sha256(frozen_bytes).hexdigest(),
        original_freeze_payload_sha256=freeze['sha256'],
        validation_run=validation[0][1]['run_id'],validation_r3_events=len(vs),
        quantiles=dict(q10=lo,q90=hi),variants=variants,seeds=[17,18,19],states=['cold','warm'],
        definition='Constant thresholds isolate score calibration; quantile range varies with global selectivity. All original posterior settings retained.')
    (OUT/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    base=load_config('config/study.json')
    for name,lower,upper in variants:
        directory=OUT/'raw'/name
        config=settings(base,'test',frozen['policy_settings'])
        config['policies'].update(tau_min=lower,tau_max=upper)
        config['logging']['directory']=str(directory)
        config['experiment']['scope']='posthoc-calibration'
        existing={(r[1]['cache_state'],r[1]['repeat']) for r in compatible_runs(directory,config)}
        with connect(config['experiment']['database']) as db:
            for repeat in range(3):
                states=tuple(s for s in ['cold','warm'] if (s,repeat) not in existing)
                if states:run(config,db,mode='offline',states=states,policies=['P3'],repeat=repeat)
        print('Completed offline calibration',name,flush=True)
    summaries=[]
    for name,lower,upper in variants:
        config=settings(base,'test',frozen['policy_settings']);config['policies'].update(tau_min=lower,tau_max=upper)
        runs=compatible_runs(OUT/'raw'/name,config)
        assert len(runs)==6
        for state in ['cold','warm']:
            rs=[r for r in runs if r[1]['cache_state']==state]
            row=dict(variant=name,state=state,tau_min=lower,tau_max=upper,seeds=len(rs))
            for field in ['simulated_llm_calls','incorrect_direct_hits','row_set_agreement','call_reduction_percent']:
                vals=[r[1][field] for r in rs]
                row[field+'_mean']=statistics.mean(vals);row[field+'_sd']=statistics.stdev(vals)
            vals=[sum(e['reason']=='selectivity_gate' for e in r[2]) for r in rs]
            row['forced_checks_mean']=statistics.mean(vals);row['forced_checks_sd']=statistics.stdev(vals)
            summaries.append(row)
    write_csv(ROOT/'tables/calibration_sweep.csv',summaries)
    groups=defaultdict(list)
    for r in main_runs:
        if r[1]['policy']!='P2':continue
        for e in r[2]:
            if e['details'].get('region')=='R3':
                for level,key in [('predicate',e['predicate_id']),('query_type',e['group'])]:
                    groups[(r[1]['cache_state'],level,key)].append(e['similarity'])
    distributions=[]
    for (state,level,key),values in groups.items():
        row=dict(state=state,level=level,group=key,events=len(values))
        row.update(dict(zip(['min','q10','q50','q90','max'],map(float,np.quantile(values,[0,.1,.5,.9,1])))))
        distributions.append(row)
    write_csv(ROOT/'tables/r3_similarity_distributions.csv',distributions)
    baseline=next(r for r in main_runs if r[1]['policy']=='P0' and r[1]['cache_state']=='cold' and r[1]['repeat']==0)
    denominator=[]
    for q in baseline[3]:
        es=[e for e in baseline[2] if e['query_id']==q['query_id']]
        counts={p:sum(e['predicate_id']==p for e in es) for p in ['shipping','defect','sarcasm']}
        denominator.append(dict(query=q['query_id'],**counts,total=len(es)))
    assert sum(r['total'] for r in denominator)==581
    write_csv(ROOT/'tables/baseline_581.csv',denominator)
    fig,axes=plt.subplots(1,2,figsize=(10,3.6))
    for state in ['cold','warm']:
        rs=[r for r in summaries if r['state']==state and r['variant'].startswith('constant')]
        axes[0].errorbar([r['tau_min'] for r in rs],[r['forced_checks_mean'] for r in rs],yerr=[r['forced_checks_sd'] for r in rs],marker='o',label=state)
        axes[1].errorbar([r['simulated_llm_calls_mean'] for r in rs],[r['incorrect_direct_hits_mean'] for r in rs],xerr=[r['simulated_llm_calls_sd'] for r in rs],yerr=[r['incorrect_direct_hits_sd'] for r in rs],marker='o',label=state)
    axes[0].set(xlabel='Constant R3 threshold',ylabel='Forced checks (mean ± SD)')
    axes[1].set(xlabel='Simulated inference calls',ylabel='Incorrect direct hits')
    for ax in axes:ax.legend()
    fig.suptitle('Exploratory calibration on the existing 96-review test cohort')
    fig.tight_layout();fig.savefig(ROOT/'figures/09_calibration_sweep.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,3.6))
    for (state,level,key),values in groups.items():
        if state=='cold' and level=='predicate':
            v=sorted(values);ax.step(v,np.arange(1,len(v)+1)/len(v),label=key)
    ax.axvline(.92,color='black',linestyle='--',label='Original ceiling .92')
    ax.set(xlabel='R3 candidate similarity',ylabel='Empirical cumulative fraction',title='Cold P2 trajectories pooled over three seeds (dependent events)')
    ax.legend();fig.tight_layout();fig.savefig(ROOT/'figures/10_r3_similarity.png',dpi=160);plt.close(fig)
    evidence=dict(plan=plan,sweep=summaries,distributions=distributions,baseline=denominator,
        new_runs=42,new_query_executions=504,new_unique_reviews=0,api_attempts=0,
        conclusion='Activation establishes an intervention, not a selectivity advantage over a calibrated constant threshold.')
    (OUT/'analysis.json').write_text(json.dumps(evidence,indent=2)+'\n')
    assert (ROOT/'frozen_configuration.json').read_bytes()==frozen_bytes
    # Independent checks of the published mechanism and raw-log aggregates.
    original={(r[1]['cache_state'],r[1]['repeat']):r for r in main_runs if r[1]['policy']=='P2'}
    for r in read_runs(OUT/'raw/constant_0.92'):
        prior=original[(r[1]['cache_state'],r[1]['repeat'])]
        for metric in ['simulated_llm_calls','incorrect_direct_hits','row_set_agreement']:
            assert r[1][metric]==prior[1][metric]
        signature=lambda e:(e['query_id'],e['review_id'],e['predicate_id'],e['decision'],e['reason'],e['label'],e['similarity'])
        assert list(map(signature,r[2]))==list(map(signature,prior[2]))
    assert all(d['min']>.92 for d in distributions)
    assert any(r['forced_checks_mean']>0 for r in summaries if r['variant']=='validation_q10_q90')
    for name,_,_ in variants:
        for _,s,events,queries in read_runs(OUT/'raw'/name):
            assert s['simulated_llm_calls']==sum(e['details'].get('simulated_llm_calls',0) for e in events)
            assert s['incorrect_direct_hits']==sum(e['decision']=='hit' and not e['correct'] for e in events)
            assert s['row_set_agreement']==sum(q['row_set_agreement'] for q in queries)/len(queries)
    audit=dict(completed_runs=42,measured_query_executions=504,api_attempts=0,original_freeze_unchanged=True,
        frozen_threshold_event_signatures_match_p2=True,r3_scores_above_original_ceiling=True,
        active_quantile_intervention=True,raw_aggregates_verified=True,
        original_freeze_file_sha256=hashlib.sha256(frozen_bytes).hexdigest(),original_freeze_payload_sha256=freeze['sha256'])
    (OUT/'verification.json').write_text(json.dumps(audit,indent=2)+'\n')

if __name__=='__main__':main()
