"""Engine-neutral residue callouts for saved PLIP report figures."""


def round_contact_label_backgrounds(rendered, unlabeled, callouts):
    """Replace ray-traced rectangular callouts with foreground rounded badges.

    The second image restores the same molecular pixels behind each label;
    then the foreground leaders and badges are drawn at the export resolution.
    """
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont

    original = Image.open(rendered)
    mode, dpi = original.mode, original.info.get('dpi')
    picture = original.convert('RGBA')
    base = Image.open(unlabeled).convert('RGBA')
    if picture.size != base.size:
        raise ValueError('Label-free render does not match the labeled image')
    width, height = picture.size
    font_size = 40
    fonts = ['/System/Library/Fonts/Supplemental/Arial Bold.ttf', 'arialbd.ttf', 'DejaVuSans-Bold.ttf']
    for candidate in fonts:
        try:
            font = ImageFont.truetype(candidate, font_size)
            break
        except OSError:
            continue
    else:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(picture)
    badges = []
    for row in callouts:
        x, y = row['screen_point'][:2]
        cx, cy = (x + 1) * width / 2, (1 - y) * height / 2
        label = row['label']
        text_box = draw.textbbox((0, 0), label, font=font)
        text_width, text_height = text_box[2] - text_box[0], text_box[3] - text_box[1]
        half_w, half_h = text_width / 2 + 11, text_height / 2 + 9
        rect = (int(cx-half_w), int(cy-half_h), int(cx+half_w), int(cy+half_h))
        # Include the old rectangular background, whose padding is slightly
        # larger than the rounded outline, before painting the new badge.
        restore = (max(0, rect[0]-24), max(0, rect[1]-24), min(width, rect[2]+24), min(height, rect[3]+24))
        picture.paste(base.crop(restore), restore)
        badges.append((row, cx, cy, rect,
                       (cx-text_width/2-text_box[0], cy-text_height/2-text_box[1])))
    for row, cx, cy, _, _ in badges:
        anchor = row.get('anchor_screen_point')
        if anchor is None:
            continue
        ax, ay = (anchor[0] + 1) * width / 2, (1 - anchor[1]) * height / 2
        points = [(cx, cy), (ax, ay)]
        stroke = max(2, round(width / 300))
        draw.line(points, fill='white', width=stroke + max(2, stroke // 2))
        draw.line(points, fill='#252525', width=stroke)
        radius = max(2, stroke)
        draw.ellipse((ax-radius, ay-radius, ax+radius, ay+radius),
                     fill='#252525', outline='white', width=max(1, stroke // 3))
    for row, _, _, rect, origin in badges:
        draw.rounded_rectangle(rect, radius=10, fill='white', outline='#333333', width=2)
        draw.text(origin, row['label'], font=font, fill='black')
    picture.convert('RGBA' if mode == 'RGBA' else 'RGB').save(Path(rendered), **({'dpi': dpi} if dpi else {}))


def label_contact_residues(cmd, *, size=40, viewport=None):
    """Label one anchor per retained PLIP-contacting residue, without moving atoms.

    Screen-relative placement is intentional: float_labels alone has no effect
    in PyMOL ray tracing. The negative depth keeps callouts in front in the
    ray-traced report views; custom scene exports opt into this style.
    """
    import math

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
    anchors = {}
    if viewport:
        width, height = viewport
        tangent = math.tan(math.radians(cmd.get_setting_float('field_of_view') / 2))
        orthoscopic = cmd.get_setting_int('orthoscopic')
    projected=[]
    for key,row in residues.items():
        selection=f"model {row['model']} and index {row['index']}"
        xyz = (np.asarray(cmd.get_atom_coords(selection)) - origin) @ rotation
        projected.append((float(xyz[0]),float(xyz[1]),key))
        if viewport:
            camera = xyz + view[9:12]
            depth = -view[11] if orthoscopic else -camera[2]
            if depth > 0:
                half_height = depth * tangent
                x = float(camera[0] / (half_height * width / height))
                y = float(camera[1] / half_height)
                if abs(x) <= 1 and abs(y) <= 1:
                    anchors[key] = [x, y]
    projected.sort();split=(len(projected)+1)//2;placements={}
    for side,group in ((-1,projected[:split]),(1,projected[split:])):
        for i,(_,_,key) in enumerate(sorted(group,key=lambda r:r[1])):
            y=-.58+i*1.16/(len(group)-1) if len(group)>1 else 0.
            placements[key]=[side*.68,y,-1.]
    cmd.hide('labels','all')
    for name,value in {'label_color':'black','label_outline_color':'white','label_font_id':7,
        'label_size':size,'float_labels':1,'label_shadow_mode':0,'label_connector':0 if viewport else 1,
        'label_connector_color':'gray10','label_connector_width':5.0,'label_position':[0,0,0],
        'label_bg_color':'white','label_bg_transparency':0.}.items():cmd.set(name,value)
    result=[]
    for key,row in sorted(residues.items()):
        selection=f"model {row['model']} and index {row['index']}"
        label=f"{row['resn'].capitalize()}{row['resi']}{row['chain']}"
        cmd.label(selection,repr(label));cmd.set('label_relative_mode',1,selection)
        cmd.set('label_screen_point',placements[key],selection)
        result.append({**row,'label':label,'screen_point':placements[key],
                       'anchor_screen_point':anchors.get(key)})
    cmd.deselect()
    return result
