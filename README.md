# Calibration of Selectivity Aware Semantic Reuse in Hybrid SQL and Language Model Pipelines

A Python research application with a real CSV-to-SQLite importer, SQL-first hybrid executor, configurable Mistral/Ollama inference, a paper-v1 VectorQ implementation, separate selectivity controllers, seven shared-runner policies, frozen validation/test experiments, a local dashboard, raw logs, tables, graphs, a detailed PDF report and a conference-format Word paper.

Start with **conference_paper.docx** and **reports/calibration.md** for the current research argument. The contribution is a calibration diagnosis and an auditable evaluation framework. The original selectivity-aware reuse threshold stayed inactive: its 0.92 ceiling was below all encountered R3 scores. A separate post-hoc sweep demonstrates active thresholds and their quality/cost tradeoffs. A selectivity-specific advantage remains unestablished.

The study uses model-generated references on a small challenge cohort. Human-verified accuracy, multiple-dataset generalization and replicated isolated live runtime remain outstanding empirical work. **research_report.pdf** and **reports/final_report.md** retain the original study with an explicit scope notice pointing to the new supplement.

## Open the interface

For a fresh GitHub checkout, the dataset and prepared cohort databases are included inside `vectorq-sql-cache.zip`. Extract that complete project into a separate folder first (PowerShell):

```powershell
Expand-Archive -LiteralPath .\vectorq-sql-cache.zip -DestinationPath .\prepared-project
Set-Location .\prepared-project\vectorq-sql-cache
```

Then follow the dependency setup below. The repository keeps working databases, credentials and temporary files out of Git history; the ZIP contains clean, reproducible cohort snapshots and the original CSV.

After installing the dependencies below, run from the project directory:

```bat
python -m scripts.serve_dashboard
```

Open **http://127.0.0.1:8765** in a browser. If that port is occupied, run `python -m scripts.serve_dashboard --port 8766` and use the corresponding URL. Stop the server with Ctrl+C.

The local interface provides:

- Study overview and the measured primary finding.
- All seven replay policies, selectable cold/warm states, and the separate live comparison.
- Every completed test/live run, including order variations and ablations, with its settings and measured summary.
- Query filtering stages, row counts, global/stage selectivity, output agreement and extra/missing rows.
- Paginated cache events filtered by query and decision, with similarity, reason and output/reference labels.
- A separate exploratory calibration section with seven threshold settings, mean ± sample SD, cold/warm switching and score plots.
- All ten figures, downloadable metric CSVs, the frozen configuration, workload, paper, original detailed report and this README.

The dashboard is read-only, binds to this computer's loopback address, uses no external web assets and makes **no Mistral requests**. It never loads `.env`. Starting it reads saved results; it does not rerun experiments or spend the remaining budget. Restart it after generating new logs. The table means come from the latest saved analysis, so regenerate figures/tables after an intentional new replay before comparing newly created runs. The run explorer includes ablations; check the displayed variant/settings before treating one as the primary configuration.

## What was compared

| Evidence | Policies | Executed scope |
|---|---|---|
| Controlled saved-reference replay | P0–P6, all seven | 42 main runs: seven policies × cold/warm × three seeds; 28 alternate-order runs; 40 one-factor runs; 110 total |
| Post-hoc calibration replay | Seven R3 threshold settings, P3 executor | 42 additional runs: seven settings × cold/warm × three seeds; 504 measured query executions on the same test reviews |
| Live Mistral API | P0/P2/P3 cold, P2/P3 warm | Five measured conditions, plus separately recorded warmup |

The proposed selectivity controller was therefore compared with **more than VectorQ**. P2 versus P3 is the primary paired hypothesis test, while no cache, static similarity, reverse gating, extra auditing and exact-key caching provide context. P2 is a paper-v1 reimplementation, not the current official vCache runtime.

Main replay P2/P3 means are identical: 338.7 simulated cold calls and 27.0 incorrect direct hits; 230.7 warm calls and 15.3 incorrect hits. The no-cache denominator is 581 calls. The added gate forced zero checks across the six main seed/state conditions. Exact-key P6 preserved every reference result set, with 288 cold calls and zero warm measured calls on this repeated-input workload. These are fidelity results against saved model labels, not human semantic accuracy.

