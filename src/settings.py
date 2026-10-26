"""Small shared configuration loader; credentials never enter saved configs."""
import json
import os
from pathlib import Path


def load_env(path='.env'):
    """Read literal KEY=value lines only; never execute shell substitutions."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not key.strip().replace('_', '').isalnum():
            raise ValueError('Malformed .env entry')
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_config(path='config/default.json'):
    load_env()
    return json.loads(Path(path).read_text(encoding='utf-8'))
