# Paper revision plan and implementation instructions for Sol

## Assignment

Revise the conference paper and supporting artifact in `C:\Users\unive\Desktop\pain` according to the user's reviewer-style feedback. The user asked the current agent to stop implementation and prepare this handoff for Sol. Do not treat this document as evidence that the paper has already been revised.

Read the complete feedback first:
`C:\Users\unive\.codex\attachments\658fbef4-3f29-4f2e-8883-96e854e67da1\Pasted text.txt`.

The deliverable is an evidence-based systems evaluation paper in the user's Word conference template, with a consistent README, interface, reproducibility evidence, and release ZIP. Preserve discussion and citations for all 25 works supplied in the user's project PDF. Do not invent positive results, human annotation, institutions, email addresses, or evaluation scale.

## Current state and work already performed

- The paper is still the previous five-page version, `conference_paper.docx` (38,603 bytes). Its recorded SHA-256 is `ee2d0378ba0ccc388b42879f38491d674584e044b69dc9148a39bd6baea71451`. None of the new reviewer-driven prose or formatting changes has been applied.
- An offline diagnostic script was added and completed: `scripts/calibration_diagnostics.py`. It produced 42 additional replay runs, 504 query executions, two figures, and diagnostic tables. These are exploratory post-hoc experiments on the same 96 test reviews. They are not a new held-out study or an increase in independent sample size.
- No additional API requests were made. The original frozen configuration was preserved byte-for-byte by the script.
- A document-operation marker ran before the interruption, but no document-authoring edit followed it. Follow the active document skill for the new implementation turn.
- The existing paper, README and ZIP have NOT yet been updated with this diagnostic analysis.

### New evidence to inspect and verify

| File | Content |
|---|---|
| `results/study/calibration/plan.json` | Explicit post-hoc status, seven settings, seeds, validation-derived quantiles |
| `results/study/calibration/analysis.json` | Aggregated diagnostic results and baseline derivation |
| `results/study/calibration/raw/<variant>/*.jsonl` | Full completed replay logs |
| `results/study/tables/calibration_sweep.csv` | Mean and sample SD for calls, incorrect direct hits, agreement, reduction, forced checks |
| `results/study/tables/r3_similarity_distributions.csv` | R3 event score distributions by predicate, query type and cache state |
| `results/study/tables/baseline_581.csv` | Per-query semantic stage counts summing to 581 |
| `results/study/figures/09_calibration_sweep.png` | Activation and error/call tradeoff |
| `results/study/figures/10_r3_similarity.png` | Cold R3 score empirical distributions |

Seven configurations: constant R3 thresholds 0.92, 0.96, 0.98, 0.99, 0.995 and 1.0, plus the original selectivity formula with endpoints derived from the 10th and 90th percentiles of one cold validation P2 trajectory. All use three seeds and cold/warm states, retain the frozen posterior settings, and run through the real executor rather than rescoring decisions in isolation.

Validation quantiles are 0.9676635929526995 and 1.0, from 206 R3 events in `offline-P2-cold-fixed-0-95a788041311`. Quantile levels and the diagnostic design were chosen after inspecting the original test result: using validation scores does not make this a retrospectively confirmatory experiment.

Selected diagnostic results (mean ± sample SD across three seeds):

| Setting | State | Simulated calls | Incorrect direct hits | Complete query row set agreement | Forced checks |
|---|---|---|---|---|---|
| Constant 0.92 | cold | 338.7 ± 77.5 | 27.0 ± 15.7 | 52.8% ± 21.0 pp | 0 |
| Constant 0.92 | warm | 230.7 ± 35.3 | 15.3 ± 9.6 | 61.1% ± 21.0 pp | 0 |
| Constant 0.98 | cold | 492.0 ± 6.6 | 4.7 ± 1.5 | 75.0% ± 8.3 pp | 94.0 ± 6.2 |
| Constant 0.98 | warm | 321.7 ± 8.7 | 1.3 ± 2.3 | 97.2% ± 4.8 pp | 59.0 ± 2.0 |
| Constant 0.99 | cold | 548.3 ± 1.5 | 0 | 100% ± 0 pp | 157.0 ± 0 |
| Constant 0.99 | warm | 397.3 ± 9.5 | 0 | 100% ± 0 pp | 175.0 ± 0 |
| Validation quantile range | cold | 447.0 ± 2.0 | 18.3 ± 0.6 | 52.8% ± 4.8 pp | 119.7 ± 1.2 |
| Validation quantile range | warm | 335.0 ± 15.6 | 7.3 ± 2.3 | 58.3% ± 8.3 pp | 84.0 ± 19.1 |

