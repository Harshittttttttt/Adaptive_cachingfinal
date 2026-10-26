# Phase 1 — executed data preparation and SQLite validation

Date: 26 October 2026 (Asia/Calcutta). This is a measured Phase 1 implementation report, not a completed semantic-cache study.

## Input and provenance

The only initially available project file was `Dataset.csv`, 57,988,503 bytes. Source SHA-256: `e11df026e5b6cbe6107927d790f070a1c104434d688b4d5d7c0725c03c6656d6`. Its upstream source, publication version, license and Amazon provenance were not supplied and remain unknown. Local source bytes plus the saved cleaning configuration define the reproducible dataset version.

The actual header is `Product_name,Price,Rate,Review,Summary`. Inspecting the values established that `Review` holds short headlines and `Summary` holds longer bodies. The configured mapping deliberately uses `Summary` for `review_text` and `Review` for the canonical `summary` field. No category exists, so all categories remain null.

Strict UTF-8 decoding failed at byte 73. The selected Latin-1 interpretation preserves byte values and does not recover previously corrupted text. Only the documented observed `U+009F??` prefix and configured currency prefixes are stripped from price fields. Unknown damaged price prefixes remain invalid and become null. The raw source remains unchanged.

## Actual import results

| Measurement | Count |
|---|---:|
| Source rows | 363,261 |
| Exact source duplicate rows | 53,786 |
| Missing review-body rows dropped | 2,022 |
| Canonical duplicate rows removed after missing-body removal | 53,286 |
| Persisted cleaned records | 307,953 |
| Invalid prices in source rows (null after cleaning) | 36,343 |
| Invalid ratings in source rows (null after cleaning) | 6 |
| Blank source prices | 16 |
| Blank source ratings | 16 |
| Blank product names | 15 |
| Blank headlines | 22 |

Quality counts describe all source rows, including rows subsequently dropped or deduplicated. Exact duplicates are reported before missing-body removal; canonical duplicates are counted among retained bodies. These counts are intentionally different. Null categories denote an absent optional column, not missing fabricated data.

Dataset version: `093a7fbcddbcc58fbd8ab7b2f2ee859c62499522508182cf1a3cc72790905300`.

## Actual verification

`python -m pytest -q --tb=short --junitxml=results/raw/phase1_tests.xml` completed with **28 passed in 2.55 seconds**. The first attempt encountered a Windows sandbox temporary-directory error; configuring a project-local temporary directory resolved it. No test failures remain.

`python -m scripts.verify_dataset` completed in **55.37 seconds** and verified:

- Re-importing the original configuration was idempotent.
- Independent reconstruction produced the same dataset version and every ordered cleaned record matched.
- Primary and reconstructed record-stream SHA-256: `8fd1cb75e4db63689f5d44f9015f7dd23ac4eb7f9429964beb4d59f47bc2ee73`.
- SQLite integrity check returned `ok`; foreign-key check returned no violations.
- The version-scoped `rating <= 2` filter returned **49,923** records, all satisfying the condition.
- A `rating < 0` filter returned **0** records.

Runtime: Python 3.14.7, SQLite 3.50.4, pytest 9.1.1, Windows 11. Runtime application dependencies are standard-library modules only. See the machine-readable environment and verification files in `results/raw`.

## Delivered code and boundaries

Implemented: column inspection/mapping, quality validation, conservative numeric cleaning, stable content IDs, source/config versioning, duplicate handling, transactional SQLite import, repeat-import checking, structured SQL filters, reference-label uniqueness constraints, future cache/run/event storage tables, automated tests, independent reconstruction verification, configuration and exact Windows CMD instructions.

The database contains no reference labels, cache entries, experiment runs or experiment events. The reserved cache metadata schema will be revisited when the exact VectorQ source implementation is selected. No LLM or embedding calls have occurred. No cache reuse, costs, latency comparisons, policy tables, plots or claims of selectivity-aware improvement are reported. Those require Phases 2–12 and actual model/reference-label runs. Corrupted text, unknown source provenance, and conservatively null prices are material dataset limitations for those phases.
