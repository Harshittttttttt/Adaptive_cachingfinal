"""Compare already executed repeated configurations, ignoring timing and run IDs."""
import json
from collections import defaultdict
from pathlib import Path

from scripts.analyze_results import read_runs
from src.settings import load_config


def main():
    config=load_config();groups=defaultdict(list)
    for header,summary,events,queries in read_runs(config['logging']['directory']):
        if (summary['mode']!='offline' or summary['order']!='fixed' or summary['repeat']!=0
                or header['config']['policies']!=config['policies']):continue
        signature=dict(events=[(e['query_id'],e['review_id'],e['predicate_id'],e['decision'],e['reason'],
                                e['label'],e['details'].get('simulated_llm_calls',0)) for e in events],
                       outputs=[(q['query_id'],q['row_ids']) for q in queries])
        groups[(summary['policy'],summary['cache_state'])].append(signature)
    checks=[]
    for (policy,state),values in groups.items():
        if len(values)<2:continue
        matches=all(v==values[0] for v in values[1:])
        checks.append(dict(policy=policy,cache_state=state,executed_repeats=len(values),decisions_and_outputs_match=matches))
        if not matches:raise AssertionError('Deterministic replay mismatch')
    if not checks:raise ValueError('No repeated configurations to verify')
    output=Path(config['logging']['directory'])/'replay_reproducibility.json'
    output.write_text(json.dumps(checks,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(checks,indent=2))


if __name__=='__main__':main()