Use the source CSV values when building tables. A constant threshold of 0.99 saves 5.6% cold and 31.6% warm calls relative to 581; it is not a selectivity-dependent method. Do not claim it is an optimal setting. The quantile method activates, but activation does not establish an advantage from selectivity. A 1.0 threshold can also be sensitive to floating-point cosine scores for identical inputs; acknowledge this if interpreting that endpoint.

## Recommended scientific framing

Choose a calibrated negative-result study with a reusable evaluation framework as the contribution. Do not present the inactive original method as an effective optimization.

Suggested title: **Calibration of Selectivity Aware Semantic Reuse in Hybrid SQL and Language Model Pipelines**.

The central finding is specific: the original selectivity-aware reuse threshold is inactive because its upper bound lies below every observed R3 candidate score in the controlled main replay. The new sweep demonstrates where interventions begin and their quality/cost consequences. A score-calibrated range can activate the method, but these results do not identify a benefit attributable to selectivity beyond ordinary threshold calibration.

State the analytical mechanism explicitly. For similarity z and selectivity s, an extra check is possible only for an R3 candidate with z < tau(s). If tau(s) <= tau_max < min(z over all encountered R3 candidates), activation is impossible. Given the same initial state, seed and reference oracle, P2 and P3 then follow the same decisions and learning trajectory. This conditional invariance explains the observed equality; it is not a theorem that selectivity never helps. Check the policy's RNG and short-circuit behavior before presenting the trajectory argument.

Use event-level R3 distributions for this argument. The old pairwise means around 0.962–0.964 are not distributions of actual reuse opportunities. In the completed main replay, the minimum pooled cold R3 score is about 0.94719 and warm about 0.95461, both above 0.92. Report per-predicate and query-type quantiles with event counts; pooled events are dependent, not independent samples.

## Ordered implementation plan

### 1. Validate the diagnostic evidence before writing claims

1. Read `scripts/calibration_diagnostics.py` and the original executor/policy logic.
2. Verify all 42 completed runs, three seeds per state/setting, consistent model/prompt/cohort identities, and zero actual requests.
3. Confirm constant 0.92 reproduces the main P2/P3 metrics and forced-check counts are positive for active settings.
4. Recompute representative aggregation rows from raw logs. Check that SD is sample SD and agreement SD is displayed in percentage points.
5. Confirm the original freeze payload and original main logs were not modified. The new plan field named `original_freeze_sha256` currently hashes the entire freeze file (`84639ff9c33dc29bdd4c88c464760d5df5710c6adb7f85ee990b35de443628b4`), whereas the existing freeze's embedded payload digest is `07e40272507623d4149be4633a7cf42eee5ae291dd5bc2990ce0b5def1da5ff7`. Rename the new field to `original_freeze_file_sha256` and record the payload digest separately to avoid confusion.
6. Improve script provenance/resume checks if needed: ensure existing runs match the full intended configuration, log exact settings and validation source, and do not overwrite historical main outputs. The current script uses `load_config`, which may load environment variables, but explicitly invokes `mode='offline'`; do not add live behavior.
7. Do not rerun completed expensive work merely to get different timings. Existing diagnostic results are already sufficient for the requested threshold analysis.

### 2. Rewrite the paper around the mechanism and evidence

Use approximately this outline, adjusting section count to the supplied template:

I. Introduction — problem, calibration gap, contributions, headline finding.

