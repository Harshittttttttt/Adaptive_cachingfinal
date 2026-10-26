"""Publish the exploratory supplement and scope the retained original report."""
from io import BytesIO
import json
from pathlib import Path
from pypdf import PdfReader,PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer

ROOT=Path(__file__).resolve().parents[1]
NOTICE='Original study report with calibration supplement'

def markdown_table(headers,rows):
    return ['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|',
            *['| '+' | '.join(map(str,row))+' |' for row in rows],'']

def write_supplement():
    evidence=json.loads((ROOT/'results/study/calibration/analysis.json').read_text())
    text=['# Calibration supplement','',
        'Exploratory post-hoc analysis | 26 October 2026','',
        'This supplement accompanies the revised conference paper. The original report retains its original study scope; the current interpretation is a calibration diagnosis, with a selectivity-specific advantage still unestablished.','',
        '## Design and provenance','',
        'The original test result was already known when this diagnostic design was chosen. The 42 additional offline runs use seven settings, two cache states and three seeds (17–19), adding 504 measured query executions on the same 96 test reviews. No independent reviews or API requests were added. Original replay comprised 110 runs and 1,320 query executions; repetition does not turn the combined 1,824 executions into independent data.','',
        'The validation-quantile rule uses q10 = 0.9676635929526995 and q90 = 1.0 from 206 R3 events in one validation P2 cold trajectory. The quantile levels were chosen post hoc. Using validation scores does not make the existing test set untouched again. Constant settings change only the R3 score threshold; the quantile rule varies it with global selectivity. The posterior and executor are unchanged.','',
        'The plan records separate hashes for the original freeze file and its embedded payload. Full run logs are in `results/study/calibration/raw/`; configuration, zero-API-use, raw aggregates and constant-0.92 event signatures are checked in `results/study/calibration/verification.json`.','',
        '## Mechanism','',
        'An extra check requires R3 membership and score z < tau(s). If every eligible score is at least the configured upper bound, the added rule cannot intervene. With identical inputs, initial state, saved-label oracle and posterior random stream, P2 and P3 then follow the same trajectory. P3 uses a separate controller random stream and an inactive check does not alter posterior sampling.','',
        'The pooled main P2 cold R3 minimum is 0.947187 and warm minimum 0.954605, above the original 0.92 ceiling. These are actual eligible events rather than arbitrary pairwise scores. Repeated events across seeds, predicates and queries are dependent.','',
        '## Full calibration results','',
        'Values are mean ± sample SD over three seeds. Set agreement and call reduction are percentages; their SDs are percentage points. Calls are simulated measured-pass inferences excluding warmup. IDH = incorrect direct hits against saved model outputs. Checks = selectivity-threshold-forced inferences.','']
    fmt=lambda r,k,scale=1:f"{r[k+'_mean']*scale:.1f} ± {r[k+'_sd']*scale:.1f}"
    text+=markdown_table(['Rule','State','Calls','IDH','Checks','Set agreement %','Call reduction %'],
        [[r['variant'],r['state'],fmt(r,'simulated_llm_calls'),fmt(r,'incorrect_direct_hits'),fmt(r,'forced_checks'),fmt(r,'row_set_agreement',100),fmt(r,'call_reduction_percent')] for r in evidence['sweep']])
    text+=['A constant 0.99 threshold has zero incorrect direct hits and 100% complete query row set agreement in this replay, at 5.6% cold and 31.6% warm call savings. This is neither an optimal-setting claim nor a selectivity-dependent method. The quantile rule activates but retains incorrect direct hits and only 52.8% cold / 58.3% warm mean set agreement. A threshold at 1.0 also depends on numerical cosine equality for repeated inputs.','',
        '![Exploratory calibration sweep](../results/study/figures/09_calibration_sweep.png)','',
        '![R3 candidate scores](../results/study/figures/10_r3_similarity.png)','',
        '## Score distributions','',
        'Groups by predicate and query type partition the same events in two different ways. n is event count, not independent review count.','']
    text+=markdown_table(['State','Grouping','Group','n','Min','q10','Median','q90','Max'],
        [[r['state'],r['level'],r['group'],r['events'],*[f"{r[k]:.6f}" for k in ['min','q10','q50','q90','max']]] for r in evidence['distributions']])
    text+=['## The no-cache denominator','',
        'There are 12 query plans, three distinct predicates and 14 semantic stages. One stage receives zero rows. In multi-predicate plans, the later stage receives preceding reference-positive survivors. One simulated inference per stage input gives 581. Cached errors can change later-stage inputs, so candidate counts differ across policies. Call reduction is 100 × (581 − measured calls)/581.','']
    text+=markdown_table(['Query','Shipping','Defect','Sarcasm','Total'],[[r[k] for k in ['query','shipping','defect','sarcasm','total']] for r in evidence['baseline']])
    text+=['## Limits and next confirmatory study','',
        'Mistral outputs are fallible references, not human gold labels. The assistant audit of 24 validation pairs was not independent human annotation. Human accuracy, multiple-dataset transfer and independently replicated live runtime remain unmeasured. See `human_annotation_protocol.md` and `revision_checklist.md` for the remaining work. A fresh study must freeze calibrated constant and selectivity rules on new validation data before testing untouched corpora.','',
        '## Reproduction','',
        'Run `python -m scripts.calibration_diagnostics` to validate/resume offline evidence and regenerate tables and plots. Incompatible saved configurations are rejected. Run `python -m scripts.report_revision` to regenerate this supplement and retain the scope notice on the original report. Neither command makes provider requests.','']
    (ROOT/'reports/calibration.md').write_text('\n'.join(text),encoding='utf-8')

