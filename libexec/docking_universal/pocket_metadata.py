"""Carry recorded pocket predictions with locked regions, without recalculation."""
import csv
import hashlib
import math
from pathlib import Path
import re


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def region_prediction(region, *, base=None, detector=None):
    """Read embedded evidence, or recover legacy evidence beside its exact box.

    Never assign an individual prediction score to a consolidated/ligand-only
    box. Recovery requires a matching approved box hash and its recorded output
    index, not a guess based on the top-ranked pocket or a similar filename.
    """
    retained = region.get('pocket_prediction') or {}
    if _number(retained.get('score')) is not None:
        if not detector or retained.get('detector') == detector:
            return dict(retained)
        return {}
    name = str(region.get('box_name') or Path(str(region.get('box',''))).name)
    match = re.search(r'_pocket(\d+)\.conf$', name)
    if not match or str(region.get('box_label','')).startswith(('L', 'B')):
        return {}
    box = Path(str(region.get('box',''))).expanduser()
    if not box.is_absolute():
        if base is None: return {}
        box = Path(base) / box
    expected = region.get('box_sha256')
    try:
        if not expected or hashlib.sha256(box.read_bytes()).hexdigest() != expected:
            return {}
        source = box.parent / 'pocket_selection_diagnostics.tsv'
        content = source.read_bytes()
        rows = list(csv.DictReader(content.decode().splitlines(), delimiter='\t'))
    except (OSError, UnicodeError):
        return {}
    matches = [row for row in rows if str(row.get('rank_order','')).strip() == str(int(match.group(1))) ]
    if len(matches) != 1: return {}
    row = matches[0]
    engine = str(row.get('pocket_engine') or detector or 'fpocket').lower()
    if detector and engine != detector: return {}
    score = _number(row.get('rank_score') or row.get('score'))
    if score is None: return {}
    result = {'detector':engine, 'score':score, 'pocket_file':row.get('pocket_file'),
              'source_file':source.name, 'source_sha256':hashlib.sha256(content).hexdigest()}
    probability = _number(row.get('probability'))
    if engine == 'p2rank' and probability is not None:
        result['probability'] = probability
    return result


def annotate_regions(regions, *, base=None, detector=None):
    result = []
    for region in regions:
        region = dict(region)
        prediction = region_prediction(region, base=base, detector=detector)
        if prediction: region['pocket_prediction'] = prediction
        result.append(region)
    return result