II. Background and Related Work — prioritize VectorQ/vCache, semantic caching and semantic-operator systems. Retain meaningful citations to all 25 supplied works, while compressing broad surveys and secondary SQL-tuning context. The less central BOHR paper should be framed as adjacent work, not authority for the proposed method or a measured comparator.

III. Selectivity Aware Reuse — hypothesis, formula, R3-only intervention, conditional inactivity argument.

IV. System Design — SQL-first executor, cache isolation, audits and shared policy evaluation. Move low-level implementation details and history to artifact documentation.

V. Experimental Methodology — dataset, model references, policies, workload, freeze protocol, metrics, replay versus live, and explicit post-hoc diagnostic protocol.

VI. Results — seven-policy replay with uncertainty; exploratory live observations and runtime; threshold sweep and score distributions. Alternatively use a dedicated following section titled Why the Threshold Is Inactive if it improves readability.

VII. Limitations — sample size, challenge sampling, model references, one dataset, repeated workload, provider variability, prepared embeddings and post-hoc design.

VIII. Conclusion and Future Work — score calibration is necessary for this intervention to operate; a selectivity-specific advantage remains unestablished.

Abstract: problem → VectorQ-based approach → 64/96 challenge cohorts and model-generated references → inactive frozen threshold and activation demonstrated by post-hoc sweep → bounded implication. Avoid cramming every baseline number into it. Distinguish the original 110 replay runs from the added 42 diagnostic runs and five live conditions.

Standardize primary terms:
- **selectivity-aware reuse threshold**;
- **simulated inference calls** for replay;
- **API request attempts** for live accounting;
- **incorrect direct hits**;
- **complete query row set agreement** (define a short table label once).

State each limitation precisely once where it affects interpretation, then avoid repeated defensive sentences.

### 3. Make scale and reference validity explicit

The study is a controlled challenge/stress workload on real review text, not a production traffic trace. It uses 64 validation and 96 test reviews, three tasks, and 12 query plans. The original 110 replay runs correspond to 1,320 measured query executions; the new 42 runs add 504. Repeated execution does not create 1,824 independent queries or enlarge the corpus. Reverse and shuffled orders test sequence sensitivity, not independent datasets or representative traffic distributions.

The bounded study budget permits mechanistic analysis, not broad external-validity claims. This is the justification for retaining the small cohort in this revision. Do not pad the experiment with duplicated queries to satisfy an apparent sample-size target.

References are Mistral `ministral-3b-2512` outputs with the corrected v2 task prompt. Embeddings are `mistral-embed-2312`. Human accuracy is unknown. The previous 24-pair validation check was performed by an assistant: 20 agreements among 22 scorable examples, two ambiguous, with two apparent sarcasm disagreements. It is not independent human verification and must not be described as such. Ambiguities were documented, not adjudicated into a human gold standard.

If preparing the next study, create a blinded human-annotation protocol and sample manifest with separate independent annotator labels, ambiguity flags, adjudication and provenance. Do not fill human columns with model judgments. Human work remains an external dependency. A fresh larger/multiple-dataset study requires its own selection plan, label/embedding budget, validation freeze, and untouched test set. Keep this future study clearly separate from the current revised paper.

### 4. Explain the 581 denominator visibly

Use `baseline_581.csv` for a compact table or explicit derivation:

| Query | Semantic-stage inputs | Calls |
|---|---|---|
| broad shipping | shipping 96 | 96 |
| broad defect | defect 96 | 96 |
| broad sarcasm | sarcasm 96 | 96 |
| low shipping | shipping 49 | 49 |
| low defect | defect 49 | 49 |
| rating 3 sarcasm | sarcasm 16 | 16 |
| cheap shipping | shipping 12 | 12 |
| expensive defect | defect 12 | 12 |
| empty shipping | shipping 0 | 0 |
| low defect then shipping | defect 49, shipping 20 | 69 |
| repeated low shipping | shipping 49 | 49 |
| high sarcasm then defect | sarcasm 31, defect 6 | 37 |

