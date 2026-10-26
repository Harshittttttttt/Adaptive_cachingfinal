"""Package source, reproducibility evidence and clean cohort snapshots; exclude secrets."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import zipfile

from src.settings import load_env


def snapshot(source,destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source) as src,sqlite3.connect(destination) as dst:
        src.backup(dst)
        # Raw JSONL preserves experiment history; replay packages start with
        # empty learned state while retaining real rows, labels and vectors.
        for table in ['experiment_events','cache_entries','policy_configuration','experiment_runs']:
            if dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                dst.execute('DELETE FROM '+table)
        dst.commit()
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.execute('VACUUM')
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Snapshot integrity failed')
        if dst.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Snapshot foreign keys failed')


def main():
    load_env()
    required=['research_report.pdf','conference_paper.docx','reports/final_report.md','results/study/acceptance.json']
    if not all(Path(p).exists() for p in required):raise ValueError('Build and verify the final report before packaging')
    acceptance=json.loads(Path('results/study/acceptance.json').read_text())
    if not all(item['passed'] for item in acceptance.values()):raise ValueError('Acceptance checks are incomplete')
    files={}
    for directory in ['src','scripts','tests','config','research','results/study','ui']:
        for p in Path(directory).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in {'.py','.json','.jsonl','.csv','.png','.xml','.toml','.md','.html','.css','.js'}:
                if p.as_posix() in {'results/study/release_manifest.json','results/study/revision_verification.json'}:continue
                files[p.as_posix()]=p
    for name in ['README.md','requirements.txt','requirements-lock.txt','requirements-documents.txt','pytest.ini','.gitignore','.gitattributes','.env.example','Dataset.csv',*required,
                 'SOL_HANDOFF.md','reports/phase1.md','reports/research_report.md','reports/calibration.md',
                 'reports/revision_checklist.md','reports/human_annotation_protocol.md','data/processed/import_report.json',
                 'data/reference_labels/validation_audit.csv','results/raw/phase1_verification.json']:
        files[name]=Path(name)
    for p in Path('data/processed/study').glob('*.json'):files[p.as_posix()]=p
    for split in ['validation','test']:
        relative='data/processed/study/'+split+'.sqlite3'
        target=Path('tmp/release-snapshots')/(split+'.sqlite3')
        snapshot(Path(relative),target);files[relative]=target
    secrets=[os.environ.get(k,'').encode() for k in ['MISTRAL_API_KEY','OPENAI_API_KEY'] if os.environ.get(k)]
    manifest={}
    output=Path('vectorq-sql-cache.zip')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(files.items()):
            if path.name=='.env':raise ValueError('Secret file excluded from release')
            content=path.read_bytes()
            if any(secret in content for secret in secrets):raise ValueError('Configured credential found in release input')
            manifest[name]={'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}
            archive.writestr('vectorq-sql-cache/'+name,content)
        archive.writestr('vectorq-sql-cache/RELEASE_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise ValueError('Archive CRC verification failed')
    Path('results/study/release_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'archive':str(output),'files':len(manifest),'bytes':output.stat().st_size,'secrets_included':False},indent=2))


if __name__=='__main__':main()
