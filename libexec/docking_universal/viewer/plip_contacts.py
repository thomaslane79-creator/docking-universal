"""Contact geometry from the exact PLIP report; no new chemical perception."""
import math
import xml.etree.ElementTree as ET

# The first three colors match the retained 2D renderer legend.
STYLES = {
    'hydrogen_bond': ('Hydrogen bond', '#5f92ff', True),
    'hydrophobic_interaction': ('Hydrophobic contact', '#009b49', False),
    'pi_stack': ('π–π stacking', '#33cccc', True),
    'salt_bridge': ('Salt bridge', '#d89200', True),
    'pi_cation_interaction': ('π–cation', '#b46bd3', True),
    'water_bridge': ('Water bridge', '#749dff', True),
    'halogen_bond': ('Halogen bond', '#ce55bd', True),
    'metal_complex': ('Metal coordination', '#777777', True),
}


def contacts(path):
    sites = ET.parse(path).getroot().findall('bindingsite')
    if len(sites) != 1:
        raise ValueError('3D contacts require exactly one identified ligand site')
    def coord(item, name):
        node = item.find(name)
        if node is None:
            return None
        point = tuple(float(node.findtext(axis)) for axis in 'xyz')
        if not all(math.isfinite(v) for v in point):
            raise ValueError('Non-finite PLIP contact coordinates')
        return point
    result = []
    for item in sites[0].findall('interactions/*/*'):
        if item.tag not in STYLES:
            continue
        first, second = ('metalcoo', 'targetcoo') if item.tag == 'metal_complex' else ('ligcoo', 'protcoo')
        a, b = coord(item, first), coord(item, second)
        if a is None or b is None:
            continue
        residue = dict(chain=item.findtext('reschain') or '', number=item.findtext('resnr') or '',
                       name=item.findtext('restype') or '')
        water = coord(item, 'watercoo') if item.tag == 'water_bridge' else None
        for start, end in ([(a, water), (water, b)] if water is not None else [(a, b)]):
            result.append(dict(kind=item.tag, residue=residue, start=start, end=end))
    return result
