"""One command for all frozen held-out policies; no API calls in replay mode."""
import argparse
from pathlib import Path
from scripts.study import tune,test_suite,live_suite
from src.settings import load_config


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config/study.json')
    p.add_argument('--live',action='store_true',help='Issue live primary-comparison requests within the persistent budget')
    args=p.parse_args();config=load_config(args.config)
    if not Path('results/study/frozen_configuration.json').exists():tune(config)
    if args.live:live_suite(config)
    else:test_suite(config)


if __name__=='__main__':main()
