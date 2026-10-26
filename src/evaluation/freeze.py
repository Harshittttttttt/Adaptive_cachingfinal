"""Content-addressed settings selected on validation, checked before test."""
import hashlib
import json
from pathlib import Path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def write_freeze(path,payload):
    if payload.get('selection_split')!='validation':
        raise ValueError('Final settings can only be selected on validation')
    path=Path(path)
    document={'payload':payload,'sha256':fingerprint(payload)}
    path.write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    return document


def read_freeze(path):
    document=json.loads(Path(path).read_text(encoding='utf-8'))
    if document['sha256']!=fingerprint(document['payload']):
        raise ValueError('Frozen settings were modified')
    if document['payload']['selection_split']!='validation':
        raise ValueError('Invalid parameter selection split')
    return document