## Calibration analysis and its limits

The original 110 replay runs comprise 1,320 measured query executions over 12 query plans. The new 42 diagnostic runs add 504 executions, **not new independent reviews**. Both suites repeatedly use the same 96 test reviews; there are 64 disjoint validation reviews. The query plans stress broad, selective, empty, repeated and multi-predicate cases rather than estimate production traffic.

An extra P3 check requires an R3 score `z < tau(s)`. Because `tau(s) <= tau_max`, scores above the upper bound make activation impossible. With matched initial state, row order, oracle and sampling streams, an inactive threshold produces the same trajectory as P2. The main R3 minima are 0.947187 cold and 0.954605 warm, above 0.92.

The diagnostic sweep uses constant thresholds 0.92, 0.96, 0.98, 0.99, 0.995 and 1.0, plus a selectivity rule with validation q10/q90 endpoints 0.967664 and 1.0 (206 validation R3 events). The design and quantile levels were chosen **after the original test result was known**; validation-derived endpoints do not turn this into a fresh held-out claim. The original freeze is unchanged.

| Setting | State | Simulated calls, mean ± SD | Incorrect direct hits, mean ± SD | Query set agreement, mean ± SD |
|---|---|---|---|---|
| Constant 0.92 | cold | 338.7 ± 77.5 | 27.0 ± 15.7 | 52.8% ± 21.0 pp |
| Constant 0.99 | cold | 548.3 ± 1.5 | 0.0 ± 0.0 | 100.0% ± 0.0 pp |
| Constant 0.99 | warm | 397.3 ± 9.5 | 0.0 ± 0.0 | 100.0% ± 0.0 pp |
| Quantile selectivity | cold | 447.0 ± 2.0 | 18.3 ± 0.6 | 52.8% ± 4.8 pp |
| Quantile selectivity | warm | 335.0 ± 15.6 | 7.3 ± 2.3 | 58.3% ± 8.3 pp |

SD is sample standard deviation over three seeds; percentage SD is in percentage points. This is conditional seed variability, not population confidence. Constant 0.99 saves 5.6% cold / 31.6% warm calls relative to 581. It is a calibration control, not an optimal-setting claim or a selectivity-dependent method. The quantile rule activates but still changes reference result sets. Full results, per-predicate and per-query-type score distributions, and the explicit 581-call derivation are in `reports/calibration.md` and the new CSV tables.

Validate/resume the diagnostic evidence and regenerate its tables and plots without API requests:

```bat
python -m scripts.calibration_diagnostics
python -m scripts.report_revision
```

Completed compatible runs are reused. Changed model, prompt, workload, policy, cohort, seed or live evidence is rejected rather than silently mixed. The file hash and embedded payload hash of the original freeze have distinct fields. `results/study/calibration/verification.json` records raw-aggregate checks, zero API attempts, 42-run coverage and event-level equality of the 0.92 control to P2. `reports/revision_checklist.md` maps reviewer issues to evidence and remaining gaps; `reports/human_annotation_protocol.md` specifies the next human-label study.

## Conference paper and detailed report

`conference_paper.docx` is the concise research paper built from the supplied `1_ConferenceTemplate.docx`: A4, two-column body, original conference typography, corrected Roman section/alphabetic subsection numbering and numbered references. It uses the team names from the supplied project PDF: Nandana Raj, Harshit Gupta and Vaishnavi Ganesan, and acknowledges faculty guide Dr. Saritha Murali. The PDF did not supply an institution or email, so those details are omitted. Add verified affiliations and contact information before conference submission.

The revised five-page paper foregrounds the inactivity condition and includes the active post-hoc sweep, R3 score quantiles, mean ± SD replay tables, the 581-call derivation, exploratory live runtime and reference-label limitations. Its related-work discussion uses **all 25 works from the supplied project PDF**, covering learned optimization, text-to-SQL, hybrid semantic queries, caching, vector search and serving. The bibliography contains 29 entries including the original VectorQ version, official repository and two model documentation sources. Citations are numbered by first appearance. `research/conference_literature.json` records supplied entries, primary-source links and corrections; `results/study/conference_paper_build.json` maps the PDF's reference numbers to the paper's numbers. The final PURPLE author order and vector-database tutorial DOI were corrected against primary metadata. Literature coverage does not mean those systems were run as experimental baselines.

