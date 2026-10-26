import argparse
import json
from src.evaluation.cohorts import prepare
from src.settings import load_config


def main():
    p=argparse.ArgumentParser(description='Prepare real, disjoint validation/test challenge cohorts without API calls')
    p.add_argument('--config',default='config/default.json')
    args=p.parse_args()
    print(json.dumps(prepare(load_config(args.config)),indent=2))


if __name__=='__main__':main()
