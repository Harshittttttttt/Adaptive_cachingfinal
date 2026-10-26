# Adaptive Semantic Caching with VectorQ for Hybrid SQL–LLM Query Pipelines

Research question: does live SQL selectivity improve the correctness/call-cost trade-off of VectorQ? The prototype includes the data importer, structured SQL-first executor, Mistral/Ollama clients, persistent reference labels, paper-v1 VectorQ reimplementation, separate selectivity controllers, seven cache policies, cold/warm offline and live pilot runner, development ablations, tables and eight figures. **Executed experiments use a separate 10-review development pilot. A validation-tuned, held-out final research experiment has not been completed.**

## Windows CMD setup

Open Command Prompt in this project folder. Python 3.11+ is intended; the actual Phase 1 run used Python 3.14.7 and pytest 9.1.1.

```bat
cd /d C:\Users\unive\Desktop\pain
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m src.data.load_reviews --config config/default.json
python -m scripts.verify_dataset --config config/default.json
```

All relative dataset/config paths resolve against the current working directory, so run from the project root. Import is deterministic and idempotent. The verification command creates a separate reconstruction database and compares every ordered cleaned record by SHA-256. It also checks repeat import, integrity, foreign keys, numeric SQL filtering and an empty filter. On this dataset the import can take approximately a minute; exact timings depend on storage.

## Dataset and configuration

The primary dataset is the real user-supplied `Dataset.csv` in the project root. It has 363,261 data rows with `Product_name,Price,Rate,Review,Summary`. No upstream publisher, license, release or Amazon provenance was supplied; these remain unknown. Do not describe it as Amazon data without supporting provenance.

All settings are in `config/default.json`. To use another CSV, set `dataset.path`, `name`, `source`, `encoding` and `columns`; keep a separate dataset name and source path for additional experiments. Optional columns can map to null. Only the review body column is required. Aliases are detected when mappings are omitted, and ambiguity fails with a useful error. Explicit mappings are required for differing field meanings.

For this file, `Summary` contains the longer review body and becomes `review_text`; `Review` contains its short headline and becomes `summary`. Product, price and rating map to their corresponding columns. Category is absent and stays null.

The file fails strict UTF-8 decoding. Latin-1 is an explicit **byte-preserving interpretation**, not a claim about the original text encoding. Existing corrupted characters remain visible in stored text. No characters are silently replaced, and the original file is never rewritten. Configured price prefixes include the observed `U+009F??` sequence; other damaged prefixes such as `???` stay invalid rather than being guessed. This conservatively loses some usable price filters and must be addressed from trustworthy upstream data before a final experiment.

Cleaning rules (version `reviews-cleaning-v1`):

1. Trim leading/trailing whitespace; blank strings become null. Literal strings such as `NA` are preserved, not assumed missing.
2. Drop missing review bodies, or fail with `missing_review=error`.
3. Parse only configured currency prefixes and valid comma thousands groups. Reject negative/nonfinite prices, malformed numbers, and ratings outside configured bounds (default 1–5); store null and report the invalid values' counts. No imputation.
4. Report exact source duplicates separately from duplicates of retained canonical records. Remove canonical duplicates by default. With `deduplicate=false`, retain occurrence-specific stable IDs.
5. Compute review IDs from canonical cleaned content. Dataset version is SHA-256 of source-byte hash plus cleaning configuration and pipeline version. IDs survive row reordering; the dataset version intentionally changes with source bytes. Dataset version is part of every review/reference-label key.

Keep the raw CSV unchanged to reconstruct the cleaned dataset. `data/processed/import_report.json` records source hash, resolved mappings, cleaning settings, quality counts and dataset version. `dataset_versions` stores the same provenance with import timestamp. Re-importing identical bytes and settings checks the row count and leaves existing records intact. Changed data or cleaning settings create a separate version. Do not edit processed databases by hand.

## Storage and tests