`research_report.pdf` and `reports/final_report.md` retain the longer original evidence report with a prominent scope notice. `reports/calibration.md` is the current diagnostic supplement; the conference paper contains the revised scientific framing and literature discussion. Download both formats from the interface. The original template is not redistributed in the project archive.

To regenerate the Word paper, install the optional document dependency and provide the original template path:

```bat
python -m pip install -r requirements-documents.txt
python -m scripts.build_conference_paper --template "C:\path\to\1_ConferenceTemplate.docx"
```

This optional document builder changes only the intended content parts and preserves the template's styles, relationships and other untouched parts byte-for-byte. Dedicated Roman section and per-section alphabetic subsection numbering definitions are appended intentionally; the original numbering definitions are retained. Captions and references have explicit formatting corrections. `lxml` is a document-authoring dependency, not required for the dashboard or experiments. The delivered paper was rendered in Microsoft Word and visually checked; regenerated copies should be rendered and checked again. Building the existing detailed report with `scripts.build_final_report` does not overwrite the conference paper.

The original interface suite passed 121 tests (`results/study/interface_tests.xml`). The revised suite passes **123 tests**, including calibration provenance and separation checks; current evidence is in `results/study/revision_tests.xml`. This includes completed-run filtering, pagination, measured/warmup separation and HTTP checks that private files and traversal paths are not served. Browser checks also covered policy/state switching and query/decision filters. No new provider requests were needed for the interface or paper.

## Windows CMD: clean setup

Python 3.14.7 was used for the executed clean-environment check. Open Command Prompt in the project directory:

```bat
cd /d C:\Users\unive\Desktop\pain
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-lock.txt
python -m pytest -q --junitxml=results/study/clean_setup_tests.xml
```

`requirements.txt` pins direct dependencies; `requirements-lock.txt` pins the exact tested transitive environment. Actual test results and the seven-policy fresh-environment real-data smoke check are recorded in `results/study/clean_setup_tests.xml` and `clean_application_smoke.json`. No API requests occur during pytest.

Copy `.env.example` to `.env` and fill `MISTRAL_API_KEY` only for new live requests. Existing environment variables take precedence. `.env`, virtual environments and SQLite working files are ignored. Do not paste keys into chat or commit them. Saved configs contain only the environment variable's name.

## Reproduce the saved held-out study without API calls

The supplied workspace includes the real CSV, versioned prepared databases, reference labels, embeddings and frozen settings. Run:

```bat
python -m scripts.run_benchmark --config config/study.json
python -m scripts.plot_results
python -m scripts.build_final_report
```

The first command runs **all P0-P6** through the same executor with independent cold/warm caches, three sampling seeds, alternate query orders and one-factor ablations. It reuses saved labels/vectors and makes zero API calls. New run IDs prevent inherited state. Raw JSONL is retained for every run; incomplete runs without a final summary are excluded from analysis. Repeated runs take several minutes depending on storage and CPU.

None of the ten validation trials met the predeclared <=2% reuse-error and >=90% result-agreement targets; the documented fallback selected the settings. No error-bound guarantee is claimed.

The frozen settings are checked by SHA-256 before test execution. Do not re-tune after viewing test results. A deliberate new study needs a new validation/test plan and a separate freeze. The saved seed/order/settings permit replay of decisions; timings naturally vary. Interrupted cache runs restart with a new run ID rather than resuming a random stream mid-run.

## Rebuild from the unchanged source CSV

```bat
python -m scripts.prepare_data --config config/default.json
python -m scripts.verify_dataset --config config/default.json
python -m scripts.prepare_study --config config/default.json
python -m scripts.study_inputs --config config/study.json --stage labels
python -m scripts.study_inputs --config config/study.json --stage embeddings
python -m scripts.study tune --config config/study.json
python -m scripts.run_benchmark --config config/study.json
python -m scripts.plot_results
python -m scripts.build_final_report
```

