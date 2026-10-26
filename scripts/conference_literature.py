"""Verified bibliography and focused related work for the conference paper.

P1--P25 keys map to the supplied project PDF's reference numbers; bibliography
numbers in the final paper are assigned by first citation, not these keys.
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def bibliography():
    refs=json.loads((ROOT/'research/conference_literature.json').read_text(encoding='utf-8'))
    return {'P'+str(r['pdf_reference']):r['citation'] for r in refs}


RELATED_WORK=[
 ('Learning based optimization','Heading2'),
 ('Qiao et al. organize learned database optimization around cardinality and cost estimation, join ordering, end to end optimization and text to SQL [P1]. Milicevic and Babovic examine deep learning across indexes, plan optimization and external optimizer control [P2]. Bagui et al. survey language model roles in database optimization [P4]. Together these surveys place the present controller at a narrower execution boundary: deciding whether a previously computed semantic predicate output can be reused. We measure observed surviving rows rather than learning cardinality estimates, selecting joins or generating a new physical plan. This scope makes the cache intervention identifiable, but does not establish that it replaces a cost based optimizer.', 'BodyText'),
 ('Kumar reviews language model architectures, applications and limitations [P7]. Lu et al. examine language models for table processing [P5], while Xu et al. survey generative information extraction and its task and prompting techniques [P6]. These works motivate combining structured records with model based interpretation. Our binary shipping, defect and sarcasm operators are a restricted classification workload; their model outputs remain fallible references. The initial prompt failure and versioned correction illustrate why model choice and task specification must be recorded alongside cache settings.', 'BodyText'),
 ('Language interfaces and query plans','Heading2'),
 ('Katsogiannis-Meimarakis and Koutrika survey neural text to SQL systems [P3]. ASKSQL combines natural language to SQL translation with a cost conscious pipeline and semantic caching for query generation [P9]. PURPLE retrieves demonstrations that match the logical composition needed for SQL generation [P14]. These methods operate at the language to query boundary. Our workload instead supplies explicit structured plans, so generated SQL errors do not become an uncontrolled source of cache disagreement. A future natural language interface could use these approaches, provided translation accuracy is assessed separately from semantic result reuse.', 'BodyText'),
 ('Vasilenko et al. embed execution plans to retrieve useful optimizer hintsets without additional model training [P11]. Abed Allah combines conventional cost estimation, learned predictions and language model reasoning for confidence aware SQL tuning [P15]. Similarity over plans and confidence about a rewrite differ from similarity over review inputs. Their role here is methodological context: a reuse decision needs a clearly defined object, feedback signal and fallback. We retain inference audits as the fallback and do not claim to reproduce either optimizer.', 'BodyText'),
 ('Hybrid semantic query processing','Heading2'),
 ('Palimpzest offers declarative AI analytics while exploring model and execution choices across quality, cost and runtime [P17]. Abacus develops cost based optimization of semantic operator systems under objectives and constraints, using validation evidence to estimate operator behavior [P18]. iPDB extends relational processing with model inference and semantic SQL optimization [P12]. These systems establish the wider setting for expensive semantic maps, filters and joins. The present prototype holds its explicit pipeline fixed while testing a reuse policy inside a predicate evaluator; it neither searches their plan spaces nor benchmarks their complete implementations.', 'BodyText'),
 ('TAG argues that database reasoning extends beyond relational text to SQL and point retrieval [P20]. SUQL supports conversational querying across structured and unstructured information [P21]. ZenDB exploits document structure to support SQL analytics over document collections [P22]. Zhao et al. survey retrieval augmented generation, including its components and limitations [P8]. These works explain why retrieval, relational filtering and model reasoning often coexist. For this study, however, retrieving a nearby embedding is only a candidate lookup: it is not proof that the two reviews share the same predicate label. Complete result set agreement is therefore measured in addition to lookup statistics.', 'BodyText'),
 ('Semantic reuse and correctness','Heading2'),
 ('The later vCache paper learns embedding specific reuse thresholds and studies user specified error guarantees [P10]. Our baseline follows the earlier three region VectorQ version [1], and is not an evaluation of the final vCache algorithm. Liu et al. formulate semantic cache eviction with mismatch costs under uncertain query and serving distributions, studying offline learning and online adaptation [P16]. That capacity and eviction problem is complementary to our selectivity gate on acceptance. We do not transfer either work\'s theoretical guarantees to this numerical reimplementation or to model labels with unknown human correctness.', 'BodyText'),
 ('Bindschaedler canonicalizes analytical SQL and natural language into intent signatures for safety focused OLAP reuse [P13]. Its exact intent checks and permitted derivations differ from approximate reuse of a binary classification answer. This distinction motivates an exact key control in our experiments: P6 isolates savings from repeated identical inputs. Its strong performance on the repeated workload does not establish that canonicalization and approximate response caching are interchangeable, or that exact caching will dominate under query drift.', 'BodyText'),
 ('Vector indexes and inference serving','Heading2'),
 ('Product quantization compresses vectors for approximate nearest neighbor search [P23]. Pan et al. review vector database query processing, indexing, compression and execution techniques [P25]. ACORN supports hybrid search over embeddings and structured predicates through predicate aware graph traversal [P24]. These works suggest that an expanded deployment must evaluate index recall, filtering and memory alongside semantic reuse error. Our exact cosine search removes approximate index recall as an experimental factor; no ACORN or product quantization speedup is claimed. Selectivity affecting vector retrieval performance does not by itself prove that it improves a cache correctness threshold.', 'BodyText'),
 ('PagedAttention addresses memory management for attention key value caches inside language model serving [P19]. It can improve the execution of requests that still reach the model. Semantic response caching instead attempts to avoid some requests altogether. These are compatible optimization layers with different units of reuse. Because this study calls a remote provider and uses prepared embeddings, it cannot measure a local serving engine improvement or infer online encoding latency from vector retrieval time.', 'BodyText'),
]


def add_related_work(add):
    add('Related work','Heading1')
    for text,style in RELATED_WORK:add(text,style)
