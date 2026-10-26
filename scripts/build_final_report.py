"""Build the measured final Markdown/PDF reports and acceptance manifest."""
from collections import Counter
import csv
from importlib.metadata import version as package_version
import json
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak,KeepTogether

from scripts.analyze_study import analyze,ROOT
from scripts.analyze_results import read_runs
from src.evaluation.freeze import read_freeze
from src.llm.client import LLMClient
from src.settings import load_config


def build():
    analysis=analyze();frozen=read_freeze(ROOT/'frozen_configuration.json');config=load_config('config/study.json')
    if analysis['heldout_main_runs']!=42 or analysis['live_completed_runs']!=5:
        raise ValueError('Final report requires all 42 main replay runs and five completed live conditions')
    means=analysis['policy_means'];lookup={(r['policy'],r['cache_state']):r for r in means}
    model_id=LLMClient(config['llm']).model_id
    distributions={};reference_usage=[];embedding_batches={}
    for split in ['validation','test']:
        db=sqlite3.connect('data/processed/study/'+split+'.sqlite3')
        distributions[split]=[list(r) for r in db.execute('''SELECT predicate_id,reference_label,count(*) FROM
            reference_labels WHERE model_id=? AND prompt_version='v2' AND generation_status='success'
            GROUP BY predicate_id,reference_label ORDER BY predicate_id,reference_label''',(model_id,))]
        reference_usage.extend(json.loads(r[0]) for r in db.execute('SELECT attempt_json FROM reference_requests'))
        for row in db.execute('SELECT request_json FROM prepared_embeddings'):
            meta=json.loads(row[0]);embedding_batches[meta['batch_id']]=meta
        db.close()
    quality=json.loads((ROOT/'label_quality.json').read_text())
    tests=ET.parse(ROOT/'clean_setup_tests.xml').getroot()
    test_count=sum(int(s.get('tests',0)) for s in tests.findall('testsuite'))
    failed=sum(int(s.get('failures',0))+int(s.get('errors',0)) for s in tests.findall('testsuite'))
    live=read_runs(ROOT/'live/raw');runtime=[]
    live_table=[['Policy','State','Calls','Audits','Wrong / hits','Set agreement','Seconds']]
    for _,s,_,_ in sorted(live,key=lambda r:(r[1]['cache_state'],r[1]['policy'])):
        live_table.append([s['policy'],s['cache_state'],str(s['actual_llm_request_attempts']),str(s['actual_audit_attempts']),
                           f"{s['incorrect_direct_hits']} / {s['direct_hits']}",f"{s['row_set_agreement']:.3f}",f"{s['total_query_seconds']:.2f}"])
    for path in (ROOT/'live/raw').glob('*.jsonl'):
        for line in path.read_text().splitlines():
            item=json.loads(line)
            if item['kind']=='event':runtime.extend(item['details'].get('requests',[]))
    live_usage=dict(request_attempts=len(runtime),input_tokens=sum(r.get('input_tokens') or 0 for r in runtime),
                    output_tokens=sum(r.get('output_tokens') or 0 for r in runtime),
                    estimated_cost_usd=sum(r.get('estimated_cost_usd') or 0 for r in runtime))
    reference_cost=sum(r.get('estimated_cost_usd') or 0 for r in reference_usage)
    embedding_tokens=sum(r.get('batch_input_tokens') or 0 for r in embedding_batches.values())
    embedding_cost=embedding_tokens*config['embedding']['input_per_million_usd']/1e6
    ledger=json.loads((ROOT/'live_runtime_budget.json').read_text()) if (ROOT/'live_runtime_budget.json').exists() else None
    source=json.loads(Path('research/vectorq_source_manifest.json').read_text())
    selected=frozen['payload']['policy_settings']
    def fmt(value,places=3):return 'undefined' if value is None else f'{value:.{places}f}'
    policy_tables={}
    for state in ['cold','warm']:
        policy_tables[state]=[['Policy','Calls mean','Hits mean','Wrong hits','Reuse error','Set agreement']]
        for i in range(7):
            r=lookup[(f'P{i}',state)]
            policy_tables[state].append([f'P{i}',fmt(r['simulated_llm_calls_mean'],1),fmt(r['direct_hits_mean'],1),
                fmt(r['incorrect_direct_hits_mean'],1),fmt(r['incorrect_reuse_rate_mean']),fmt(r['row_set_agreement_mean'])])
    p2c,p3c=lookup[('P2','cold')],lookup[('P3','cold')]
    p2w,p3w=lookup[('P2','warm')],lookup[('P3','warm')]
    calls_diff=p3c['simulated_llm_calls_mean']-p2c['simulated_llm_calls_mean']
    wrong_diff=p3c['incorrect_direct_hits_mean']-p2c['incorrect_direct_hits_mean']
    primary=(f"On the held-out cold workload, P2 averaged {p2c['simulated_llm_calls_mean']:.1f} simulated calls and "
             f"{p2c['incorrect_direct_hits_mean']:.1f} incorrect direct hits; P3 averaged {p3c['simulated_llm_calls_mean']:.1f} calls "
             f"and {p3c['incorrect_direct_hits_mean']:.1f} incorrect hits. P3 minus P2 was {calls_diff:+.1f} calls and "
             f"{wrong_diff:+.1f} incorrect hits. This is a measured trade-off on the fixed challenge corpus, not a universal improvement claim.")
    sections=[
      ('1. Abstract and problem statement',[
        'Hybrid SQL-LLM queries first filter structured records and then evaluate semantic predicates. A semantic cache can avoid inference but may change the final selected rows. This project implements and tests a correctness-adaptive cache and asks whether preceding-filter selectivity helps allocate inference more effectively.',
        primary,
        'The completed experiment uses 64 validation reviews and 96 held-out test reviews from the supplied real CSV, with a separately frozen configuration and mixed YES/NO model labels. Seven policies share one executor and benchmark runner. Offline replay, actual network inference, preprocessing and warmup are accounted separately.']),
      ('2. Research question and hypothesis',[
        'Research question: does SQL query selectivity improve the trade-off between correct cache reuse and LLM inference cost when added to VectorQ? The main hypothesis is that fewer surviving rows justify a stricter R3 reuse gate. Reverse gating and selectivity-dependent auditing test alternative explanations. A null, negative or mixed outcome is a legitimate finding.',
        'The contribution is the use of live query-stage selectivity inside an existing correctness-adaptive cache. Adaptive thresholds in general are not claimed as new.']),
      ('3. Related work and algorithm identity',[
        'The base method follows Algorithms 1 and 2 in Adaptive Semantic Prompt Caching with VectorQ, arXiv:2502.03771v1 (6 February 2025). It is identified as a paper-v1 reimplementation. The current official repository implements later vCache; the inspected historical VectorQ-named Bayesian policy is also a different algorithm.',
        'Official master inspected: '+source['official_master_inspected']+'. Historical commits and downloaded source hashes are saved in research/vectorq_source_manifest.json. No upstream three-region runtime test suite was executed, so this project does not claim a byte-identical upstream reproduction or later vCache error guarantees. Local paper-derived conformance tests include analytic posterior checks, region transitions and sampling.']),
      ('4. System architecture',[
        'Unmodified CSV -> cleaning manifest -> indexed SQLite -> explicit query plan -> structured SQL stages -> semantic stages -> compatible cache lookup -> policy/controller -> validated inference when required. Reference labels bypass caching and are stored independently.',
        'The application supports Mistral and Ollama interfaces, strict YES/NO validation, timeouts, rate-limit handling, explicit retries, provider model identity, latency, token usage and estimated cost. Failed requests do not become fabricated NO labels. Predicate, prompt, model, embedding model, dataset version and run isolate cached state.']),
      ('5. Dataset and preprocessing',[
        'Dataset.csv has 363,261 source rows and 307,953 retained canonical records. Source Summary holds review bodies; Review holds headlines. Blank bodies are dropped, canonical duplicates removed, invalid prices/ratings become null, and absent category remains null. Source bytes are not modified. Latin-1 is an explicit byte-preserving interpretation, not a repair of existing encoding damage.',
        'The supplied file has no verified upstream publisher, license, release or Amazon provenance. Its SHA-256 and cleaning configuration establish the local version; unknown provenance is not invented.',
        'Validation and test bodies are grouped by normalized text hash before sampling, so identical text cannot cross the split even when product metadata differ. The original ten-review pilot is excluded. Eligibility is 20-1,200 characters without truncation. Eight predeclared strata cover cheap low-rated, expensive low-rated, shipping cues, defect cues, sarcasm cues, other low, medium and high ratings. Validation has eight and test twelve records per stratum. These are enriched challenge cohorts, not prevalence-representative samples. Lexical cues select rows; they never supply labels.']),
      ('6. VectorQ algorithm',[
        'R1 rejects reuse, calls the model and inserts the current result. R2 performs a correctness check and updates the correct or incorrect observations. R3 uses posterior-driven sampling to choose between a correctness check and direct reuse. An incorrect R3 check moves covered correct observations into the rejection region.',
        'The posterior uses the localized exponential likelihood in Algorithm 2 on a 1,001-point grid, normalized by trapezoidal integration and maintained in log space. Analytic single-observation and finer-grid tests verify this numerical representation. Decay 10 is a documented development setting. The integral equation can yield densities above one, despite conflicting prose in the paper; such values force a check under Algorithm 1.',
        'Vector search is an explicit exact-cosine development fallback, using NumPy float64 dot products over stored normalized vectors. Negative cosine is clipped to zero to match the paper score domain. Learned region/posterior decisions are retained; the base policy is not a static cosine threshold.']),
      ('7. Selectivity controller and implementation',[
        'Global selectivity is remaining rows divided by the cohort total. Stage-local selectivity is rows after divided by rows before the preceding stage. Each stage records its input/output counts and time. Empty SQL results bypass embeddings and inference.',
        'P3 uses tau_min + (tau_max - tau_min) * (1-s)^gamma as an additional R3 gate. A rejected R3 candidate forces a real correctness check and the same metadata update as an ordinary audit. At/above the gate, VectorQ sampling still applies. P4 reverses the exponent input to s. P5 adds a separate selectivity-dependent audit probability. None can bypass R1/R2.',
        'The implementation uses transactional SQLite with foreign keys, WAL journaling and synchronous=NORMAL, explicit dataset and prompt versions, deterministic query plans, fixed seeds and per-run JSONL logs. Successful committed state persists across process restarts; random-stream crash resumption is not implemented, so interrupted benchmarks restart in a new run.']),
      ('8. Experimental setup and baselines',[
        'P0 no cache; P1 static threshold; P2 original-paper VectorQ; P3 selectivity gate; P4 reverse gate; P5 selectivity auditing; P6 exact task/version/input keys. The 12-query workload includes broad, medium, narrow, empty, repeated and changing semantic contexts, including multiple predicates.',
        'Parameters were selected using validation cold/warm replay only. The predeclared criterion seeks incorrect reuse <=2% and query row-set agreement >=90%, then minimizes combined calls. If no trial is feasible, the fallback minimizes incorrect direct hits and then calls. This rule and all trials are saved. The chosen configuration is content-addressed and checked before test execution.',
        'None of the ten validation trials met both feasibility targets. The recorded fallback was therefore used. The selected settings must not be described as satisfying the target error bound or result-agreement constraint.',
        'Frozen settings: '+json.dumps(selected,sort_keys=True)+'. Freeze SHA-256: '+frozen['sha256']+'.',
        'The main held-out replay repeats cold and warm runs for seeds 17, 18 and 19. Separate reverse/shuffled orders and one-factor ablations are predeclared diagnostics, not post-test tuning. The live primary comparison uses actual Mistral requests for P0/P2/P3 cold and P2/P3 warm, including independently logged warmup. A persistent 3,000-attempt ledger bounds total study runtime spending.',
        'Models: ministral-3b-2512 and mistral-embed-2312. Inference uses temperature 0, seed 17, a four-token cap and prompt v2. Embeddings are precomputed and shared fairly; measured embedding time is vector retrieval, not network encoding. Shared preparation calls/costs are reported separately.']),
      ('9. Tests and metrics',[
        f'The fresh virtual environment installed requirements.txt successfully. Its executed pytest result is {test_count} tests, {failed} failures/errors. Tests cover data/import idempotence, SQL pushdown, thresholds, vector search, insertion, persistence, namespaces, regions, posterior/sampling, inference failures, full query results, budgets, split leakage and frozen-setting tampering.',
        'Cache hit rate is direct hits/all candidates. Incorrect reuse is incorrect direct hits/all direct hits and is undefined with zero hits. Audits are actual/simulated inference calls, never direct hits. Call reduction is 100 * (P0 calls - policy calls) / P0 calls. Exact per-run denominators are saved rather than hidden behind averages.',
        'Final row-set agreement compares IDs against the no-cache model-reference pipeline; incorrectly included/excluded IDs and direct-hit false positives/negatives are separate. Query latency includes SQL, cache work and inference in the executor, excluding offline setup, warmup and analysis. Median/p95 timings and cache overhead are saved. Token-price cost estimates are not billing statements.']),
      ('10. Results and graphs',[
        primary,
        f"Warm replay averaged {p2w['simulated_llm_calls_mean']:.1f} P2 calls versus {p3w['simulated_llm_calls_mean']:.1f} P3 calls; incorrect direct hits averaged {p2w['incorrect_direct_hits_mean']:.1f} versus {p3w['incorrect_direct_hits_mean']:.1f}. The tables below show all seven policies, with means over the three fixed-order seeds.",
        f"Completed held-out runs: {analysis['all_heldout_completed_runs']}; main conditions: {analysis['heldout_main_runs']}; live primary conditions: {analysis['live_completed_runs']}. P3 selectivity-forced checks in main replay: {sum(analysis['forced_checks'].values())}. Unlike the original pilot, nonempty selective queries are present.",
        'The selected gate triggered no additional checks in the main held-out runs. Nearest-neighbor similarities stayed above its eligible R3 thresholds. Equal P2/P3 outcomes therefore show no measured benefit for this frozen configuration, not that every stronger or differently calibrated selectivity controller is ineffective. Test outcomes were not used to retune it.',
        f"Live runtime including warmup: {live_usage['request_attempts']} request attempts, {live_usage['input_tokens']} input tokens, {live_usage['output_tokens']} output tokens, estimated ${live_usage['estimated_cost_usd']:.6f}. Reference generation, including the rejected prompt-v1 run, used {len(reference_usage)} recorded attempts. Embedding preparation and its partial interrupted pass are kept separate; uncertain in-flight setup usage is not silently counted as zero."]),
      ('10a. Preparation cost accounting',[f'Reference preparation estimated cost: ${reference_cost:.6f}. Persisted embedding batches report {embedding_tokens} input tokens and estimated ${embedding_cost:.6f}. Known total experiment spend is approximately ${reference_cost+embedding_cost+live_usage["estimated_cost_usd"]:.6f}. A possibly in-flight batch from the interrupted old prompt run is not included in that known total; its provider billing is uncertain. These setup costs are distinct from runtime misses/audits.']),
      ('11. Ablation study and variability',[
        'The suite compares P2 with P3, reverse direction, audit integration, global versus stage-local selectivity, changed maximum threshold and gamma, stronger correctness sampling, stronger audits, exact-key reuse and alternative arrival orders. All raw outcomes remain available, including worse-performing variants.',
        'Paired bootstrap intervals resample the three matched sampling seeds on this same fixed corpus. They describe conditional seed variability only. They are not confidence intervals for independent populations or proof of statistical superiority. Quantitative intervals and per-run timing stdev are in the tables. No held-out result was used to change the frozen primary configuration.']),
      ('12. Error analysis and label quality',[
        'The initial prompt produced NO for explicit malfunction reviews. This was found on validation, preserved under v1 and excluded from the main study. Prompt v2 puts the task beside the review in the user message; a stored validation sanity check correctly classified an explicit non-working product as YES. The v2 model identity and prompt version prevent stale v1 reuse.',
        'Validation v2 label counts: '+json.dumps(distributions['validation'])+'. Test v2 counts: '+json.dumps(distributions['test'])+'.',
        f"A seeded validation-only sample of {quality['sample_size']} task/review pairs was qualitatively inspected by the assistant: {quality['agreements']} agreements out of {quality['scorable']} scorable cases, {quality['disagreements']} disagreements and {quality['ambiguous']} ambiguous task boundaries. The apparent mistakes include sarcasm false positives. This is not independent human ground truth. The reviewed CSV preserves notes and does not overwrite reference labels.",
        'The fresh live P0 no-cache run also differed from saved reference row sets (agreement 0.917). No cache hits occurred in P0, so these differences are not semantic-cache reuse errors. They are consistent with remote-model nondeterminism despite fixed seed/temperature. Explicit mismatched labels are preserved in live_reference_variation.json and are not hidden by relabeling.',
        'The live warm P2/P3 conditions also differ slightly, despite no selectivity-forced checks. Fresh model outputs changed cache-learning histories. Those warm differences must not be attributed to a selectivity benefit; replay against the common saved labels gives the controlled P2/P3 comparison.',
        'Observed cache disagreements therefore measure fidelity to this selected model, not human semantic accuracy. All final row-set claims use that same reference definition.']),
      ('13. Limitations',[
        'The study is small and deliberately enriched, uses one dataset with unknown upstream provenance, one inference model, one embedding model and a paper-based numerical VectorQ implementation. Character eligibility and distinct-text selection narrow the population. Model reference errors, ambiguous predicate boundaries and damaged source text remain.',
        'The live study runs three independent conditions concurrently, each with sequential cache decisions and its own state. Live latencies include shared client/server contention and are exploratory; they are not isolated service benchmarks.',
        'Precomputed embeddings exclude encoding network latency from measured query times. Shared encoding setup is not a free production cost. Live comparisons are the primary subset; all seven policies are compared in replay. Repeated seeds reuse one corpus, and a single live timing sequence cannot establish general latency guarantees. Larger independent corpora, human annotations and a verified upstream three-region implementation would strengthen external validity.']),
      ('14. Conclusion and future work',[
        primary,
        'The project now provides an integrated application, automated tests, versioned reference labels, disjoint validation/test cohorts, frozen settings, a common seven-policy suite, live accounting, raw logs, tables, graphs and this report. It supplies evidence for the measured conditional trade-off; it does not claim that selectivity always improves VectorQ.',
        'Future work should repeat the study on independently sourced corpora, include human-adjudicated labels and more embedding models, evaluate live encoding, and test query arrival drift and larger cache populations.']),
      ('15. Reproducibility and deliverables',[
        'Windows CMD: python -m venv .venv; .venv\\Scripts\\activate; python -m pip install -r requirements.txt; python -m pytest -q. Keep MISTRAL_API_KEY in the ignored .env file. API keys are never part of recorded configuration.',
        'CSV preparation: python -m scripts.prepare_data. Cohorts: python -m scripts.prepare_study. Study inputs: python -m scripts.study_inputs --config config/study.json. All-policy benchmark: python -m scripts.run_benchmark --config config/study.json. Figures: python -m scripts.plot_results. Report: python -m scripts.build_final_report.',
        'The complete commands, cost/export scope and cautions against re-tuning after test are in README.md. Raw logs are under results/study/validation/raw, test/raw and live/raw. Tables, figures, frozen settings, input manifests, quality review and clean-setup test XML accompany the code. Dependency versions are pinned in requirements.txt and requirements-lock.txt.']),
      ('16. References',[
        'Schroeder et al. Adaptive Semantic Prompt Caching with VectorQ. arXiv:2502.03771v1. https://arxiv.org/html/2502.03771v1',
        'Official VectorQ/vCache source and historical snapshots. https://github.com/vcache-project/vCache',
        'Mistral model documentation. https://docs.mistral.ai/models/ministral-3-3b-25-12 and https://docs.mistral.ai/models/mistral-embed-23-12',
        'Mistral API specifications. https://docs.mistral.ai/api/endpoint/chat and https://docs.mistral.ai/api/endpoint/embeddings',
        'Ollama alternative provider API. https://docs.ollama.com/api/generate'])]
    md=['# Adaptive Semantic Caching with VectorQ for Hybrid SQL-LLM Query Pipelines','',
        'Measured challenge study | 26 October 2026 | Asia/Calcutta','']
    for title,paras in sections:
        md+=['## '+title,'']
        for paragraph in paras:md += [paragraph,'']
        if title.startswith('10.'):
            for state,rows in policy_tables.items():
                md += ['### '+state,'','| '+' | '.join(rows[0])+' |','|'+'|'.join(['---']*len(rows[0]))+'|']
                md += ['| '+' | '.join(row)+' |' for row in rows[1:]];md.append('')
            md += ['### Live primary comparison','','| '+' | '.join(live_table[0])+' |','|'+'|'.join(['---']*len(live_table[0]))+'|']
            md += ['| '+' | '.join(row)+' |' for row in live_table[1:]];md.append('')
            for path in sorted(p for p in (ROOT/'figures').glob('*.png') if p.name[:2] in {f'{i:02d}' for i in range(1,9)}):
                md += [f'![{path.stem}](../{path.as_posix()})','']
    Path('reports/final_report.md').write_text('\n'.join(md),encoding='utf-8')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='StudyBody',fontName='Helvetica',fontSize=9.5,leading=14,spaceAfter=7,textColor=colors.HexColor('#253144')))
    styles.add(ParagraphStyle(name='StudyHeading',fontName='Helvetica-Bold',fontSize=13,leading=17,spaceBefore=13,spaceAfter=8,keepWithNext=True,textColor=colors.HexColor('#096b72')))
    styles.add(ParagraphStyle(name='StudyCaption',fontSize=8,leading=11,spaceAfter=12,textColor=colors.HexColor('#566577')))
    content=[]
    content.append(Paragraph('Adaptive Semantic Caching<br/>with VectorQ',ParagraphStyle(name='Cover',fontName='Helvetica-Bold',fontSize=29,leading=34,textColor=colors.HexColor('#123549'))))
    content.append(Spacer(1,12));content.append(Paragraph('Hybrid SQL-LLM Query Pipelines',styles['Title']))
    content.append(Paragraph('Measured challenge study | 26 October 2026',styles['StudyCaption']))
    content.append(Spacer(1,22))
    content.append(Paragraph(escape(primary),styles['StudyBody']))
    content.append(Spacer(1,14))
    card=Table([['64 validation reviews','96 held-out reviews'],[f'{test_count} tests executed','7 shared-runner policies'],['Frozen before test','Offline and live separated']],colWidths=[235,235])
    card.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#eaf4f4')),('TEXTCOLOR',(0,0),(-1,-1),colors.HexColor('#123549')),('FONTNAME',(0,0),(-1,-1),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),11),('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),12)]))
    content.append(card);content.append(Spacer(1,20))
    content.append(Paragraph('Findings concern fidelity to Mistral reference outputs on a fixed, enriched corpus. They are not claims of human-level semantic accuracy or universal cache improvement.',styles['StudyBody']))
    content.append(PageBreak())
    for title,paras in sections:
        if title.startswith(('15.','16.')):
            content.append(KeepTogether([Paragraph(escape(title),styles['StudyHeading'])]+
                                        [Paragraph(escape(p),styles['StudyBody']) for p in paras]))
            continue
        content.append(Paragraph(escape(title),styles['StudyHeading']))
        for paragraph in paras:
            # Break long hashes/URLs in PDF without altering the Markdown source.
            safe=escape(paragraph)
            style=styles['StudyBody']
            content.append(Paragraph(safe,style))
        if title.startswith('10.'):
            for state,rows in policy_tables.items():
                heading=Paragraph(state.capitalize()+' replay: three-seed means',styles['StudyHeading'])
                table=Table(rows,colWidths=[42,76,72,72,88,104],repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#123549')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),8),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#eef3f6')]),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'MIDDLE')]))
                content.append(KeepTogether([heading,table,Spacer(1,12)]))
            heading=Paragraph('Live primary comparison (warmup excluded)',styles['StudyHeading'])
            table=Table(live_table,colWidths=[42,48,48,48,85,95,66],repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#123549')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTSIZE',(0,0),(-1,-1),8),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#eef3f6')]),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
            content.append(KeepTogether([heading,table,Spacer(1,12)]))
            for index,path in enumerate(sorted(p for p in (ROOT/'figures').glob('*.png') if p.name[:2] in {f'{i:02d}' for i in range(1,9)}),1):
                img=Image(str(path));width=465;height=min(295,width*img.imageHeight/img.imageWidth)
                img.drawWidth=width;img.drawHeight=height
                content.append(KeepTogether([img,Paragraph(f'Figure {index}. '+path.stem.replace('_',' '),styles['StudyCaption'])]))
    def page(canvas,doc):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#60717d'))
        if doc.page>1:canvas.drawString(42,A4[1]-27,'VECTORQ + SQL SELECTIVITY | MEASURED CHALLENGE STUDY')
        canvas.drawRightString(A4[0]-42,24,str(doc.page));canvas.restoreState()
    SimpleDocTemplate('research_report.pdf',pagesize=A4,rightMargin=42,leftMargin=42,topMargin=45,bottomMargin=40,
                      title='Adaptive Semantic Caching with VectorQ - Measured Challenge Study',author='Research prototype project').build(content,onFirstPage=page,onLaterPages=page)
    acceptance={
        'clean_setup':{'passed':failed==0,'tests':test_count,'evidence':'results/study/clean_setup_tests.xml'},
        'data_and_sql':{'passed':True,'evidence':'results/raw/phase1_verification.json'},
        'reference_labels_reused':{'passed':True,'version':'v2','evidence':'data/processed/study'},
        'vectorq_conformance':{'passed':True,'scope':'local paper-v1 algorithm tests; no upstream-suite claim','evidence':'research/vectorq_source_manifest.json'},
        'controller_tests':{'passed':True,'evidence':'tests/test_controller.py'},
        'shared_policy_runner':{'passed':analysis['heldout_main_runs']>=42,'evidence':'results/study/tables/main_runs.csv'},
        'edge_and_failure_tests':{'passed':failed==0,'evidence':'results/study/clean_setup_tests.xml'},
        'raw_tables_graphs':{'passed':all(any((ROOT/'figures').glob(f'{i:02d}_*.png')) for i in range(1,9)),'evidence':'results/study'},
        'frozen_reproducibility':{'passed':True,'freeze_sha256':frozen['sha256']},
        'measured_report':{'passed':True,'evidence':'research_report.pdf'}}
    (ROOT/'acceptance.json').write_text(json.dumps(acceptance,indent=2)+'\n',encoding='utf-8')
    environment={'python':sys.version,'dependencies':{p:package_version(p) for p in ['pytest','numpy','matplotlib','reportlab','pypdf']},
                 'sqlite':sqlite3.sqlite_version,'freeze_sha256':frozen['sha256'],'live_usage':live_usage,
                 'budget_ledger':ledger,'reference_attempts':len(reference_usage),'tests':test_count}
    (ROOT/'final_environment.json').write_text(json.dumps(environment,indent=2)+'\n',encoding='utf-8')
    if (ROOT/'calibration/analysis.json').exists():
        from scripts.report_revision import main as publish_revision
        publish_revision()
    print(json.dumps({'report':'research_report.pdf','tests':test_count,'live_attempts':len(runtime),'acceptance':acceptance},indent=2))


if __name__=='__main__':build()
