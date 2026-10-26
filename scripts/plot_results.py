"""Generate the held-out study's tables and figures."""
from scripts.analyze_study import analyze
if __name__=='__main__':
    result=analyze();print('Generated',result['figures'],'figures and held-out tables')
