"""Select a PLIP site by retained identity, never contact count or proximity."""


def select_binding_site(root, *, ligand_id=None, chain=None, position=None):
    sites = root.findall('bindingsite')
    for key, value in {'hetid': ligand_id, 'chain': chain, 'position': position}.items():
        if value is not None:
            sites = [s for s in sites if (s.findtext('identifiers/' + key) or '').strip() == str(value)]
    if len(sites) != 1:
        raise ValueError('PLIP contacts require exactly one matching ligand site; retained identity is missing or ambiguous')
    return sites[0]


def retained_binding_site(root):
    # Older single-site experimental files remain readable. Multi-component
    # reports use the normalized UNL Z:1 identity written by our complex builder.
    if len(root.findall('bindingsite')) == 1:
        site = select_binding_site(root)
        if site.findtext('identifiers/ligtype') == 'ION':
            raise ValueError('Retained ligand contacts are missing; only an ion site was identified')
        if site.findtext('identifiers/hetid') == 'UNL':
            return select_binding_site(root, ligand_id='UNL', chain='Z', position='1')
        return site
    return select_binding_site(root, ligand_id='UNL', chain='Z', position='1')