Total = 581. One simulated inference per input to each semantic stage, with earlier reference labels determining later-stage survivors. There are three distinct predicates, 12 plans and 14 declared semantic stages, one of which receives zero rows. Different cached outputs can change later-stage input counts; do not assume every policy processes exactly 581 candidates. Call reduction is 100 × (581 − calls)/581 for this measured workload.

### 5. Tables, uncertainty, runtime and typography

- Report mean ± sample SD over seeds in all replay result tables. Existing `analysis.json` / `tables/policy_means.csv` already contain main-run SDs. The diagnostic CSV contains the new SDs.
- Include call reduction, either as a column or in adjacent prose, with its denominator defined. Use compact tables that remain legible in two columns rather than squeezing seven long columns into one.
- State that seed dispersion is conditional variability on one corpus, not population confidence. Do not manufacture live confidence intervals from one run per condition.
- Put captions above tables as TABLE I, TABLE II, etc.; define every abbreviation below the table.
- Add a runtime table from `tables/live_runs.csv`: measured pipeline time (`total_query_seconds`), inference time (`llm_seconds`), cache search time (`search_seconds`), prepared-vector retrieval time (`embedding_seconds`), and optionally policy processing. Inspect definitions in `src/evaluation/metrics.py` before claiming component sums; some timing fields overlap.
- Explain that these are measured query-pipeline totals excluding warmup and preparation, not full online embedding deployment latency. Prepared-vector retrieval is not embedding API encoding time. Three live conditions could run concurrently, so timing comparisons are exploratory.
- Move the five live conditions into a clearly labelled exploratory subsection. Warm P2/P3 differences cannot be attributed to an inactive threshold; one no-cache live reference output also changed.
- Fix headings with proper Word numbering definitions: uppercase Roman main sections, alphabetical subsections restarting under each section. Current style/template preservation left erroneous continuous numbering visible; preserving that defect is not a requirement.
- Remove bold from reference entries explicitly, including inherited style formatting. Keep consistent arXiv versions, venue details, DOI formatting, and access dates for online documentation/repositories.
- Cite a precise inspected repository revision. Preserve the distinction between a paper-v1 reimplementation and the later vCache implementation; do not imply upstream code was the executed baseline.

### 6. Keep the interface and artifact consistent

- Update README with the new framing, diagnostic reproduction command, separate result counts, newly added figures/tables and remaining evidence gaps.
- Add a visibly labelled exploratory calibration view or section to the local interface. At minimum expose the new plots and downloadable tables, preserving the original main comparison. Verify that current figure/table discovery includes the new files; do not silently merge diagnostic runs into the 110-run held-out list.
- Update the narrative report or clearly mark it as the original study report with a link to the new supplement; avoid contradictory claims across downloads.
- Rebuild `vectorq-sql-cache.zip` only after the paper and documentation are finalized. Ensure new evidence and revised sources are included and credentials excluded. Audit manifests and file hashes rather than relying on an old acceptance record.
- Provide a concise revision checklist mapping each reviewer issue to the changed section/evidence and explicitly mark human annotation, multiple datasets and expanded live replication as unresolved or future work.

## Important files and commands

Primary authoring sources:
- `scripts/build_conference_paper.py` — fills the original Strict OOXML template.
- `scripts/conference_literature.py` — related-work prose and bibliography loader.
- `research/conference_literature.json` — all 25 supplied references, verification provenance and corrected citations.
- `research/conference_crossref_metadata.json` — existing metadata evidence.
- `research/vectorq_source_manifest.json` — implementation/source provenance.

Existing study and UI:
- `scripts/study.py`, `scripts/analyze_study.py`, `scripts/analyze_results.py`.
- `src/vectorq/policy.py`, `src/controller/selectivity.py`, `src/evaluation/runner.py`, `src/evaluation/metrics.py`.
- `scripts/serve_dashboard.py`, `ui/index.html`, `ui/app.js`, `ui/style.css`.
- `reports/final_report.md`, `scripts/build_final_report.py`, `scripts/package_project.py`.
- `results/study/frozen_configuration.json`, `analysis.json`, `label_quality.json`, `live_reference_variation.json`, `tables/`, `test/raw/`, `live/raw/`.

