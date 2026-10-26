"""Development ablations only. Never select final parameters on this pilot."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from src.database.db import connect
from src.evaluation.runner import run
from src.settings import load_config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config/default.json')
    args=parser.parse_args();config=load_config(args.config)
    variants=[('global',{}),('stage',{'selectivity_kind':'stage'}),
              ('lower_min',{'tau_min':.68}),('higher_max',{'tau_max':.95}),
              ('gamma_half',{'gamma':.5}),('gamma_two',{'gamma':2}),
              ('more_posterior_audits',{'uncertainty_gate':.5}),
              ('more_selectivity_audits',{'audit_max':.8})]
    results=[]
    with connect(config['experiment']['pilot_database']) as db:
        for name,settings in variants:
            variant=deepcopy(config);variant['policies'].update(settings)
            # Run P2 alongside the three proposed integrations for every setting.
            values=run(variant,db,policies=['P2','P3','P4','P5'])
            for result in values:result['ablation']=name
            results.extend(values)
        for order in ['reverse','shuffled']:
            values=run(config,db,order=order)
            for result in values:result['ablation']='order_'+order
            results.extend(values)
        values=run(config,db,repeat=1)
        for result in values:result['ablation']='repeat_seed18'
        results.extend(values)
    path=Path(config['logging']['directory'])/'development_ablations.json'
    path.write_text(json.dumps(dict(purpose='development diagnostics; no final parameter selection',runs=results),indent=2)+'\n',encoding='utf-8')
    print('Saved',len(results),'development runs to',path)


if __name__=='__main__':main()