**The two `study_inputs` stages send selected review text to Mistral and incur API usage.** They resume successful saved inputs rather than regenerating them. Existing failed labels require diagnosis before another attempt. The completed study's label budget was 960 attempts including the rejected prompt-v1 run; corrected embeddings had an additional 480-input allowance. A persistent embedding reservation file prevents exceeding that corrected-input cap. Network interruptions can leave uncertain setup usage, which is not assumed free. Rebuilding independently requires your own API key and budget; saved references and embeddings are the inexpensive replay path.

A fresh label-only generation command for the original dataset also exists:

```bat
python -m scripts.generate_labels --limit 10
```

That legacy command uses prompt v1 and is retained for audit/reproduction of the initial pilot. The main study uses **config/study.json and prompt v2** instead. Do not mix those references.

## Live held-out primary comparison

```bat
python -m scripts.run_benchmark --config config/study.json --live
```

This calls Mistral for P0/P2/P3 cold and P2/P3 warm. Each warm condition includes a separately logged population pass. Three independent conditions can run concurrently; inference within each cache remains sequential. The persistent `results/study/live_runtime_budget.json` reserves attempts before transmission and enforces the shared 3,000-attempt cap across conditions and invocations. Re-running spends additional remaining allowance and is not needed to inspect saved results. Do not erase the ledger to bypass its budget.

Live timings include network/server contention between those three conditions and are exploratory rather than isolated service benchmarks. Main scientific call/error comparisons use common saved-reference replay. Both modes use the same **precomputed embeddings**, so measured embedding time is vector retrieval. Offline encoding latency/cost is separate and must be included in any deployment cost model. No local-LLM monetary savings are invented.

## Dataset and split provenance

The real user-supplied `Dataset.csv` has 363,261 rows with `Product_name,Price,Rate,Review,Summary`. Inspection established that `Summary` contains the longer body and becomes `review_text`; `Review` is the headline and becomes canonical `summary`. The supplied file's upstream publisher, license, release and Amazon provenance are unknown. Source SHA-256 and cleaning/version manifests are saved instead of inventing provenance.

Cleaning trims outer whitespace, turns blank cells into null, drops missing bodies, deduplicates canonical records and creates content-derived stable IDs. Optional fields remain null. Numeric parsing accepts only configured currency prefixes, valid thousands groups, finite nonnegative prices and ratings in 1-5; invalid values become null with quality counts. The configured Latin-1 interpretation preserves bytes but cannot repair existing text corruption. The raw CSV is never rewritten. Re-imports of identical source/config are idempotent; changed bytes or cleaning settings create a new dataset version. See `reports/phase1.md` and `data/processed/import_report.json` for full counts.

The main challenge cohorts have **64 validation and 96 test reviews**. Normalized review-body hashes define disjoint groups before selection. Pilot bodies are excluded. Eligibility is 20-1,200 characters, with no truncation. Eight strata cover cheap low-rated, expensive low-rated, shipping cues, defect cues, sarcasm cues and remaining low/medium/high reviews. Each stratum contributes 8 validation and 12 test records. This enrichment supports varied workloads but is not prevalence-representative. Lexical cues select records and never generate labels. Manifests record every selected ID, text hash, stratum, parent version and seed.

## Labels, model choice and quality

Mistral `ministral-3b-2512` was selected as the small, low-cost inference model, with `mistral-embed-2312` embeddings. A small model does not inherently reduce input tokens: short instructions and a four-token response cap control usage. Full review text is retained. Standard configured prices checked on 26 October 2026 are $0.10/M input/output LLM tokens and $0.10/M embedding input tokens; estimates use provider-reported usage and are not billing statements.

Prompt v1 returned NO for explicit malfunction examples. Those requests are preserved but excluded from the main study. Version v2 puts the task and review together in the user message, producing mixed labels. Inference uses temperature 0, seed 17, exact YES/NO validation and one attempt per request in the final study. Determinism is not guaranteed by the remote provider. Ollama is supported through the same interface but was tested with local transport doubles, not a live local model.

