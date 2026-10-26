"""Versioned semantic tasks and explicit query plans; no text-to-SQL."""
from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class Task:
    predicate_id: str
    instruction: str
    prompt_version: str = 'v1'
    output_format: str = 'YES|NO'
    required_fields: tuple[str, ...] = ('review_text',)

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in
                   (self.predicate_id, self.instruction, self.prompt_version)):
            raise ValueError('Task identity, version and instruction must be nonempty')
        if self.output_format != 'YES|NO' or self.required_fields != ('review_text',):
            raise ValueError('This prototype supports review_text -> YES|NO tasks')

    @property
    def fingerprint(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def input_text(self, review_text):
        if not isinstance(review_text, str) or not review_text.strip():
            raise ValueError('Missing review text')
        # JSON prevents accidental ambiguity in exact keys and embedding input.
        return json.dumps({'predicate_id': self.predicate_id,
                           'prompt_version': self.prompt_version,
                           'instruction': self.instruction,
                           'output_format': self.output_format,
                           'review_text': review_text}, sort_keys=True, ensure_ascii=True)


TASKS = {
    'shipping': Task('shipping', 'Does the review describe a shipping or delivery problem?'),
    'sarcasm': Task('sarcasm', 'Does the review express sarcasm?'),
    'defect': Task('defect', 'Does the review describe a product defect or malfunction?'),
}


def tasks_for(config):
    version=config.get('semantic_prompt_version','v1')
    if version=='v1':return TASKS
    if version!='v2':raise ValueError('Unknown semantic prompt version')
    return {key:Task(task.predicate_id,task.instruction,'v2') for key,task in TASKS.items()}


@dataclass(frozen=True)
class QueryPlan:
    query_id: str
    dataset_version: str
    sql_filters: tuple[tuple[str, str, object], ...] = ()
    semantic_tasks: tuple[Task, ...] = ()
    output_format: str = 'row_ids'
    group: str = 'unspecified'

    def __post_init__(self):
        if not self.query_id or not self.dataset_version:
            raise ValueError('Query ID and explicit dataset version are required')
        if self.output_format not in {'row_ids', 'rows'}:
            raise ValueError('Unsupported query output format')
        if len({t.predicate_id for t in self.semantic_tasks}) != len(self.semantic_tasks):
            raise ValueError('A predicate can appear only once in a query')

    @classmethod
    def from_dict(cls, value, dataset_version, registry=None):
        registry=registry or TASKS
        tasks = []
        for spec in value.get('semantic_tasks', []):
            if isinstance(spec, str):
                tasks.append(registry[spec])
            else:
                task = registry[spec['predicate_id']]
                if spec.get('prompt_version', task.prompt_version) != task.prompt_version:
                    raise ValueError('Unknown task prompt version')
                tasks.append(task)
        configured_version = value.get('dataset_version', dataset_version)
        if configured_version != dataset_version:
            raise ValueError('Workload dataset version differs from selected dataset')
        return cls(value['query_id'], dataset_version,
                   tuple(tuple(f) for f in value.get('sql_filters', [])), tuple(tasks),
                   value.get('output_format', 'row_ids'), value.get('group', 'unspecified'))


def selected_version(config, db):
    """Select the recorded import explicitly; never silently choose latest."""
    version = config['dataset'].get('version')
    if not version:
        from pathlib import Path
        version = json.loads(Path(config['dataset']['report']).read_text(encoding='utf-8'))['dataset_version']
    row = db.execute('SELECT source_dataset FROM dataset_versions WHERE dataset_version=?', (version,)).fetchone()
    if not row or row['source_dataset'] != config['dataset']['name']:
        raise ValueError('Selected dataset version is missing or has a different dataset name')
    return version
