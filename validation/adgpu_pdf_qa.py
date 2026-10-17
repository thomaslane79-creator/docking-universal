#!/usr/bin/env python3
"""Render every compact-callout PDF page and compare unchanged pages to reviewed pixels."""
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image, ImageChops
from docking_universal.ad4_gpu import digest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'validation/runs/adgpu-integration-20261016'
record=json.loads((BASE/'gui-ready/summary.json').read_text())
old=BASE/'pdf-visual-qa.json'
shutil.copy2(old,BASE/'pdf-visual-qa-before-compact.json')
result={'status':'awaiting_changed_page_visual_review','changed_pages':{},'unchanged_reviewed_pages':{},
        'inspection':'All pages rendered; unchanged pages match previously visually inspected page pixels exactly.'}
for kind,key in (('protocol','protocol_report'),('screen','screening_report')):
    folder=ROOT/f'tmp/pdfs/adgpu-compact-{kind}';folder.mkdir(parents=True,exist_ok=False)
    with (folder/'render.log').open('w') as log:
        subprocess.run(['/opt/homebrew/bin/pdftoppm','-scale-to','1100','-png',record[key],str(folder/'page')],
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    changed=[];same=[]
    for page in sorted(folder.glob('page-*.png')):
        previous=ROOT/f'tmp/pdfs/adgpu-final-{kind}'/page.name
        new_image=Image.open(page).convert('RGB');old_image=Image.open(previous).convert('RGB') if previous.is_file() else None
        if old_image is not None and new_image.size==old_image.size and ImageChops.difference(new_image,old_image).getbbox() is None:
            same.append(page.name)
        else:changed.append(page.name)
    result['changed_pages'][kind]=changed;result['unchanged_reviewed_pages'][kind]=same
    result[key+'_sha256']=digest(record[key]);result[kind+'_pages']=len(changed)+len(same)
(BASE/'pdf-visual-qa.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
