"""Verify the revised paper, frozen evidence and release without provider access."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(archive=False):
    study=ROOT/'results/study'
    audit=json.loads((study/'calibration/verification.json').read_text())
    assert audit['completed_runs']==42 and audit['api_attempts']==0 and audit['raw_aggregates_verified']
    assert sha(study/'frozen_configuration.json')==audit['original_freeze_file_sha256']
    tests=ET.parse(study/'revision_tests.xml').getroot().findall('testsuite')
    count=sum(int(s.get('tests',0)) for s in tests)
    assert count==123 and not any(int(s.get(k,0)) for s in tests for k in ['failures','errors','skipped'])
    build=json.loads((study/'conference_paper_build.json').read_text())
    assert sha(ROOT/'conference_paper.docx')==build['output_sha256']
    qa=json.loads((study/'conference_paper_qa.json').read_text())
    assert qa['docx_sha256']==build['output_sha256'] and qa['pages']==5 and qa['every_page_visually_inspected']
    expected=['I. INTRODUCTION','II. BACKGROUND AND RELATED WORK','III. SELECTIVITY AWARE REUSE',
        'IV. SYSTEM DESIGN','V. EXPERIMENTAL METHODOLOGY','VI. RESULTS','VII. LIMITATIONS','VIII. CONCLUSION AND FUTURE WORK']
    rendered=ROOT/'tmp/conference/paper-calibration-verified.pdf'
    if rendered.exists():
        assert sha(rendered)==qa['rendered_pdf_sha256']
        paper=PdfReader(rendered);assert len(paper.pages)==5
        text='\n'.join(p.extract_text() for p in paper.pages)
        headings=[line.strip() for line in text.splitlines() if re.match(r'^[IVX]+\. ',line.strip())]
        for heading in ['A. Challenge data and reference standard','A. Original seven-policy replay']:assert heading in text
    else:
        # Release packages omit QA intermediates; bind the saved inspection to exact DOCX bytes.
        headings=qa['roman_sections']
    assert headings==expected,headings
    with zipfile.ZipFile(ROOT/'conference_paper.docx') as z:
        doc=ET.fromstring(z.read('word/document.xml'));w=doc.tag.split('}')[0][1:];ns={'w':w}
        paragraphs=doc.findall('w:body/w:p',ns);body=[];refs=[];in_refs=False
        for p in paragraphs:
            value=''.join(p.itertext())
            if value=='References':in_refs=True;continue
            (refs if in_refs else body).append(value)
            if in_refs and value:
                for run in p.findall('w:r',ns):
                    assert run.find('w:rPr/w:b',ns).get('{'+w+'}val')=='0'
        refs=[r for r in refs if re.match(r'^\[\d+\]',r)]
        assert len(refs)==29 and len(build['pdf_reference_to_paper_reference'])==25
        numbers=[int(n) for n in re.findall(r'\[(\d+)\]','\n'.join(body))]
        assert list(dict.fromkeys(numbers))==list(range(1,30))
        assert not re.search(r'\[P\d+\]','\n'.join(body))
    assert json.loads((study/'live_runtime_budget.json').read_text())['remaining']==221
    report=PdfReader(ROOT/'research_report.pdf')
    assert len(report.pages)==11 and 'Original study report with calibration supplement' in report.pages[0].extract_text()
    evidence=dict(paper_pages=5,reference_count=29,all_25_supplied_works_cited=True,main_sections=expected,
        tests_passed=count,posthoc_runs_verified=42,additional_api_attempts=0,original_freeze_unchanged=True,
        paper_sha256=sha(ROOT/'conference_paper.docx'),report_sha256=sha(ROOT/'research_report.pdf'))
    if archive:
        with zipfile.ZipFile(ROOT/'vectorq-sql-cache.zip') as z:
            manifest=json.loads(z.read('vectorq-sql-cache/RELEASE_MANIFEST.json'))
            for name,meta in manifest.items():
                content=z.read('vectorq-sql-cache/'+name)
                assert hashlib.sha256(content).hexdigest()==meta['sha256'] and len(content)==meta['bytes']
            for name in ['conference_paper.docx','README.md','research_report.pdf','scripts/conference_content.py',
                         'reports/calibration.md','reports/revision_checklist.md','results/study/calibration/verification.json']:
                assert z.read('vectorq-sql-cache/'+name)==(ROOT/name).read_bytes()
            assert not any(Path(n).name=='.env' for n in z.namelist())
            assert sum('/calibration/raw/' in n and n.endswith('.jsonl') for n in z.namelist())==42
            evidence.update(archive_files_verified=len(manifest),archive_sha256=sha(ROOT/'vectorq-sql-cache.zip'))
    (study/'revision_verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--archive',action='store_true');verify(p.parse_args().archive)
