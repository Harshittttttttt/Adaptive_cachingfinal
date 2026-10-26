# Reviewer revision checklist

| Issue | Implemented revision and evidence | Status |
|---|---|---|
| Weak contribution | Paper Introduction and Selectivity Aware Reuse foreground conditional inactivity and the auditable seven-policy executor | Revised |
| Abstract and conclusion | Direct problem, evaluation, score-support finding and bounded implication | Revised |
| Inactive configuration | 42 post-hoc runs; full constant sweep and active validation-quantile rule in `results/study/calibration/` | Implemented; exploratory |
| Similarity mechanism | Main P2 R3 distributions by predicate, query type and state; conditional trajectory argument | Verified against logs and policy RNG behavior |
| Small or misleading scale | Paper Methodology/Limits distinguish 12 plans, 96 test reviews, 1,320 original and 504 diagnostic executions | Clarified; broader data remains outstanding |
| Human truth | Model reference identity and unknown human accuracy prominent in abstract/method; assistant check explicitly identified | Human annotation remains outstanding |
| Live ambiguity | Dedicated exploratory live subsection; remote output variation and inactive-threshold interpretation | Revised; expanded live replication remains outstanding |
| Uncertainty | Main and calibration replay tables report mean ± sample SD; agreement dispersion is in percentage points | Implemented |
| 581 denominator | Paper Table II and `tables/baseline_581.csv` enumerate every semantic-stage input | Verified |
| Runtime | Paper Table VI separates pipeline, inference, search and prepared-vector retrieval; components inspected in metrics source | Implemented; no online embedding timing claim |
| IEEE headings | Dedicated upper-Roman main section list and alphabetic subsection lists with explicit per-section restarts | Render checked |
| Tables and notation | Captions above tables, TABLE I–VI, immediate column definitions and standardized terms | Render checked |
| References | All 25 supplied works have body citations; 29 total entries; repository revision and exact model versions; reference bold disabled | Citation audit and visual check |
| Implementation minutiae | Short paper scope/fidelity statement, details in artifact README and source manifest | Revised |
| Interface | Separate Calibration study with state control, means/SD, scores, source tables; original run explorer still contains only original test/live logs | Implemented and tested |
| Artifact consistency | README and calibration supplement updated; detailed report retains original scope with explicit notice; release rebuilt after verification | Check release evidence |

The revision establishes an active score-calibration experiment, not a demonstrated selectivity-specific optimization. No original freeze was replaced. No new API requests or independent human labels were obtained. Multiple independent datasets, representative traffic, human adjudication, further models and independently replicated online timings require a fresh confirmatory study.
