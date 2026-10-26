"""Explicit column resolution and conservative record cleaning."""
import math
import re

CANONICAL = ('product_name', 'price', 'rating', 'review_text', 'summary', 'category')
ALIASES = {
    'product_name': ('productname', 'product', 'title'),
    'price': ('price', 'productprice'),
    'rating': ('rating', 'rate', 'score', 'overall'),
    'review_text': ('reviewtext', 'review', 'text', 'body', 'reviewbody'),
    'summary': ('summary', 'headline', 'reviewtitle'),
    'category': ('category', 'productcategory'),
}


def normalize_header(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def resolve_columns(headers, overrides=None):
    if not headers or len(set(headers)) != len(headers):
        raise ValueError('CSV needs non-duplicate column names')
    normalized = {}
    for header in headers:
        key = normalize_header(header)
        if key in normalized:
            raise ValueError(f'Ambiguous normalized CSV header: {header}')
        normalized[key] = header
    overrides = overrides or {}
    if set(overrides) - set(CANONICAL):
        raise ValueError('Unknown canonical column in mapping')
    mapping = {}
    for field in CANONICAL:
        if field in overrides:
            chosen = overrides[field]
            if chosen is not None and chosen not in headers:
                raise ValueError(f'Configured column missing: {chosen}')
            mapping[field] = chosen
        else:
            matches = [normalized[a] for a in ALIASES[field] if a in normalized]
            if len(matches) > 1:
                raise ValueError(f'Ambiguous mapping for {field}; configure explicitly')
            mapping[field] = next(iter(matches), None)
    if not mapping['review_text']:
        raise ValueError('Required review_text column missing')
    return mapping


def clean_text(value):
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_numeric(value, field, config):
    """Blank -> null; invalid -> null plus an explicit quality flag."""
    if value is None:
        return None, False
    if field == 'price':
        for prefix in config.get('numeric_prefixes', ['₹', '$', '£', '€']):
            if value.startswith(prefix):
                value = value[len(prefix):].strip()
                break
        # Only accept correctly grouped thousands, not arbitrary punctuation removal.
        if ',' in value:
            if not re.fullmatch(r'-?\d{1,3}(,\d{3})+(\.\d+)?', value):
                return None, True
            value = value.replace(',', '')
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None, True
    if not math.isfinite(result) or (field == 'price' and result < 0):
        return None, True
    if field == 'rating' and not config.get('rating_min', 1) <= result <= config.get('rating_max', 5):
        return None, True
    return result, False


def clean_record(row, mapping, config):
    record = {k: clean_text(row.get(v)) if v else None for k, v in mapping.items()}
    missing = [k for k, v in record.items() if v is None]
    invalid = []
    for field in ('price', 'rating'):
        record[field], bad = parse_numeric(record[field], field, config)
        if bad:
            invalid.append(field)
    return record, missing, invalid
