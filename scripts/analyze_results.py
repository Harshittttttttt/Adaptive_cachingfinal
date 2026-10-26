"""Read raw JSONL events, export denominator-aware tables and eight figures."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read_runs(directory):
    runs=[]
    for path in sorted(Path(directory).glob('*.jsonl'),key=lambda p:p.stat().st_mtime_ns):
        items=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        summaries=[r for r in items if r['kind']=='summary']
        if not summaries:continue  # Interrupted runs must never count as finished results.
        runs.append((items[0],summaries[-1],
                     [r for r in items if r['kind']=='event' and r['pass_kind']=='measure'],
                     [r for r in items if r['kind']=='query' and r['pass_kind']=='measure']))
    return runs


def write_csv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def analyze(directory='results/raw',root='results'):
    runs=read_runs(directory)
    if not runs:raise ValueError('No completed benchmark logs')
    tables=Path(root)/'tables';figures=Path(root)/'figures'
    tables.mkdir(parents=True,exist_ok=True);figures.mkdir(parents=True,exist_ok=True)
    write_csv(tables/'all_runs.csv',[s for _,s,_,_ in runs])
    # Main figures exclude development variants and alternate orders. Full table
    # preserves every executed configuration so negative results remain visible.
    main=[r for r in runs if r[1]['order']=='fixed' and r[1]['repeat']==0
          and r[0]['config']['policies']==json.loads(Path('config/default.json').read_text())['policies']]
    # If the command was repeated, display the most recent run per condition.
    unique={}
    for item in main:unique[(item[1]['mode'],item[1]['policy'],item[1]['cache_state'])]=item
    main=list(unique.values())
    write_csv(tables/'main_policy_comparison.csv',[s for _,s,_,_ in main])
    colors={f'P{i}':f'C{i}' for i in range(7)}
    def save(fig,name):
        fig.tight_layout();fig.savefig(figures/(name+'.png'),dpi=150);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(11,7))
    for ax,(mode,state) in zip(axes.flat,[('offline','cold'),('offline','warm'),('live','cold'),('live','warm')]):
        for _,s,_,_ in main:
            if s['mode']!=mode or s['cache_state']!=state or s['incorrect_reuse_rate'] is None:continue
            ax.scatter(s['cache_hit_rate'],s['incorrect_reuse_rate'],color=colors[s['policy']])
            ax.annotate(s['policy'],(s['cache_hit_rate'],s['incorrect_reuse_rate']),
                        xytext=(3,8+10*int(s['policy'][1:])),textcoords='offset points',fontsize=8,
                        arrowprops={'arrowstyle':'-','color':colors[s['policy']],'lw':.5})
        ax.set(xlabel='Direct hit rate',ylabel='Incorrect direct hits / all direct hits',
               title=mode+' '+state+' pilot; undefined rates omitted',ylim=(-.02,.15),xlim=(-.05,1.05))
    save(fig,'01_hit_rate_vs_incorrect_reuse')
    by_selectivity=[]
    for _,s,events,queries in main:
        groups=defaultdict(list)
        for event in events:groups[event['global_selectivity']].append(event)
        for selectivity,es in groups.items():
            direct=[e for e in es if e['decision']=='hit']
            calls=sum(e['llm_calls'] if s['mode']=='live' else e['details'].get('simulated_llm_calls',0) for e in es)
            cost_values=[r.get('estimated_cost_usd') for e in es for r in e['details'].get('requests',[])]
            by_selectivity.append(dict(policy=s['policy'],mode=s['mode'],cache_state=s['cache_state'],
                global_selectivity=selectivity,candidates=len(es),direct_hits=len(direct),
                incorrect_direct_hits=sum(not e['correct'] for e in direct),
                call_reduction=100*(len(es)-calls)/len(es),
                incorrect_reuse_rate=sum(not e['correct'] for e in direct)/len(direct) if direct else None,
                mean_candidate_seconds=sum(e['elapsed_seconds'] for e in es)/len(es),
                estimated_cost_usd=sum(cost_values) if cost_values and all(x is not None for x in cost_values)
                    else (0 if s['mode']=='live' and calls==0 else None)))
    write_csv(tables/'selectivity_groups.csv',by_selectivity)
    for number,metric,ylabel in [(2,'call_reduction','Call reduction (%) per observed candidate'),
                                (3,'incorrect_reuse_rate','Incorrect direct hits / all direct hits'),
                                (4,'mean_candidate_seconds','Mean candidate processing seconds'),
                                (5,'estimated_cost_usd','Measured-token estimated inference cost (USD)')]:
        fig,axes=plt.subplots(1,2,figsize=(11,4))
        for ax,mode in zip(axes,['offline','live']):
            for policy in colors:
                values=sorted([r for r in by_selectivity if r['policy']==policy and r['mode']==mode
                               and r['cache_state']=='cold' and r[metric] is not None],key=lambda r:r['global_selectivity'])
                if values:ax.plot([r['global_selectivity'] for r in values],[r[metric] for r in values],
                                  marker='o',label=policy,color=colors[policy])
            ax.set(xlabel='Global selectivity within 10-review cohort',ylabel=ylabel,title=mode+' cold pilot')
            if ax.lines:ax.legend(fontsize=7)
            else:ax.text(.5,.5,'No monetary estimate for offline replay',ha='center',transform=ax.transAxes)
        save(fig,f'{number:02d}_{metric}_vs_selectivity')
    fig,ax=plt.subplots(figsize=(9,4))
    for _,s,events,_ in main:
        if s['mode']!='offline' or s['cache_state']!='cold':continue
        hits=0;ys=[]
        for index,event in enumerate(events,1):
            hits+=event['decision']=='hit';ys.append(hits/index)
        ax.plot(range(1,len(ys)+1),ys,label=s['policy'],color=colors[s['policy']])
    ax.set(xlabel='Processed candidate sequence',ylabel='Cumulative direct hit rate',title='Offline cold pilot');ax.legend()
    save(fig,'06_sequence_performance')
    grouped=[]
    for _,s,events,queries in main:
        for group in sorted({q['group'] for q in queries}):
            qs=[q for q in queries if q['group']==group];es=[e for e in events if e['group']==group]
            grouped.append(dict(policy=s['policy'],mode=s['mode'],cache_state=s['cache_state'],group=group,
                                queries=len(qs),candidates=len(es),direct_hits=sum(e['decision']=='hit' for e in es),
                                row_set_agreement=sum(q['row_set_agreement'] for q in qs)/len(qs)))
    write_csv(tables/'query_groups.csv',grouped)
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    for ax,group in zip(axes,['broad','medium','narrow']):
        vals=[r for r in grouped if r['mode']=='offline' and r['cache_state']=='cold' and r['group']==group]
        ax.bar([r['policy'] for r in vals],[r['direct_hits']/r['candidates'] if r['candidates'] else 0 for r in vals])
        ax.set(title=group,xlabel='Policy',ylabel='Direct hit rate');ax.tick_params(axis='x',labelsize=7)
        if not any(r['candidates'] for r in vals):ax.text(.5,.5,'No candidates in this pilot',ha='center',transform=ax.transAxes)
    save(fig,'07_query_group_comparison')
    fig,ax=plt.subplots(figsize=(9,4))
    for offset,state in [(-.2,'cold'),(.2,'warm')]:
        vals={s['policy']:s['call_reduction_percent'] for _,s,_,_ in main if s['mode']=='offline' and s['cache_state']==state}
        ax.bar([i+offset for i in range(7)],[vals.get(f'P{i}',0) for i in range(7)],width=.4,label=state)
    ax.set(xticks=range(7),xticklabels=list(colors),ylabel='Simulated call reduction (%)',title='Offline cold/warm development pilot');ax.legend()
    save(fig,'08_cold_warm_policy_comparison')
    return dict(completed_runs=len(runs),main_conditions=len(main),figures=8)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--raw',default='results/raw')
    parser.add_argument('--output',default='results');args=parser.parse_args()
    print(json.dumps(analyze(args.raw,args.output),indent=2))


if __name__=='__main__':main()
