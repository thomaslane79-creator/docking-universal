"""Carry recorded pocket predictions with locked regions, without recalculation."""
import csv
import colorsys
import hashlib
import math
from pathlib import Path
import re

# Keep the first five rank colors and space the following colors perceptually
# against white at the pocket surface opacity used by the 3D viewer.
POCKET_COLORS = ("#d62728", "#1f77b4", "#d9a400", "#a334b4", "#00a6bf",
                 "#1a06f9", "#6b5a2e", "#e506f9", "#e495bb", "#f9067b",
                 "#064af9", "#e4e195", "#f95e06", "#261f7a", "#7a1f40",
                 "#9088f2", "#ef9b6c", "#f9ef06", "#a2c4d7", "#8d38fa",
                 "#953804", "#eb4782", "#320495", "#06f9f9", "#fbf560",
                 "#956c04", "#e619c5", "#f288ed")

def _extended_pocket_palette(base, total=256):
    """Stable distinct RGB values, keeping green reserved for ligand evidence."""
    colors = list(base)
    seen = set(colors)
    for index in range(4096):
        hue = (index * 0.6180339887498949) % 1.0
        if 0.22 <= hue <= 0.46:
            continue
        saturation = (0.78, 0.58, 0.91, 0.46)[(index // 7) % 4]
        lightness = (0.43, 0.58, 0.34, 0.68)[(index // 13) % 4]
        rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
        color = '#{:02x}{:02x}{:02x}'.format(*(round(value * 255) for value in rgb))
        if color not in seen:
            colors.append(color)
            seen.add(color)
            if len(colors) == total:
                break
    return tuple(colors)

POCKET_COLORS = _extended_pocket_palette(POCKET_COLORS)
POCKET_COLOR_NAMES = tuple(f'du_report_pocket_{i}' for i in range(1, len(POCKET_COLORS) + 1))
POCKET_COLOR_RGB = {name: tuple(int(color[i:i+2], 16) / 255 for i in (1, 3, 5))
                    for name, color in zip(POCKET_COLOR_NAMES, POCKET_COLORS)}
LIGAND_EVIDENCE_GREEN = '#009e43'


def candidate_pocket_number(candidate):
    """Resolve a site's recorded predicted-pocket identity, including merges."""
    evidence = candidate.get('evidence') or {}
    group = evidence.get('site_group') or evidence.get('site_group_presentation') or {}
    numbers = []
    identities = [candidate.get('id'), *(group.get('member_ids') or [])]
    for member in group.get('members') or []:
        identities.append(member.get('id') or member.get('label'))
    for identity in identities:
        match = re.fullmatch(r'P(\d+)', str(identity or ''), re.I)
        if match and int(match.group(1)) > 0:
            numbers.append(int(match.group(1)))
    if numbers:
        return min(numbers)
    return None


def candidate_display_label(candidate):
    """Name a merged site for its pocket; keep its stored identifier intact."""
    number = candidate_pocket_number(candidate)
    return f'P{number}' if number else str(candidate.get('label') or candidate.get('id') or '')


def region_pocket_number(region):
    """Use recorded grouped membership; never infer a match from proximity."""
    numbers = []
    for member in (region.get('site_group') or {}).get('members') or []:
        label = str(member.get('label') or member.get('id') or '')
        match = re.fullmatch(r'P(\d+)', label, re.I)
        if match and member.get('pocket_prediction'):
            numbers.append(int(match.group(1)))
    if numbers:
        return min(numbers)
    if region.get('site_source') == 'input_bound_ligand':
        return None
    match = re.fullmatch(r'P(\d+)', str(region.get('box_label') or ''), re.I)
    return int(match.group(1)) if match else None


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
