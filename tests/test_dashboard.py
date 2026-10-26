"""Dashboard reads evidence accurately and never serves arbitrary project files."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen
import pytest
import scripts.serve_dashboard as dashboard


@pytest.fixture
def saved(tmp_path, monkeypatch):
    root=tmp_path; study=root/'results/study'; raw=study/'test/raw';raw.mkdir(parents=True)
    (study/'frozen_configuration.json').write_text(json.dumps({'payload':{'policy_settings':{'gamma':1}}}))
    rows=[{'kind':'run','config':{'policies':{'gamma':1}}},
          {'kind':'event','pass_kind':'warmup','query_id':'q','decision':'hit'},
          *[{'kind':'event','pass_kind':'measure','query_id':'q','decision':'hit','index':i} for i in range(105)],
          {'kind':'event','pass_kind':'measure','query_id':'other','decision':'miss'},
          {'kind':'query','pass_kind':'measure','query_id':'q'},
          {'kind':'summary','run_id':'test-run','policy':'P3'}]
    (raw/'complete.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
    (raw/'interrupted.jsonl').write_text(json.dumps(rows[0]))
    (study/'calibration').mkdir()
    (study/'calibration/analysis.json').write_text(json.dumps({'new_runs':42,'new_unique_reviews':0,'api_attempts':0,'sweep':[]}))
    (root/'.env').write_text('PRIVATE_TEST_VALUE=never-serve')
    (root/'ui').mkdir();(root/'ui/index.html').write_text('<html>Dashboard</html>')
    monkeypatch.setattr(dashboard,'ROOT',root);monkeypatch.setattr(dashboard,'STUDY',study)
    return dashboard.Dashboard()


def test_only_complete_runs_and_measured_events(saved):
    assert len(saved.runs)==1
    r=saved.api('/api/run',{'id':['test-run'],'query':['q'],'decision':['hit']})
    assert r['total']==105 and len(r['events'])==100
    assert r['summary']['variant']=='main settings'
    page=saved.api('/api/run',{'id':['test-run'],'query':['q'],'offset':['100']})
    assert [e['index'] for e in page['events']]==list(range(100,105))
    assert len(page['queries'])==1
    with pytest.raises(ValueError):saved.api('/api/run',{'id':['../../.env']})
    with pytest.raises(ValueError):saved.api('/api/run',{'id':['test-run'],'offset':['-1']})


def test_calibration_is_separate_from_heldout_explorer(saved):
    study=saved.api('/api/calibration',{})
    assert study['new_runs']==42 and study['new_unique_reviews']==0 and study['api_attempts']==0
    assert len(saved.api('/api/runs',{}))==1


def test_http_asset_allowlist(saved):
    server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.make_handler(saved))
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base) as response:
            assert b'Dashboard' in response.read()
            assert response.headers['X-Content-Type-Options']=='nosniff'
        for path in ['/.env','/../.env','/%2e%2e/.env','/config/study.json']:
            with pytest.raises(HTTPError) as error:urlopen(base+path)
            assert error.value.code==404
        with urlopen(base+'/api/run?id=test-run&query=q') as response:
            assert json.load(response)['total']==105
    finally:
        server.shutdown();server.server_close();worker.join()
