import argparse
import json

from src.database.db import connect
from src.evaluation.runner import run
from src.settings import load_config


def main():
    parser=argparse.ArgumentParser(description='All-policy benchmark on the explicitly derived real-data pilot')
    parser.add_argument('--config',default='config/default.json')
    parser.add_argument('--mode',choices=['offline','live'],default='offline')
    parser.add_argument('--states',nargs='+',choices=['cold','warm'],default=['cold','warm'])
    parser.add_argument('--policies',nargs='+',choices=['P0','P1','P2','P3','P4','P5','P6'])
    parser.add_argument('--order',choices=['fixed','reverse','shuffled'],default='fixed')
    parser.add_argument('--repeat',type=int,default=0)
    parser.add_argument('--max-live-attempts',type=int,help='Lower the configured attempt budget for this invocation')
    args=parser.parse_args();config=load_config(args.config)
    if args.max_live_attempts is not None:
        if not 0 <= args.max_live_attempts <= config['experiment']['max_live_request_attempts']:
            parser.error('The override can only lower the configured live request budget')
        config['experiment']['max_live_request_attempts']=args.max_live_attempts
    with connect(config['experiment'].get('database',config['experiment'].get('pilot_database'))) as db:
        result=run(config,db,args.mode,args.states,args.policies,args.order,args.repeat)
    print(json.dumps([dict(policy=s['policy'],mode=s['mode'],cache_state=s['cache_state'],
                           actual_attempts=s['actual_llm_request_attempts'],
                           simulated_calls=s['simulated_llm_calls'],direct_hits=s['direct_hits'],
                           row_set_agreement=s['row_set_agreement']) for s in result],indent=2))


if __name__=='__main__':main()