def scope_original_report():
    path=ROOT/'research_report.pdf'
    reader=PdfReader(BytesIO(path.read_bytes()))
    if NOTICE in reader.pages[0].extract_text():return
    buffer=BytesIO();styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='NoticeBody',fontName='Helvetica',fontSize=11,leading=17,spaceAfter=15))
    content=[Paragraph(NOTICE,styles['Title']),Spacer(1,28)]
    for paragraph in [
        '26 October 2026',
        'The following pages retain the original 110-run replay study and five live conditions. The current conference paper reframes the contribution around threshold calibration and includes 42 additional exploratory offline runs.',
        'The original selectivity-aware reuse threshold never activates because its 0.92 ceiling lies below eligible R3 scores. A later threshold sweep demonstrates active interventions. A constant 0.99 threshold removes incorrect direct hits against the saved references while saving fewer inference calls. A validation-quantile selectivity rule activates but still changes result sets.',
        'Read conference_paper.docx for the revised research argument and reports/calibration.md for the complete diagnostic tables, score distributions and 581-call derivation. The local dashboard has a separate Calibration study section. These files accompany this report in the release package.',
        'The extra 504 query executions reuse the same 96 test reviews. The diagnostic design is post-hoc, reference labels remain model-generated, and no additional API requests were made. Human-verified accuracy, multiple datasets and expanded live replication remain future empirical work.',
        'The retained report pages describe the original study, with its original figures and tables. Use the revised paper and supplement for current framing, uncertainty tables and exploratory calibration interpretation.'
    ]:content.append(Paragraph(paragraph,styles['NoticeBody']))
    SimpleDocTemplate(buffer,pagesize=A4,leftMargin=55,rightMargin=55,topMargin=65,bottomMargin=55).build(content)
    writer=PdfWriter();writer.append(PdfReader(BytesIO(buffer.getvalue())));writer.append(reader)
    writer.add_metadata({'/Title':NOTICE,'/Author':'Nandana Raj; Harshit Gupta; Vaishnavi Ganesan'})
    with path.open('wb') as file:writer.write(file)
    md=ROOT/'reports/final_report.md';original=md.read_text(encoding='utf-8')
    if not original.startswith('> Original study report'):
        md.write_text('> Original study report (110 replay runs and five live conditions). For the revised calibration argument and the separate 42-run post-hoc analysis, read [the calibration supplement](calibration.md) and the revised conference paper. The following narrative retains its original study scope.\n\n'+original,encoding='utf-8')

def main():
    write_supplement();scope_original_report()
    print('Calibration supplement written; original report scope notice retained.')

if __name__=='__main__':main()