Template and author source:
- `C:\Users\unive\Downloads\1_ConferenceTemplate.docx`.
- `C:\Users\unive\Downloads\25BCE2252_VL2026270103340_AST06 (1).pdf`.
- Authors: Nandana Raj, Harshit Gupta, Vaishnavi Ganesan. Degree: B.Tech. in Computer Science and Engineering. Guide: Dr. Saritha Murali (acknowledgment). Institution and emails are unverified; do not invent them.

Application Python: `.venv-check\Scripts\python.exe`.

Diagnostic reproduction (offline only, existing completed configurations are skipped):
```powershell
.\.venv-check\Scripts\python.exe -m scripts.calibration_diagnostics
```

Use the workspace dependency loader to resolve bundled Python/Node for DOCX authoring. The known Python path is:
`C:\Users\unive\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.

Build the paper from the supplied template:
```powershell
& 'C:\Users\unive\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -m scripts.build_conference_paper --template 'C:\Users\unive\Downloads\1_ConferenceTemplate.docx'
```

Do not assume the current builder is ready: it still contains the old paper body and must be edited first. It uses lxml because python-docx does not directly support this Strict OOXML template. Existing build checks assert that nonedited parts, including numbering/styles, remain identical; deliberately update those checks if fixing numbering/styles requires changing them. Record intentional changes rather than bypassing validation.

## Document verification and acceptance

1. Read the active documents skill and follow its authoring marker and render requirements. Use the user template as the design authority.
2. Attempt the canonical renderer. Prior attempts failed because of Strict OOXML handling and unavailable bundled LibreOffice on Windows. Diagnose current failures before falling back.
3. Previously successful fallback: native Word COM `ExportAsFixedFormat(..., 17)` to a temporary PDF, then bundled PDFium rendering at scale 1.65. Hidden Word avoids interrupting the user. Escalate only as required by the tool environment.
4. Inspect every rendered page, including tables, heading numbers, captions, references and equation. Text extraction alone is insufficient. Rerender after layout edits.
5. Update `results/study/conference_paper_build.json`, `conference_paper_qa.json`, and `conference_citation_audit.json` for the actual new document. Do not carry over the previous all-pages-checked claim or hashes.
6. Confirm all 25 supplied works have relevant in-text citations and every bibliography number resolves. Existing `tmp/conference/check_citations.py` expects 29 total references; adjust only if the actual bibliography changes. Keep numbering ordered by first appearance.
7. Verify final counts, calculations, uncertainty units and post-hoc labels against logs. Ensure no sentence says the method generally proves selectivity ineffective or that calibration establishes human semantic accuracy.
8. Run relevant existing tests for any policy/UI code changes; do not add trivial document tests solely to increase test count. Previous suite had 121 passing tests, not a guarantee for changed code.
9. Verify the final archive contents and current hashes; do not include `.env`, API keys, Word temporary files, or QA render intermediates as deliverables.
10. Final user response should state what was revised and what empirical gaps remain, with a link/citation to the finished paper and updated package.

## API and research boundaries

The user's existing authorization is limited to the original pilot and 160-review study. The main label allowance of 960 attempts is exhausted. Corrected embeddings were explicitly approved up to 960 inputs across old/corrected versions. Live runtime ledger currently shows 2,779 of 3,000 attempts used, leaving 221. Do not reset counters or run an expanded live suite under that allowance. Do not expose `.env` contents in tools or prose.

The current requested paper revisions can be implemented with existing offline evidence. If proposing a larger live or additional-dataset study, first prepare the exact records/cohorts, experiment design and bounded request budget, then obtain any required additional authorization. Never fabricate human review or claim extra corpus diversity from repeated execution.

## Completion criteria

The revision is complete when the paper foregrounds the calibration mechanism; reports an active threshold sweep and distributions with correct exploratory status; includes main replay uncertainty, the 581 derivation and exploratory runtime evidence; fixes visible IEEE formatting and citations; preserves all supplied literature; and updates README/interface/package consistently. Human-verified accuracy and broader dataset generalization must remain candidly identified as outstanding research work unless actually obtained.
