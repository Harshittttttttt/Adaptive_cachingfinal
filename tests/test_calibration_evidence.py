"""A resumed exploratory study must not silently mix incompatible evidence."""
import copy
import json
import pytest
from scripts.calibration_diagnostics import compatible_runs


def test_resume_rejects_changed_workload_and_live_calls(tmp_path):
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'dataset_version':'test-v2'}))
    config=dict(policies={'tau_min':.99},llm={'model':'model-a'},embedding={'model':'embed-a'},
                workload=[{'query_id':'q'}],semantic_prompt_version='v2',experiment={'manifest':str(manifest)})
    header=dict(kind='run',mode='offline',policy='P3',config=config,cohort_manifest={'dataset_version':'test-v2'})
    summary=dict(kind='summary',run_id='saved',order='fixed',cache_state='cold',repeat=0,seed=17,actual_llm_request_attempts=0)
    rows=[header,dict(kind='query',query_id='q',pass_kind='measure'),summary]
    def save():
        (tmp_path/'run.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    save();assert len(compatible_runs(tmp_path,config))==1
    changed=copy.deepcopy(config);changed['workload']=[{'query_id':'other'}]
    with pytest.raises(ValueError,match='Incompatible'):compatible_runs(tmp_path,changed)
    summary['actual_llm_request_attempts']=1;save()
    with pytest.raises(ValueError,match='API requests'):compatible_runs(tmp_path,config)
