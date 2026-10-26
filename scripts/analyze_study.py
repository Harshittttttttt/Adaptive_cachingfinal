"""Held-out tables, paired seed variability and figures from immutable raw logs."""
from collections import defaultdict
import csv
import json
from pathlib import Path
import random
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from scripts.analyze_results import read_runs
from src.evaluation.freeze import read_freeze

ROOT=Path('results/study')


def csv_write(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=keys);writer.writeheader();writer.writerows(rows)


def analyze():
    frozen=read_freeze(ROOT/'frozen_configuration.json')
    chosen=frozen['payload']['policy_settings']
    runs=read_runs(ROOT/'test/raw')
    main=[r for r in runs if r[0]['config']['policies']==chosen and r[1]['order']=='fixed']
    # Keep the last completed invocation for each predeclared condition.
    unique={}
    for item in main:unique[(item[1]['policy'],item[1]['cache_state'],item[1]['repeat'])]=item
    main=list(unique.values())
    if not main:raise ValueError('No completed held-out main runs')
    tables=ROOT/'tables';figures=ROOT/'figures'
    tables.mkdir(parents=True,exist_ok=True);figures.mkdir(parents=True,exist_ok=True)
    csv_write(tables/'all_heldout_runs.csv',[r[1] for r in runs])
    csv_write(tables/'main_runs.csv',[r[1] for r in main])
    validation_rows=[]
    for trial in frozen['payload']['trials']:
        outcomes=trial['runs'];hits=sum(s['direct_hits'] for s in outcomes);errors=sum(s['incorrect_direct_hits'] for s in outcomes)
        validation_rows.append(dict(policy=trial['policy'],settings=json.dumps(trial['settings'],sort_keys=True),
            feasible=not trial['objective'][0],combined_calls=sum(s['simulated_llm_calls'] for s in outcomes),
            incorrect_direct_hits=errors,direct_hit_denominator=hits,
            incorrect_reuse_rate=errors/hits if hits else None,
            mean_row_set_agreement=statistics.mean(s['row_set_agreement'] for s in outcomes)))
    csv_write(tables/'validation_trials.csv',validation_rows)
    means=[]
    groups=defaultdict(list)
    for item in main:groups[(item[1]['policy'],item[1]['cache_state'])].append(item[1])
    for (policy,state),values in sorted(groups.items()):
        row=dict(policy=policy,cache_state=state,seeds=len(values))
        for key in ['simulated_llm_calls','simulated_audit_calls','direct_hits','incorrect_direct_hits',
                    'cache_hit_rate','incorrect_reuse_rate','row_set_agreement','call_reduction_percent',
                    'incorrectly_included_rows','incorrectly_excluded_rows','total_query_seconds',
                    'embedding_seconds','search_seconds','policy_seconds','median_query_seconds','p95_query_seconds']:
            nums=[v[key] for v in values if v.get(key) is not None]
            row[key+'_mean']=statistics.mean(nums) if nums else None
            row[key+'_stdev']=statistics.stdev(nums) if len(nums)>1 else None
        row['candidate_counts']='/'.join(str(v['candidates']) for v in values)
        row['hit_denominators']='/'.join(str(v['direct_hits']) for v in values)
        means.append(row)
    csv_write(tables/'policy_means.csv',means)
    paired=[]
    for state in ['cold','warm']:
        a={r[1]['repeat']:r[1] for r in main if r[1]['policy']=='P2' and r[1]['cache_state']==state}
        b={r[1]['repeat']:r[1] for r in main if r[1]['policy']=='P3' and r[1]['cache_state']==state}
        for repeat in sorted(set(a)&set(b)):
            paired.append(dict(cache_state=state,repeat=repeat,
                call_difference_p3_minus_p2=b[repeat]['simulated_llm_calls']-a[repeat]['simulated_llm_calls'],
                incorrect_hit_difference_p3_minus_p2=b[repeat]['incorrect_direct_hits']-a[repeat]['incorrect_direct_hits'],
                row_agreement_difference_p3_minus_p2=b[repeat]['row_set_agreement']-a[repeat]['row_set_agreement']))
    csv_write(tables/'paired_p2_p3.csv',paired)
    intervals=[]
    for state in ['cold','warm']:
        for key in ['call_difference_p3_minus_p2','incorrect_hit_difference_p3_minus_p2','row_agreement_difference_p3_minus_p2']:
            values=[r[key] for r in paired if r['cache_state']==state]
            if not values:continue
            rng=random.Random(2252)
            boot=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(5000))
            intervals.append(dict(cache_state=state,metric=key,paired_seeds=len(values),
                                  mean=statistics.mean(values),bootstrap_low=boot[125],bootstrap_high=boot[4874],
                                  interpretation='Conditional seed variability only; same corpus, not independent population evidence'))
    csv_write(tables/'paired_seed_intervals.csv',intervals)
    diagnostics=[]
    live=read_runs(ROOT/'live/raw')
    live_unique={}
    for r in live:live_unique[(r[1]['policy'],r[1]['cache_state'])]=r
    live=list(live_unique.values())
    csv_write(tables/'live_runs.csv',[r[1] for r in live])
    def save(fig,name):
        fig.tight_layout();fig.savefig(figures/(name+'.png'),dpi=160);plt.close(fig)
    colors={f'P{i}':f'C{i}' for i in range(7)}
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for ax,state in zip(axes,['cold','warm']):
        identical=defaultdict(list)
        for row in means:
            if row['cache_state']!=state or row['incorrect_reuse_rate_mean'] is None:continue
            x=row['cache_hit_rate_mean'];y=row['incorrect_reuse_rate_mean']
            identical[(round(x,10),round(y,10))].append(row['policy'])
        for (x,y),policies in identical.items():
            ax.scatter(x,y,color=colors[policies[0]])
            ax.annotate('/'.join(policies),(x,y),xytext=(-5 if x>.85 else 5,7),textcoords='offset points',
                        ha='right' if x>.85 else 'left',fontsize=9)
        ax.set(title=state+' held-out replay (3 seeds)',xlabel='Direct hit rate',ylabel='Incorrect direct hits / all direct hits')
    fig.suptitle('Undefined reuse rates omitted; identical policy points share a label',fontsize=10)
    save(fig,'01_reuse_tradeoff')
    baseline={}
    for _,s,events,queries in main:
        if s['policy']=='P0' and s['repeat']==0:
            for q in queries:baseline[(s['cache_state'],q['query_id'])]=sum(e['details'].get('simulated_llm_calls',0) for e in events if e['query_id']==q['query_id'])
    for _,s,events,queries in main+live:
        if s['mode']=='offline' and s['repeat']!=0:continue
        for q in queries:
            es=[e for e in events if e['query_id']==q['query_id']]
            sql=[x for x in q['stages'] if x['kind']=='sql'][-1]
            direct=[e for e in es if e['decision']=='hit']
            calls=sum(e['llm_calls'] if s['mode']=='live' else e['details'].get('simulated_llm_calls',0) for e in es)
            denominator=baseline.get((s['cache_state'],q['query_id']),0)
            costs=[r.get('estimated_cost_usd') for e in es for r in e['details'].get('requests',[])]
            diagnostics.append(dict(policy=s['policy'],mode=s['mode'],cache_state=s['cache_state'],query_id=q['query_id'],
                group=q['group'],sql_selectivity=sql['global_selectivity'],sql_candidates=sql['remaining_rows'],
                inference_calls=calls,baseline_calls=denominator,
                call_reduction_percent=100*(denominator-calls)/denominator if denominator else None,
                direct_hits=len(direct),incorrect_direct_hits=sum(not e['correct'] for e in direct),
                incorrect_reuse_rate=sum(not e['correct'] for e in direct)/len(direct) if direct else None,
                query_seconds=q['elapsed_seconds'],
                estimated_cost_usd=sum(costs) if costs and all(c is not None for c in costs)
                    else (0 if s['mode']=='live' and calls==0 else None),
                row_set_agreement=q['row_set_agreement']))
    csv_write(tables/'query_metrics.csv',diagnostics)
    for number,key,label,mode in [(2,'call_reduction_percent','Call reduction vs same-query P0 (%)','offline'),
                                  (3,'incorrect_reuse_rate','Incorrect direct hits / all direct hits','offline'),
                                  (4,'query_seconds','Query execution seconds (precomputed embeddings)','live'),
                                  (5,'estimated_cost_usd','Estimated live inference cost (USD)','live')]:
        fig,axes=plt.subplots(1,2,figsize=(11,4))
        for ax,state in zip(axes,['cold','warm']):
            for policy in colors:
                values=sorted([r for r in diagnostics if r['policy']==policy and r['mode']==mode and r['cache_state']==state
                               and r[key] is not None and r['sql_candidates']>0],key=lambda r:r['sql_selectivity'])
                if values:
                    marker={'P2':'o','P3':'x','P4':'+'}.get(policy,'o')
                    ax.scatter([v['sql_selectivity'] for v in values],[v[key] for v in values],label=policy,
                               color=colors[policy],alpha=.75,marker=marker)
            ax.set(title=f'{mode} {state}',xlabel='SQL selectivity before semantic stages',ylabel=label)
            if ax.collections:ax.legend(fontsize=8)
        save(fig,f'{number:02d}_{key}_vs_selectivity')
    fig,ax=plt.subplots(figsize=(9,4))
    for _,s,events,_ in main:
        if s['repeat'] or s['cache_state']!='cold':continue
        hits=0;values=[]
        for i,e in enumerate(events,1):hits+=e['decision']=='hit';values.append(hits/i)
        ax.plot(range(1,len(values)+1),values,label=s['policy'],color=colors[s['policy']])
    ax.set(xlabel='Processed semantic candidates',ylabel='Cumulative direct hit rate',title='Held-out changing/repeated workload');ax.legend(ncol=4)
    save(fig,'06_sequence')
    grouped=[]
    for state in ['cold','warm']:
        for policy in colors:
            for group in ['broad','medium','narrow','empty','repeat','multi']:
                rows=[r for r in diagnostics if r['mode']=='offline' and r['cache_state']==state and r['policy']==policy and r['group']==group]
                denom=sum(r['baseline_calls'] for r in rows);calls=sum(r['inference_calls'] for r in rows)
                grouped.append(dict(policy=policy,cache_state=state,group=group,baseline_calls=denom,inference_calls=calls,
                                    call_reduction_percent=100*(denom-calls)/denom if denom else None))
    csv_write(tables/'query_groups.csv',grouped)
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    for ax,group in zip(axes,['broad','medium','narrow']):
        rows=[r for r in grouped if r['cache_state']=='cold' and r['group']==group]
        ax.bar([r['policy'] for r in rows],[r['call_reduction_percent'] or 0 for r in rows],color=[colors[r['policy']] for r in rows])
        ax.set(title=group,xlabel='Policy',ylabel='Call reduction (%)')
    save(fig,'07_query_groups')
    fig,ax=plt.subplots(figsize=(9,4))
    for offset,state in [(-.2,'cold'),(.2,'warm')]:
        rows={r['policy']:r for r in means if r['cache_state']==state}
        ax.bar([i+offset for i in range(7)],[rows[f'P{i}']['call_reduction_percent_mean'] for i in range(7)],
               width=.4,label=state,yerr=[rows[f'P{i}']['call_reduction_percent_stdev'] or 0 for i in range(7)],capsize=2)
    ax.set(xticks=range(7),xticklabels=list(colors),ylabel='Call reduction (%)',title='Held-out replay: mean and stdev over 3 sampling seeds');ax.legend()
    save(fig,'08_cold_warm')
    summary=dict(freeze_sha256=frozen['sha256'],heldout_main_runs=len(main),all_heldout_completed_runs=len(runs),
                 live_completed_runs=len(live),policy_means=means,paired_intervals=intervals,
                 forced_checks={s['run_id']:sum(e['reason']=='selectivity_gate' for e in events)
                                for _,s,events,_ in main if s['policy']=='P3'},figures=8)
    (ROOT/'analysis.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return summary


if __name__=='__main__':
    result=analyze();print(json.dumps({k:v for k,v in result.items() if k not in ['policy_means','paired_intervals','forced_checks']},indent=2))