`src/database/db.py` creates `reviews`, `reference_labels`, `cache_entries`, `experiment_runs`, `experiment_events`, plus `dataset_versions`. Cache entries store versioned VectorQ region observations and the log posterior, vectors and request text. Reference-label keys include dataset version, review, task, prompt and model; foreign keys prevent labels for nonexistent review versions. Success labels must be YES/NO and failed generations cannot carry a label.

Transactions roll back failed writes. Indexes support rating, price, product and category filters, cache namespaces, and per-run query events. Structured filters allowlist columns/operators and bind values, reject invalid numbers and always restrict to an explicit dataset version.

Tests use clearly marked synthetic fixtures solely for validation, not as experimental data. They cover aliases, required fields, explicit body/headline mapping, blanks, invalid numbers, duplicate reporting/retention, stable IDs, source preservation, reconstruction, repeated imports, configuration versions, SQL filters, malformed input, strict decoding, reference uniqueness and transaction rollback. `pytest.ini` puts temporary test data in `.pytest-work` to work inside the Windows sandbox.

See `reports/phase1.md` for the historical Phase 1 checkpoint and `reports/research_report.md` for the current measured pilot study. Machine-readable logs, tables, figures and test reports are under `results/`.

## Models, secrets and token use

Copy `.env.example` to `.env` and fill `MISTRAL_API_KEY` locally. `.env` is ignored. The loader also honors existing environment variables and never executes shell syntax from the file. Never paste API keys into reports or source code.

Configured models are pinned `ministral-3b-2512` and `mistral-embed-2312`, chosen using the official Mistral model documentation on 26 October 2026. The LLM uses a short classification instruction, temperature zero, seed 17 and a four-token output cap. Smaller models do not intrinsically use fewer input tokens. Full review bodies are preserved; no silent truncation reduces the input. Model outputs must be exactly YES or NO after surrounding whitespace removal. Incomplete or malformed output is a failure, not a fabricated NO. Temperature and a seed do not guarantee remote-service determinism.

The current standard pricing assumption is $0.10 per million input and output LLM tokens and $0.10 per million embedding tokens. These are saved estimates from documented prices, not billing statements; no provider-side prompt-cache discount is assumed. Failed request cost is unknown when the provider supplies no usage.

The alternative local provider is `ollama` with an explicit model and base URL. Its latency and token counts are logged when available; no monetary cost is invented. Automated tests use local transport doubles. Only Mistral has been exercised live in this project.

## Reference labels and the approved development pilot

The current pilot contains precisely the first 10 cleaned real reviews in review-ID order. Its manifest records all IDs and the parent version; its separate database has a derived cohort version. All three tasks are labeled independently without semantic caching. Reference labels are the selected model's outputs, not human truth. All 30 pilot labels happened to be NO, which makes this an execution smoke test rather than an informative correctness study.

Run from Windows CMD after filling `.env`:

```bat
python -m scripts.inspect_workload
python -m scripts.generate_labels --limit 10
python -m scripts.inspect_labels --size 30
python -m scripts.prepare_pilot
python -m scripts.prepare_embeddings
```

Label generation defaults to 10 reviews times three tasks (up to two attempts per task). It resumes successful saved labels, preserves failures and retries saved failures only with `--retry-failed`. `--offset` and `--limit` support larger independent label generation workflows when deliberately requested. Changing a task without a new prompt version is rejected. The model identity includes generation settings, so incompatible labels are not silently reused.

`manual_review.csv` has blank human-label and notes columns. Fill those after reading each task/review, then calculate agreement and investigate disagreements before a final study. Exporting this file does not constitute manual validation; none is claimed yet. Keep it separate from immutable model reference labels.

## One command for all policies

After the preceding preparation commands, this command runs all P0–P6 with isolated cold and warm caches:

```bat
python -m scripts.benchmark --mode offline
```

Offline replay uses saved model labels, makes zero API calls and reports **simulated** inference counts. Live inference on misses and checks is separate:

```bat
python -m scripts.benchmark --mode live --states cold
python -m scripts.benchmark --mode live --states warm --max-live-attempts 362
python -m scripts.ablate
python -m scripts.analyze_results
python -m scripts.write_report
python -m pytest -q --junitxml=results/raw/final_tests.xml
```

The 362-attempt warm override was the remaining budget after the actual cold run used 138 of the approved 500 runtime attempts. Each invocation has its own configured budget; adding new live invocations is additional spending. Warmup inference is recorded separately from the measured warm pass and must be included in total operational spend.

Both modes currently use precomputed embeddings from the same Mistral model for fair, inexpensive pilot runs. Encoding setup calls/costs are saved separately; measured embedding time is an in-memory vector retrieval, **not remote embedding inference latency**. Live timing includes actual LLM network calls and local SQL/cache work, but excludes offline labeling, offline encoding setup and cache warmup. The runner deliberately refuses cohorts other than these 10 IDs. A larger validation/test experiment requires extending that explicit scope and generating its own reference labels/embeddings.

Policies: P0 no cache; P1 static threshold; P2 VectorQ paper v1; P3 its R3 selectivity gate; P4 reverse gate; P5 extra selectivity-dependent R3 audits; P6 exact task/version/text key. Audits count as inference attempts and never direct hits. Predicate, prompt, model, embedding model, cohort version and run isolate entries. New runs get new state; `reset()` also resets the random streams. An existing run rejects changed policy settings. Mid-run crash resumption of the random stream is not supported: restart as a fresh run instead.

## VectorQ provenance and numerical choices

P2 follows Algorithms 1 and 2 of [the original paper, arXiv v1](https://arxiv.org/html/2502.03771v1). It retains R1/R2/R3, monotone rejection, correction-driven region updates, the exponential posterior and uncertainty-gate sampling. P3–P5 are separate controllers and cannot bypass R1/R2.

The inspected [official repository](https://github.com/vcache-project/vCache) at `50694eebf0c870231030f73707cb6543d47f0411` implements later vCache. Historical `2c99678e9ed3934a0ef0b07789acd34b67f77a79` contains unfinished posterior/core methods, and `fca83c4d6822f329aad6bfd619a855718fc020e9` implements a different logistic Bayesian policy. These were not silently substituted for the requested three-region method. Saved sources and hashes are in `research/vectorq_source_manifest.json`.

This is a **paper-based reimplementation**, not a byte-identical reproduction of an upstream runtime or the later vCache guarantees. The continuous posterior uses a 1,001-point trapezoidal grid with log-space updates; analytic one-step and 10,001-point convergence tests verify the numerical representation. Default decay 10 is a documented development choice. Algorithm 2 normalizes by an integral, whereas the paper's prose also says the density is bounded by one. We follow the explicit integral equation; values above one force an audit under Algorithm 1. Exact cosine search is the declared development fallback; negative cosine scores are clipped to zero to match the paper's [0,1] score domain. No upstream three-region test suite was executed, and no claim that such a suite passed is made.

## Experimental limits and next research work

The saved development sweep covers gate direction, gate versus audit, global versus stage-local selectivity, minimum/maximum threshold, gamma, uncertainty gate, audit rate, query orders and a repeated seed. It does not tune or freeze final parameters. No final test data were used to select parameters because no final test experiment exists yet.

Before drawing research conclusions, extend to representative, disjoint validation and test cohorts with positive and negative labels; inspect labels manually; tune on validation only; freeze the full configuration; then repeat the held-out comparison with appropriate confidence intervals. Current performance numbers are pilot diagnostics. Empty narrow groups and undefined reuse rates remain explicit in tables. Timing variability on ten records and precomputed embeddings cannot establish production latency or cost savings.

All processed candidates in the main live pilot had global selectivity 1.0; selective queries were empty. P3 made zero selectivity-forced checks, so its equality with P2 does not test the main selectivity hypothesis. Selective nonempty behavior is covered by automated fixtures, not demonstrated by this real-data pilot.
