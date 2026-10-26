"""Generate the 17-section research checkpoint from executed raw logs."""
from collections import Counter,defaultdict
from importlib.metadata import version as package_version
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import xml.etree.ElementTree as ET

from scripts.analyze_results import analyze, read_runs
from src.settings import load_config


def main():
    config=load_config()
    analyze()
    runs=read_runs(config['logging']['directory'])
    original=[r for r in runs if r[1]['order']=='fixed' and r[1]['repeat']==0
              and r[0]['config']['policies']==config['policies']]
    main_runs={}
    for run in original:main_runs[(run[1]['mode'],run[1]['cache_state'],run[1]['policy'])]=run
    live_cold=[main_runs[k][1] for k in sorted(main_runs) if k[:2]==('live','cold')]
    live_warm=[main_runs[k][1] for k in sorted(main_runs) if k[:2]==('live','warm')]
    def table(summaries,call_key):
        lines=['| Policy | Calls | Audits | Direct hits / candidates | Incorrect / hits | Query row-set agreement | Query seconds |',
               '|---|---:|---:|---:|---:|---:|---:|']
        for s in summaries:
            audit=s['actual_audit_attempts'] if call_key.startswith('actual') else s['simulated_audit_calls']
            reuse=f"{s['incorrect_direct_hits']}/{s['direct_hits']}" if s['direct_hits'] else 'undefined (0 hits)'
            lines.append(f"| {s['policy']} | {s[call_key]} | {audit} | {s['direct_hits']}/{s['candidates']} | {reuse} | {s['row_set_agreement']:.3f} | {s['total_query_seconds']:.4f} |")
        return '\n'.join(lines)
    with sqlite3.connect(config['dataset']['database']) as db:
        attempts=[json.loads(r[0]) for r in db.execute('SELECT attempt_json FROM reference_requests')]
        labels=db.execute('SELECT predicate_id,reference_label,count(*) FROM reference_labels GROUP BY predicate_id,reference_label').fetchall()
    measured_live=[s for _,s,_,_ in runs if s['mode']=='live']
    live_calls=sum(s['actual_llm_request_attempts']+s['warmup_actual_calls'] for s in measured_live)
    runtime_requests=[]
    for path in Path(config['logging']['directory']).glob('live-*.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            item=json.loads(line)
            if item['kind']=='event':runtime_requests.extend(item['details'].get('requests',[]))
    live_cost=sum(r.get('estimated_cost_usd') or 0 for r in runtime_requests)
    forced=Counter(e['reason'] for _,s,events,_ in runs for e in events if s['mode']=='offline')
    suite=ET.parse('results/raw/final_tests.xml').getroot()
    totals={k:sum(int(s.get(k,0)) for s in suite.findall('testsuite')) for k in ['tests','failures','errors','skipped']}
    variability=defaultdict(list)
    for header,s,_,_ in runs:
        key=(s['mode'],s['policy'],s['cache_state'],s['order'],json.dumps(header['config']['policies'],sort_keys=True))
        variability[key].append(s['total_query_seconds'])
    import csv
    with Path('results/tables/repeated_run_variability.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.writer(file);writer.writerow(['mode','policy','cache_state','order','policy_config','runs','mean_seconds','stdev_seconds'])
        for key,values in variability.items():
            writer.writerow([*key,len(values),statistics.mean(values),statistics.stdev(values) if len(values)>1 else ''])
    report=f'''# Adaptive Semantic Caching with VectorQ for Hybrid SQL–LLM Query Pipelines

Research checkpoint — 26 October 2026 (Asia/Calcutta). Executed development pilot; final validation/test study pending.

## 1. Abstract

This prototype evaluates SQL selectivity as an additional control on a correctness-adaptive semantic cache. It imports a real product-review CSV, executes structured filters before semantic tasks, and compares seven policies on the same persistent model labels and embeddings. The main comparison is original-paper VectorQ (P2) versus its selectivity gate (P3). The ten-review pilot has only NO reference labels, so its measurements validate execution and accounting rather than the scientific hypothesis. In the live cold pilot P2 and P3 each required 16 inference attempts out of a 40-attempt no-cache baseline. This observation does not establish a correctness benefit.

## 2. Problem statement

Hybrid queries combine inexpensive SQL filters with costly semantic inference. Approximate reuse reduces model calls but may change selected row IDs. A cache decision must account for task/version compatibility, uncertain correctness and the actual cost of audits.

## 3. Research question and hypotheses

Does adding preceding-filter selectivity to VectorQ improve correct reuse versus inference cost? The main hypothesis is stricter reuse when fewer rows remain. Reverse-direction gating and selectivity-driven auditing are controls. They may yield null, negative or mixed outcomes; superiority is not assumed.

## 4. Related work and distinction from VectorQ

VectorQ's original paper v1 supplies the three-region correctness-adaptive base. The current official repository and a historical VectorQ-named Bayesian policy implement different methods. Our P2 is an explicitly identified reimplementation of paper v1 Algorithms 1–2, not the later verified vCache algorithm. The proposed contribution is applying live SQL selectivity to this existing cache; adaptive thresholds in general are not claimed as new.

## 5. System architecture

Unmodified CSV → versioned cleaning → indexed SQLite → explicit query plan → SQL stages → semantic stages → compatible nearest neighbor → cache policy/controller → validated Mistral inference when required. Separate reference-label generation bypasses the cache. Reference, encoding-setup, warmup and measured-runtime calls remain distinct. SQLite and raw JSONL preserve decisions and configurations. Each run has its own cache and seeded sampling streams.

## 6. Dataset and preprocessing

The full file has 363,261 source rows; cleaning retains 307,953. Review bodies are in source Summary and headlines in source Review. Blank bodies are dropped, canonical duplicates removed, invalid numeric values set to null, and optional category remains null. Latin-1 preserves the source bytes' interpretation but cannot repair previously corrupted text. Upstream publisher, license, release and Amazon provenance remain unknown. See phase1.md and the import manifest for hashes and counts.

The separate pilot derives exactly the first ten cleaned reviews in stable ID order. Its version and parent/row IDs are recorded in data/processed/pilot_manifest.json. It is a development cohort, not a held-out test. The 12-query workload uses actual rating/price columns, repeated contexts, empty filters and multi-stage tasks. Some narrow filters yield no candidates within this tiny cohort, even though the full dataset has narrow-query matches.

## 7. VectorQ base method

R1 rejects reuse and inserts current validated inference; R2 checks the model and updates observed correctness; R3 samples a correctness audit before eligible reuse. Incorrect R3 validations move covered correct observations into rejection. The correctness posterior follows Algorithm 2's localized exponential update, maintained in log space on a 1,001-point grid. Trapezoidal normalization follows the integral equation, despite conflicting paper prose about a [0,1] density bound. Densities above the uniform sampling upper bound force checks. Analytic one-update and finer-grid convergence tests verify the numerical representation. Decay 10 is a development setting. Search uses the documented exact-cosine fallback with negative scores clipped to zero.

No upstream three-region runtime or its test suite was executed. Inspected historical sources contain either unfinished posterior methods or a different logistic algorithm. Therefore these results must not be described as an exact reproduction of the official implementation. Source URLs, pinned commits, hashes and deviations are in research/vectorq_source_manifest.json.

## 8. Selectivity controller

P3 applies tau_min + (tau_max − tau_min) × (1 − s)^gamma only to R3. Below the gate it forces an inference and the same posterior/region update as an ordinary correctness check. At or above the gate original sampling remains active. P4 substitutes s^gamma; P5 adds a separate selectivity-dependent audit probability. R1 and R2 rules remain intact. Development parameters are .72, .92, gamma 1; missing or invalid selectivity is rejected when the controller needs it. Global selectivity is remaining/total cohort rows; stage-local selectivity is after/before the preceding stage.

## 9. Experimental methodology

One runner gives all policies the same explicit workload, reference labels, input embedding model and query order. Cold runs start empty; warm runs use distinct caches populated by an unmeasured workload pass. Warmup calls are still logged and included in total operational spend. Seed 17 is the main pilot seed; reverse/shuffled arrival orders and seed 18 are separate development runs. No parameters were tuned on a final test set. No validation-tuned frozen final configuration exists yet.

All benchmark modes use precomputed mistral-embed-2312 vectors. Encoding setup is separately measured and charged; measured embedding time is vector retrieval, not live encoding. Live runs issue actual ministral-3b-2512 requests for misses and audits. Offline replay makes zero API requests and counts simulated calls. Temperature 0, seed 17 and four-token outputs reduce cost and variability but do not guarantee remote determinism. A shared runtime budget constrained the approved pilot to 500 request attempts; executed cold plus warmup plus warm runtime attempts: **{live_calls}**.

## 10. Baseline configurations

P0 no cache; P1 fixed cosine .82; P2 paper-v1 VectorQ; P3 VectorQ plus main selectivity gate; P4 reverse gate; P5 selectivity-dependent extra audits; P6 exact task/version/input key. All namespaces include cohort version, task, prompt, LLM configuration identity, embedding model and isolated run. Query results use conjunction semantics. A failed inference yields no fabricated label or partial successful query result.

## 11. Metrics

Direct hit rate uses all processed semantic candidates as denominator. Incorrect reuse is incorrect direct hits/all direct hits and is undefined when there are no hits. Audits are not direct hits, including when they confirm a cached label. Call reduction uses 100 × (baseline calls − policy calls)/baseline calls; offline simulated calls and actual live attempts are separate. The no-cache reference candidate count excludes retries; this pilot had no retries. Final row-set agreement, included/excluded IDs and direct-hit YES/NO errors remain separate from unmeasured human semantic truth. Raw logs contain stage/candidate timings and token usage; tables include median/p95 query timing and cost estimates. Empty-query timing is included, so query medians can be near zero.

## 12. Results

Live cold runs (each policy processes 40 candidates, with all 12 final query results agreeing with the model-reference pipeline):

{table(live_cold,'actual_llm_request_attempts')}

Live warm measurement, excluding separately logged warmup calls:

{table(live_warm,'actual_llm_request_attempts')}

The reference preparation made {len(attempts)} actual attempts: {sum(r.get('input_tokens') or 0 for r in attempts)} input tokens and {sum(r.get('output_tokens') or 0 for r in attempts)} output tokens. Its estimated price is ${sum(r.get('estimated_cost_usd') or 0 for r in attempts):.7f}, excluded from runtime miss counts. Shared embedding setup used 30 requests, 2,253 input tokens and an estimated $0.0002253. Live runtime including warmup used {sum(r.get('input_tokens') or 0 for r in runtime_requests)} input tokens and {sum(r.get('output_tokens') or 0 for r in runtime_requests)} output tokens, with estimated inference cost ${live_cost:.7f}. Monetary values use configured standard token prices, not billing statements.

The final test suite reports {totals['tests']} tests, {totals['failures']} failures, {totals['errors']} errors, {totals['skipped']} skipped. See final_tests.xml. Tables/figures derive from executed logs, including {len(runs)} completed runs; interrupted logs without a terminal summary are excluded.

## 13. Ablation study

The saved development sweep contains 106 runs: global versus stage-local selectivity; changed minimum/maximum thresholds; gamma .5 and 2; stronger posterior audits; increased selectivity audits; reverse and shuffled query orders; and seed-18 repetition. Each run stores its exact settings and order. This is a development sensitivity check, not a final validation sweep or final parameter selection. results/tables/all_runs.csv preserves the complete outcomes; repeated_run_variability.csv reports observed timing mean/stdev when repeated conditions exist. The eight generated figures cover hit/error trade-off, selectivity/calls/errors/timing/cost, sequence behavior, broad/medium/narrow groups and cold/warm policies.

## 14. Error analysis and label quality

The stored pilot reference-label distribution is {labels}. All labels are NO. Incorrect reuse rates of zero therefore do not demonstrate discrimination between positive and negative semantic outcomes. A human-review CSV was exported with blank human-label/notes fields; no human audit has been completed. Lexical or manually invented labels were never substituted for real reference calls. The original dataset's damaged text and null prices can affect both task interpretation and structured query populations. The pilot cannot estimate those errors.

## 15. Limitations

Every processed candidate in the main live comparison had global selectivity 1.0; the selective SQL queries were empty in this cohort. P3 therefore made zero selectivity-forced checks. Its identical call count to P2 is expected here, not evidence that the gate has no value under selective nonempty workloads. Unit/integration tests exercise selective nonempty inputs, but the real pilot does not.

Ten records, one label class, correlated/repeated queries, unverified upstream provenance, a paper-based numerical implementation and precomputed embeddings severely limit generalization. There is no completed held-out validation/test experiment or human semantic ground truth. A new exact-search fallback and posterior grid require larger-scale comparison with a verified upstream paper-v1 implementation if one becomes available. Full-dataset import and SQL inspection are complete, but runtime policy benchmarking deliberately refuses cohorts outside the approved ten records. Live run timing lacks a hardware/network-controlled repeated study; single-run latency differences are not causal evidence. Provider prompt caching, retries, changing model backends and pricing may affect later results. Mid-run RNG crash resumption is not implemented; restart with a fresh run.

## 16. Conclusion

The implemented prototype exercises the requested architecture and all policy variants on real approved inputs, with explicit inference accounting and reproducible logs. The cold pilot shows equal P2/P3 call counts and zero observed reuse disagreement in a single-class cohort. It neither confirms nor rejects the scientific hypothesis. The next research step is a representative, manually checked, disjoint validation/test study with configuration freezing before test evaluation, larger mixed-label workloads and repeated uncertainty estimates.

## 17. References

- Schroeder et al., Adaptive Semantic Prompt Caching with VectorQ, original arXiv:2502.03771v1: https://arxiv.org/html/2502.03771v1
- Official VectorQ/vCache repository and recorded historical snapshots: https://github.com/vcache-project/vCache
- Mistral Ministral 3 3B model identity and pricing: https://docs.mistral.ai/models/ministral-3-3b-25-12
- Mistral Embed identity and pricing: https://docs.mistral.ai/models/mistral-embed-23-12
- Mistral chat and embedding endpoint specifications: https://docs.mistral.ai/api/endpoint/chat and https://docs.mistral.ai/api/endpoint/embeddings
- Ollama alternative provider API: https://docs.ollama.com/api/generate
'''
    Path('reports/research_report.md').write_text(report,encoding='utf-8')
    environment=dict(python=sys.version,sqlite=sqlite3.sqlite_version,platform=platform.platform(),
                     pytest=package_version('pytest'),matplotlib=package_version('matplotlib'),numpy=package_version('numpy'),
                     tests=totals,completed_runs=len(runs),live_runtime_attempts=live_calls)
    Path('results/raw/research_environment.json').write_text(json.dumps(environment,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(environment,indent=2))


if __name__=='__main__':main()
