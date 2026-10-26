# Protocol for the next human verified study

This is a proposed protocol. No annotations or human-accuracy estimates have been collected under it.

1. Select fresh review-body groups before annotation and separate validation from untouched test groups. Record source identity, license, selection seed, length rules and normalized text hashes. Include a prevalence-oriented sample and a separately reported challenge sample from at least one additional documented source. Determine sample sizes and uncertainty targets before viewing outcomes.
2. Write task definitions for shipping, sarcasm and defect, including explicit inclusion/exclusion examples and an AMBIGUOUS option. Pilot the definitions on validation material; record changes before the test protocol is frozen.
3. Have two human annotators independently label each selected task/review pair. Hide model outputs, cache decisions, sampling cues and the other annotator's answers. Retain anonymous annotator IDs, timestamps, task-definition versions and short rationale fields. Model-generated labels must never populate human-label columns.
4. A third human adjudicates disagreements using the frozen task definitions. Preserve both original answers, the adjudicated answer, the adjudicator ID and reason. Predeclare whether irreducibly ambiguous cases are retained as a separate class or excluded from binary metrics; report their count and sensitivity analysis.
5. Report class counts, inter-annotator agreement, adjudication rates and model agreement/accuracy on scorable cases, with appropriate uncertainty and per-task confusion matrices. Do not label assistant spot-checks as independent human verification.
6. Use fresh validation data to choose similarity calibration and compare a constant-threshold control with selectivity-dependent alternatives under the same accuracy/cost target. Include exact-input caching. Log activation rate and the eligible score distribution before comparing final result sets.
7. Freeze task definitions, cohort manifests, models/prompts, workload distributions, policy parameters, seed list, metrics and analysis plan before testing new held-out data. Keep the current post-hoc cohort out of confirmatory claims.
8. Define a bounded API/export budget for the exact cohorts and models, obtain any necessary additional authorization, and preserve existing usage ledgers. Run live conditions in isolation with replications, separate online encoding from lookup, and account for preparation and warmup costs.

The existing 24-pair assistant audit is diagnostic context only. It is not an input human gold standard for this protocol.