Reference keys include dataset, review, task, prompt and model-configuration identity. Changed task text without a new version is rejected. Labels are the selected model's outputs, not guaranteed human truth. A seeded 24-pair validation-only quality sample is saved in `data/reference_labels/validation_audit.csv`: an assistant spot-check found 20 agreements among 22 scorable cases and two ambiguous boundaries. It is explicitly **not independent human annotation**; apparent sarcasm errors remain documented. A human can inspect/adjudicate that file separately without overwriting model references.

## Policies and VectorQ fidelity

| ID | Policy |
|---|---|
| P0 | No cache |
| P1 | Validation-tuned fixed similarity threshold |
| P2 | Original-paper VectorQ, three-region reimplementation |
| P3 | VectorQ plus selectivity-aware reuse threshold in R3 |
| P4 | VectorQ plus reverse-direction R3 gate |
| P5 | VectorQ plus selectivity-dependent R3 audits |
| P6 | Exact predicate/prompt/input key |

P2 follows Algorithms 1 and 2 in **arXiv:2502.03771v1**, retaining R1 rejection, R2 checking, R3 correctness sampling, posterior updates and monotone region correction. The continuous posterior uses a convergence-tested 1,001-point log-space grid with trapezoidal normalization. The explicit integral equation is followed despite conflicting prose about density bounds. Default decay 10 is documented. Exact NumPy float64 cosine search is the development fallback, not approximate nearest-neighbor search; negative scores are clipped to zero for the paper's domain.

The official repository at `50694eebf0c870231030f73707cb6543d47f0411` implements later vCache. Inspected historical `2c99678e9ed3934a0ef0b07789acd34b67f77a79` has unfinished posterior methods, while `fca83c4d6822f329aad6bfd619a855718fc020e9` implements a different logistic Bayesian policy. Downloaded sources/hashes are in `research/vectorq_source_manifest.json`. This is a **tested paper-based implementation**, not a byte-identical upstream reproduction or a claim that an upstream three-region test suite passed.

P3's threshold is `tau_min + (tau_max-tau_min)*(1-s)^gamma`. It only adds checks within R3; R1/R2 are unchanged. P4 uses `s^gamma`; P5 changes additional audit frequency. Audits always count as inference and never direct hits. Cache namespaces isolate dataset, predicate, prompt, LLM settings, embedding model and run.

## Metrics and artifacts

SQL and semantic stages log total/input/output rows, global and stage-local selectivity and elapsed time. Events record nearest-neighbor score, region, reason, checks, calls, correctness and timings. Empty SQL results make no embedding/LLM calls. SQL columns/operators are allowlisted and values parameterized. Failed inference or persistence never yields fabricated success, and an inference already completed before a failed cache write remains counted.

Incorrect reuse is incorrect direct hits/all direct hits; zero-hit rates remain undefined. Call reduction uses the matching no-cache denominator. Final row-set agreement and included/excluded IDs are separate from cache-decision errors and from unknown human semantic truth. Offline calls are simulated; actual request attempts, tokens, warmup and setup remain separate.

- `results/study/validation/raw/`: validation trials.
- `results/study/frozen_configuration.json`: selected settings, objective, trials and SHA-256.
- `results/study/test/raw/`: held-out seeds, orders and ablations.
- `results/study/live/raw/`: actual primary-comparison requests and warmup.
- `results/study/tables/`: policy metrics, exact denominators, query groups, paired differences and conditional seed intervals.
- `results/study/figures/`: eight original graphs and two exploratory calibration plots.
- `results/study/calibration/`: separate post-hoc plan, raw logs, analysis and verification.
- `reports/calibration.md`: complete calibration tables, score distributions and denominator derivation.
- `results/study/acceptance.json`: acceptance checklist linked to evidence.
- `research_report.pdf` and `reports/final_report.md`: measured findings and limitations.

The initial 10-review pilot remains under `results/raw/` and historical reports; it is not pooled into the held-out results. The main report separates reference-model fidelity from semantic truth, reports negative findings, and does not claim a general selectivity advantage.
