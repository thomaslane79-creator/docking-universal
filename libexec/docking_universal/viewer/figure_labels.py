"""Engine-neutral residue callouts for saved PLIP report figures."""


def label_contact_residues(cmd, *, size=40):
    """Label one anchor per retained PLIP-contacting residue, without moving atoms.

    Screen-relative front-plane placement is intentional: float_labels alone
    has no effect in PyMOL ray tracing. Custom scene exports opt into this style.
    """
    import numpy as np
    selections=[n for n in cmd.get_names('selections') if n.startswith('plip_contact_residues_chain_')]
    if not selections:return []
    rows=[]
    cmd.iterate('('+' or '.join(selections)+') and polymer.protein',
        "rows.append({'model':model,'index':index,'name':name,'resn':resn,'resi':resi,'chain':chain,'segi':segi})",
        space={'rows':rows})
    residues={}
    for row in rows:
        key=(row['model'],row['segi'],row['chain'],row['resi'])
        if key not in residues or (row['name']=='CA' and residues[key]['name']!='CA'):residues[key]=row
    view=cmd.get_view();rotation=np.asarray(view[:9]).reshape(3,3);origin=np.asarray(view[12:15])
    projected=[]
    for key,row in residues.items():
        selection=f"model {row['model']} and index {row['index']}"
        xyz=rotation@(np.asarray(cmd.get_atom_coords(selection))-origin)
        projected.append((float(xyz[0]),float(xyz[1]),key))
    projected.sort();split=(len(projected)+1)//2;placements={}
    for side,group in ((-1,projected[:split]),(1,projected[split:])):
        for i,(_,_,key) in enumerate(sorted(group,key=lambda r:r[1])):
            y=-.58+i*1.16/(len(group)-1) if len(group)>1 else 0.
            placements[key]=[side*.68,y,1.]
    cmd.hide('labels','all')
    for name,value in {'label_color':'black','label_outline_color':'white','label_font_id':7,
        'label_size':size,'float_labels':1,'label_shadow_mode':0,'label_connector':1,
        'label_connector_color':'gray50','label_connector_width':1.5,'label_position':[0,0,0],
        'label_bg_color':'white','label_bg_transparency':0.}.items():cmd.set(name,value)
    result=[]
    for key,row in sorted(residues.items()):
        selection=f"model {row['model']} and index {row['index']}"
        label=f"{row['resn'].capitalize()}{row['resi']}{row['chain']}"
        cmd.label(selection,repr(label));cmd.set('label_relative_mode',1,selection)
        cmd.set('label_screen_point',placements[key],selection)
        result.append({**row,'label':label,'screen_point':placements[key]})
    cmd.deselect()
    return result
