"""Deterministic, text-disjoint challenge cohorts selected before any labels."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

from src.database.db import connect, initialize
from src.llm.references import ReferenceStore
from src.query.plan import TASKS, selected_version

SELECTION_VERSION = 'stratified-text-disjoint-v1'
STRATA = ('cheap_low', 'expensive_low', 'shipping_cue', 'defect_cue',
          'sarcasm_cue', 'low_other', 'medium_other', 'high_other')


def text_key(text):
    return hashlib.sha256(' '.join(text.lower().split()).encode()).hexdigest()


def stratum(row):
    rating, price = row['rating'], row['price']
    text = row['review_text'].lower()
    if rating is not None and rating <= 2 and price is not None and price < 100:
        return 'cheap_low'
    if rating == 1 and price is not None and price >= 20000:
        return 'expensive_low'
    if re.search(r'\b(ship\w*|deliver\w*|courier|parcel|transit)\b', text):
        return 'shipping_cue'
    if re.search(r'\b(broken|defect\w*|faulty|damaged)\b|not working|stopped working', text):
        return 'defect_cue'
    if re.search(r'yeah right|thanks for nothing|what a joke|just great|so much for', text):
        return 'sarcasm_cue'
    if rating is not None and rating <= 2:
        return 'low_other'
    if rating == 3:
        return 'medium_other'
    return 'high_other'


def select(rows, sizes, seed=2252, excluded_texts=()):
    """Split by normalized body hash, then sample within predeclared strata.

    Lexical cues are sampling strata, never reference labels. No selected text
    can be present in both cohorts, even if product metadata differ.
    """
    pools = {split: defaultdict(list) for split in sizes}
    excluded = set(excluded_texts)
    seen = set()
    for row in rows:
        text = row['review_text']
        if not 20 <= len(text) <= 1200:
            continue
        group = text_key(text)
        if group in excluded or group in seen:
            continue
        seen.add(group)
        split = 'validation' if int(group[:8], 16) % 3 == 0 else 'test'
        if split not in pools:
            continue
        ranking = hashlib.sha256(f'{seed}:{row["review_id"]}'.encode()).hexdigest()
        pools[split][stratum(row)].append((ranking, dict(row)))
    chosen, diagnostics = {}, {}
    for split, size in sizes.items():
        if size <= 0 or size % len(STRATA):
            raise ValueError('Cohort sizes must be positive multiples of eight strata')
        quota = size // len(STRATA)
        picked, remainder = [], []
        available = {}
        for name in STRATA:
            pool = sorted(pools[split][name], key=lambda pair: pair[0])
            available[name] = len(pool)
            picked.extend(row for _, row in pool[:quota])
            remainder.extend(pool[quota:])
        picked.extend(row for _, row in sorted(remainder, key=lambda pair: pair[0])[:size-len(picked)])
        if len(picked) != size:
            raise ValueError('Insufficient eligible real rows')
        chosen[split] = sorted(picked, key=lambda row: row['review_id'])
        diagnostics[split] = dict(available=available, selected=dict(Counter(stratum(r) for r in picked)))
    groups = [{text_key(row['review_text']) for row in values} for values in chosen.values()]
    if len(groups) == 2 and groups[0] & groups[1]:
        raise AssertionError('Text leakage between validation and test')
    return chosen, diagnostics


def prepare(config, root='data/processed/study', sizes=None):
    sizes = sizes or {'validation': 64, 'test': 96}
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with connect(config['dataset']['database']) as source:
        parent = selected_version(config, source)
        pilot = source.execute('SELECT review_text FROM reviews WHERE dataset_version=? ORDER BY review_id LIMIT 10',
                               (parent,)).fetchall()
        rows = source.execute('SELECT * FROM reviews WHERE dataset_version=? ORDER BY review_id', (parent,))
        cohorts, diagnostics = select(rows, sizes, excluded_texts=[text_key(r['review_text']) for r in pilot])
        parent_info = dict(source.execute('SELECT * FROM dataset_versions WHERE dataset_version=?', (parent,)).fetchone())
    manifests = {}
    for split, rows in cohorts.items():
        ids = [r['review_id'] for r in rows]
        provenance = dict(selection_version=SELECTION_VERSION, seed=2252, split=split,
                          parent_dataset_version=parent, review_ids=ids,
                          text_group_hashes=[text_key(r['review_text']) for r in rows],
                          eligibility='20..1200 characters, distinct normalized bodies, excluding pilot bodies',
                          strata=diagnostics[split], purpose='stratified challenge cohort; not prevalence-representative')
        version = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
        manifest = dict(dataset_version=version, row_count=len(rows), **provenance)
        database = root / (split + '.sqlite3')
        with connect(database) as db:
            initialize(db)
            refs = ReferenceStore(db)
            for task in TASKS.values():
                refs.register_task(task)
            db.execute('''INSERT OR IGNORE INTO dataset_versions
                (dataset_version,source_dataset,source_sha256,source_path,source_description,
                 cleaning_config,row_count,cleaning_summary) VALUES (?,?,?,?,?,?,?,?)''',
                (version, 'challenge-' + split, parent_info['source_sha256'], parent_info['source_path'],
                 parent_info['source_description'], json.dumps(provenance), len(rows), json.dumps(diagnostics[split])))
            db.executemany('INSERT OR IGNORE INTO reviews VALUES (?,?,?,?,?,?,?,?,?)',
                           [(version, *tuple(r[k] for k in ('review_id','product_name','price','rating','review_text',
                                                            'summary','category','source_dataset'))) for r in rows])
        path = root / (split + '_manifest.json')
        path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        manifests[split] = manifest
    # Counts, not review contents, are sufficient for a concrete export approval.
    overview = dict(selection_version=SELECTION_VERSION, cohorts={
        s: dict(row_count=len(rs), body_characters=sum(len(r['review_text']) for r in rs),
                strata=diagnostics[s]['selected'], dataset_version=manifests[s]['dataset_version'])
        for s, rs in cohorts.items()}, text_disjoint=True, labels_per_review=3,
        label_calls_without_retries=sum(sizes.values())*3,
        label_attempt_cap=sum(sizes.values())*3*2,
        embedding_inputs=sum(sizes.values())*3,
        live_runtime_attempt_cap=3000,
        price_note='At configured $0.10/M input/output tokens; exact use is provider-reported after execution')
    (root/'export_plan.json').write_text(json.dumps(overview, indent=2)+'\n', encoding='utf-8')
    return overview
