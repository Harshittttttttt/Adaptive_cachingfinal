"""Validation-only parameter selection and frozen held-out experiment suite."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from src.database.db import connect
from src.evaluation.freeze import fingerprint,read_freeze,write_freeze
from src.evaluation.runner import run
from src.settings import load_config

ROOT=Path('results/study')
DATA=Path('data/processed/study')


def settings(base,split,policy_settings=None):
    config=deepcopy(base)
    config['experiment'].update(database=str(DATA/(split+'.sqlite3')),manifest=str(DATA/(split+'_manifest.json')),
                                scope='challenge-study',max_live_request_attempts=3000)
    config['logging']['directory']=str(ROOT/split/'raw')
    if policy_settings:config['policies'].update(policy_settings)
    return config


def objective(summaries):
    hits=sum(s['direct_hits'] for s in summaries)
    errors=sum(s['incorrect_direct_hits'] for s in summaries)
    row_agreement=sum(s['row_set_agreement'] for s in summaries)/len(summaries)
    risk=errors/hits if hits else 0  # zero-hit feasibility is vacuous, not precision evidence.
    calls=sum(s['simulated_llm_calls'] for s in summaries)
    feasible=risk<=.02 and row_agreement>=.90
    return (not feasible,calls if feasible else errors,
            errors if feasible else calls,-row_agreement)


def tune(base):
    ROOT.mkdir(parents=True,exist_ok=True)
    trials=[]
    def trial(policy,changes):
        config=settings(base,'validation',changes)
        with connect(config['experiment']['database']) as db:
            outcomes=run(config,db,policies=[policy])
        result=dict(policy=policy,settings=changes,objective=objective(outcomes),runs=outcomes)
        trials.append(result)
        return result
    base_trials=[trial('P2',{'uncertainty_gate':ug}) for ug in [.5,1.0]]
    selected_base=min(base_trials,key=lambda t:t['objective'])['settings']
    gate_choices=[dict(tau_min=.72,tau_max=.92,gamma=1),dict(tau_min=.72,tau_max=.96,gamma=1),
                  dict(tau_min=.8,tau_max=.96,gamma=2),dict(tau_min=.72,tau_max=.98,gamma=.5)]
    gates=[trial('P3',{**selected_base,**choice}) for choice in gate_choices]
    selected_gate=min(gates,key=lambda t:t['objective'])['settings']
    statics=[trial('P1',{'fixed_threshold':threshold}) for threshold in [.72,.82,.92,.96]]
    selected_static=min(statics,key=lambda t:t['objective'])['settings']
    policies={**base['policies'],**selected_base,**selected_gate,**selected_static}
    validation=json.loads((DATA/'validation_manifest.json').read_text())
    test=json.loads((DATA/'test_manifest.json').read_text())
    if set(validation['text_group_hashes'])&set(test['text_group_hashes']):raise ValueError('Split leakage')
    payload=dict(selection_split='validation',validation_version=validation['dataset_version'],
                 test_version=test['dataset_version'],policy_settings=policies,
                 llm=base['llm'],embedding=base['embedding'],workload=base['workload'],
                 semantic_prompt_version=base.get('semantic_prompt_version','v1'),
                 selection_objective='Risk <=2% and query set agreement >=90%; then fewest combined cold/warm simulated calls. If infeasible, fewest incorrect direct hits, then calls.',
                 trials=trials)
    frozen=write_freeze(ROOT/'frozen_configuration.json',payload)
    (ROOT/'validation_selection.json').write_text(json.dumps(trials,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'frozen_sha256':frozen['sha256'],'selected_policies':policies},indent=2))
    return frozen


def test_suite(base,full=True):
    frozen=read_freeze(ROOT/'frozen_configuration.json');payload=frozen['payload']
    if any(fingerprint(base[k])!=fingerprint(payload[k]) for k in ['llm','embedding','workload']):
        raise ValueError('Model or workload changed after freezing')
    if base.get('semantic_prompt_version','v1')!=payload['semantic_prompt_version']:
        raise ValueError('Prompt version changed after freezing')
    config=settings(base,'test',payload['policy_settings'])
    if json.loads((DATA/'test_manifest.json').read_text())['dataset_version']!=payload['test_version']:
        raise ValueError('Test cohort changed after freezing')
    outputs=[]
    with connect(config['experiment']['database']) as db:
        for repeat in range(3 if full else 1):
            outputs.extend(run(config,db,repeat=repeat))
            print('Completed held-out fixed-order seed',17+repeat,flush=True)
        if full:
            for order in ['reverse','shuffled']:
                outputs.extend(run(config,db,order=order))
                print('Completed held-out order',order,flush=True)
            # One-factor ablations use predeclared settings, never select a new winner.
            variants=[('stage_selectivity',{'selectivity_kind':'stage'}),
                      ('lower_max',{'tau_max':max(payload['policy_settings']['tau_min'],.90)}),
                      ('gamma_two',{'gamma':2}),('stronger_sampling',{'uncertainty_gate':.25}),
                      ('stronger_audit',{'audit_max':.8})]
            for name,changes in variants:
                variant=deepcopy(config);variant['policies'].update(changes)
                values=run(variant,db,policies=['P2','P3','P4','P5'])
                for value in values:value['ablation']=name
                outputs.extend(values)
                print('Completed held-out ablation',name,flush=True)
    (ROOT/'heldout_runs.json').write_text(json.dumps({'freeze_sha256':frozen['sha256'],'runs':outputs},indent=2)+'\n',encoding='utf-8')
    return outputs


def live_suite(base):
    from concurrent.futures import ThreadPoolExecutor,as_completed
    frozen=read_freeze(ROOT/'frozen_configuration.json');payload=frozen['payload']
    if any(fingerprint(base[k])!=fingerprint(payload[k]) for k in ['llm','embedding','workload']):
        raise ValueError('Model or workload changed after freezing')
    if base.get('semantic_prompt_version','v1')!=payload['semantic_prompt_version']:
        raise ValueError('Prompt version changed after freezing')
    if json.loads((DATA/'test_manifest.json').read_text())['dataset_version']!=payload['test_version']:
        raise ValueError('Test cohort changed after freezing')
    config=settings(base,'test',payload['policy_settings'])
    config['experiment']['budget_ledger']=str(ROOT/'live_runtime_budget.json')
    config['experiment']['concurrent_condition_workers']=3
    config['logging']['directory']=str(ROOT/'live'/'raw')
    def condition(item):
        policy,state=item
        with connect(config['experiment']['database']) as db:
            result=run(config,db,mode='live',states=(state,),policies=[policy])
        print('Completed held-out live',policy,state,flush=True)
        return result
    outputs=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(condition,item) for item in [('P0','cold'),('P2','cold'),('P3','cold'),('P2','warm'),('P3','warm')]]
        for future in as_completed(futures):outputs.extend(future.result())
    (ROOT/'live_runs.json').write_text(json.dumps({'freeze_sha256':frozen['sha256'],'runs':outputs},indent=2)+'\n',encoding='utf-8')
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['tune','test','live','all'])
    parser.add_argument('--config',default='config/default.json')
    parser.add_argument('--quick',action='store_true',help='One fixed-order test repeat only')
    args=parser.parse_args();base=load_config(args.config)
    if args.stage in ('tune','all'):tune(base)
    if args.stage in ('test','all'):test_suite(base,not args.quick)
    if args.stage=='live':live_suite(base)


if __name__=='__main__':main()
