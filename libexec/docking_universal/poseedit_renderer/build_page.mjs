import fs from 'node:fs';
import path from 'node:path';

const outputRoot = process.argv[2];
const assetsRoot = process.argv[3];
if (!outputRoot || !assetsRoot) throw new Error('usage: build_page.mjs OUTPUT_ROOT ASSETS_ROOT');

fs.mkdirSync(outputRoot, {recursive: true});
for (const name of [
  'interaction-drawer.js', 'd3.min.js', 'fraction.min.js',
  'smiles-drawer.min.js', 'pack-scene.js',
]) {
  fs.copyFileSync(path.join(assetsRoot, name), path.join(outputRoot, name));
}
const actualPose = fs.readFileSync(path.join(outputRoot, 'actual-pose-base.json'), 'utf8');
fs.writeFileSync(path.join(outputRoot, 'actual-pose-data.js'), `window.actualPoseScene = ${actualPose};\n`);

const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#fff;font-family:Arial,sans-serif}
#wrap{width:1200px;height:900px;position:relative;overflow:hidden;background:#fff}
#draw-area{width:1200px;height:900px;display:block}
#status{position:absolute;left:14px;top:12px;color:#555;font:14px Arial}
</style></head><body><div id="wrap"><div id="status">Rendering locally…</div><svg id="draw-area"></svg></div>
<script src="d3.min.js"></script><script src="fraction.min.js"></script>
<script src="smiles-drawer.min.js"></script><script src="interaction-drawer.js"></script>
<script src="TestJson.js"></script><script>
try {
  const drawer = new window.InteractionDrawerClass('draw-area', {allowInteraction: false});
  drawer.addByJSON(JSON.stringify(interactionDrawerTestJson));
  document.getElementById('status').remove();
  window.__renderDone = true;
} catch (error) {
  document.getElementById('status').textContent = 'Render error: ' + error.stack;
  window.__renderError = String(error.stack || error);
}
</script></body></html>`;
fs.writeFileSync(path.join(outputRoot, 'index.html'), html);

const actualHtml = `<!doctype html>
<html><head><meta charset="utf-8"><style>
html,body{margin:0;background:#fff;font-family:Arial,sans-serif}
#wrap{width:920px;height:620px;position:relative;overflow:hidden;background:#fff}
#draw-area{width:920px;height:565px;display:block}
#legend{position:absolute;z-index:2;left:50%;bottom:10px;transform:translateX(-50%);padding:7px 10px;border:1px solid #d9e2f3;border-radius:7px;background:#f7f9fd;color:#355a93;display:flex;gap:18px;align-items:center;white-space:nowrap;font:13px Arial}
.hbond{display:inline-block;width:28px;border-top:2px dashed #5f92ff;margin-right:6px;vertical-align:middle}
.hydro{display:inline-block;width:28px;border-top:2px solid #009b49;margin-right:6px;vertical-align:middle}
.pipi{display:inline-block;width:28px;border-top:3px double #33cccc;margin-right:6px;vertical-align:middle}
</style></head><body><div id="wrap"><svg id="draw-area"></svg><div id="legend"><span><i class="hbond"></i>Hydrogen bond</span><span><i class="hydro"></i>Hydrophobic contact</span><span id="pi-legend"><i class="pipi"></i>π–π stacking</span></div></div>
<script src="d3.min.js"></script><script src="fraction.min.js"></script>
<script src="smiles-drawer.min.js"></script><script src="interaction-drawer.js"></script>
<script src="actual-pose-data.js"></script><script src="plip-conversion-data.js"></script><script src="hydrophobic-layout-data.js"></script><script src="pack-scene.js"></script><script>
try {
  const scene = window.actualPoseScene.scene;
  const plip = window.plipConversion;
  if (!(plip.piStackings || []).length) document.getElementById('pi-legend').remove();
  const templates = window.InteractionDrawerTemplates;
  const byAtom = Object.fromEntries(scene.structures[0].atoms.map(atom => [atom.id, atom]));
  const residueTargets = [];
  function addTemplate(name, label, center, contact, targetPicker) {
    const ligandAtomId = contact.ligandAtomId;
    const structure = structuredClone(templates[name].scene.structures[0]);
    const sid = scene.structures.length;
    const idMap = new Map();
    structure.atoms.forEach((atom, index) => idMap.set(atom.id, 50000 + sid * 1000 + index));
    structure.atoms.forEach(atom => atom.id = idMap.get(atom.id));
    structure.bonds.forEach((bond, index) => {
      bond.id = 60000 + sid * 1000 + index;
      bond.from = idMap.get(bond.from); bond.to = idMap.get(bond.to);
    });
    (structure.rings || []).forEach((ring, index) => {
      ring.id = 70000 + sid * 1000 + index;
      ring.atoms = ring.atoms.map(id => idMap.get(id));
    });
    structure.id = sid; structure.structureName = label; structure.structureLabel = label;
    structure.atoms.forEach(atom => {
      if (atom.charge && !Number.isInteger(atom.charge)) {
        atom.additionalInformation = Object.assign({}, atom.additionalInformation, {
          suppressedFractionalCharge: atom.charge,
          displayPolicy: 'fractional template charge hidden in compact view'
        });
        atom.charge = 0;
      }
    });
    if (name === 'BACKBONE') structure.atoms[4].label = label;
    else structure.atoms[0].label = label;
    const target = targetPicker(structure.atoms);
    const cx = structure.atoms.reduce((sum, atom) => sum + atom.coordinates.x, 0) / structure.atoms.length;
    const cy = structure.atoms.reduce((sum, atom) => sum + atom.coordinates.y, 0) / structure.atoms.length;
    const ligand = byAtom[ligandAtomId].coordinates;
    const current = Math.atan2(target.coordinates.y - cy, target.coordinates.x - cx);
    const desired = Math.atan2(ligand.y - center.y, ligand.x - center.x);
    const angle = desired - current, cos = Math.cos(angle), sin = Math.sin(angle);
    structure.atoms.forEach(atom => {
      const x = atom.coordinates.x - cx, y = atom.coordinates.y - cy;
      atom.coordinates = {x: center.x + x * cos - y * sin, y: center.y + x * sin + y * cos};
    });
    scene.structures.push(structure);
    residueTargets.push({sid, atomId: target.id, ligandAtomId, contact, targetCoordinates:target.coordinates});
  }
  const backboneN = atoms => atoms.find(atom => atom.element === 'N');
  const sidechainAtom = (atoms, contact) => {
    const element = (contact.proteinAtom || '').replace(/[^A-Za-z]/g, '').slice(0, 1).toUpperCase();
    const candidates = atoms.filter(atom => atom.element === element);
    if (element === 'N') return candidates.find(atom => atom.charge > 0) || candidates.at(-1);
    return candidates.at(-1) || atoms.at(-1);
  };
  const sideCounts = {left:0,right:0};
  const sideTotals = {
    left:plip.hydrogenBonds.filter(c => byAtom[c.ligandAtomId].coordinates.x < 0).length,
    right:plip.hydrogenBonds.filter(c => byAtom[c.ligandAtomId].coordinates.x >= 0).length
  };
  plip.hydrogenBonds.forEach(contact => {
    const side = byAtom[contact.ligandAtomId].coordinates.x < 0 ? 'left' : 'right';
    const index = sideCounts[side]++;
    const total = sideTotals[side];
    const y = total === 1 ? 55 : -52 + index * 105 / (total - 1);
    const center = {x:side === 'left' ? -195 : 190,y};
    const template = contact.contextKind === 'side_chain' && templates[contact.residueName + 'SIDECHAIN']
      ? contact.residueName + 'SIDECHAIN' : 'BACKBONE';
    const picker = template === 'BACKBONE' ? backboneN : atoms => sidechainAtom(atoms, contact);
    const label = contact.residueName[0] + contact.residueName.slice(1).toLowerCase() + contact.residueNumber + contact.chain;
    addTemplate(template, label, center, contact, picker);
  });
  scene.atomPairInteractions = residueTargets.map((pair, id) => ({
    id, fromStructure: 0, toStructure: pair.sid, from: pair.ligandAtomId, to: pair.atomId,
    additionalInformation: Object.assign({source:'PLIP XML',interactionType:'hydrogen_bond'}, pair.contact)
  }));
  scene.piStackings = [];
  (plip.piStackings || []).forEach((contact,index) => {
    const templateName=contact.residueName+'SIDECHAIN';
    if (!templates[templateName]) return;
    const structure=structuredClone(templates[templateName].scene.structures[0]);
    const sid=scene.structures.length;
    const idMap=new Map();
    structure.atoms.forEach((atom,atomIndex)=>idMap.set(atom.id,80000+sid*1000+atomIndex));
    structure.atoms.forEach(atom=>atom.id=idMap.get(atom.id));
    structure.bonds.forEach((bond,bondIndex)=>{
      bond.id=90000+sid*1000+bondIndex;
      bond.from=idMap.get(bond.from); bond.to=idMap.get(bond.to);
    });
    (structure.rings || []).forEach((ring,ringIndex)=>{
      ring.id=100000+sid*1000+ringIndex;
      ring.atoms=ring.atoms.map(atomId=>idMap.get(atomId));
    });
    const ligandRing=scene.structures[0].rings.find(ring=>ring.id===contact.ligandRingId);
    const ligandRingAtoms=ligandRing.atoms.map(atomId=>byAtom[atomId]);
    const ringCenter={
      x:ligandRingAtoms.reduce((sum,atom)=>sum+atom.coordinates.x,0)/ligandRingAtoms.length,
      y:ligandRingAtoms.reduce((sum,atom)=>sum+atom.coordinates.y,0)/ligandRingAtoms.length
    };
    const placement={
      'TRP86':{x:72,y:54},
      'TRP286':{x:-68,y:-68},
      'TYR341':{x:-70,y:72}
    }[contact.residueName+contact.residueNumber] || {x:70,y:70};
    const center={x:ringCenter.x+placement.x,y:ringCenter.y+placement.y};
    const cx=structure.atoms.reduce((sum,atom)=>sum+atom.coordinates.x,0)/structure.atoms.length;
    const cy=structure.atoms.reduce((sum,atom)=>sum+atom.coordinates.y,0)/structure.atoms.length;
    structure.atoms.forEach(atom=>atom.coordinates={x:atom.coordinates.x-cx+center.x,y:atom.coordinates.y-cy+center.y});
    const label=contact.residueName[0]+contact.residueName.slice(1).toLowerCase()+contact.residueNumber+contact.chain;
    const labelAtom=structure.atoms.find(atom=>atom.element==='R') || structure.atoms[0];
    labelAtom.label=label;
    structure.id=sid; structure.structureName=label; structure.structureLabel=label;
    scene.structures.push(structure);
    const proteinRing=(structure.rings || []).find(ring=>ring.atoms.length===6) || structure.rings[0];
    scene.piStackings.push({
      id:index,fromStructure:0,toStructure:sid,from:contact.ligandRingId,to:proteinRing.id,
      additionalInformation:Object.assign({source:'PLIP XML',interactionType:'pi_stacking'},contact)
    });
  });
  const ligandCenter = {
    x:scene.structures[0].atoms.reduce((sum,atom)=>sum+atom.coordinates.x,0)/scene.structures[0].atoms.length,
    y:scene.structures[0].atoms.reduce((sum,atom)=>sum+atom.coordinates.y,0)/scene.structures[0].atoms.length
  };
  const directionOf=contact=>{
    const projected=contact.projectedProteinDirection2D;
    if (projected && Math.hypot(projected[0],projected[1])>0.1) return {x:projected[0],y:projected[1]};
    const atom=byAtom[contact.ligandAtomId].coordinates;
    const dx=atom.x-ligandCenter.x,dy=atom.y-ligandCenter.y,length=Math.hypot(dx,dy)||1;
    return {x:dx/length,y:dy/length};
  };
  const angleOf=contact=>{const direction=directionOf(contact);return Math.atan2(direction.y,direction.x);};
  const angular=[...plip.hydrophobicContacts].sort((a,b)=>angleOf(a)-angleOf(b));
  const hydroGroups=[];
  angular.forEach(contact => {
    const previous=hydroGroups.at(-1);
    const gap=previous ? angleOf(contact)-angleOf(previous.at(-1)) : Infinity;
    if (!previous || gap>0.72) hydroGroups.push([contact]);
    else previous.push(contact);
  });
  if (hydroGroups.length>1) {
    const circularGap=(angleOf(hydroGroups[0][0])+Math.PI*2)-angleOf(hydroGroups.at(-1).at(-1));
    if (circularGap<=0.72) hydroGroups[0]=hydroGroups.pop().concat(hydroGroups[0]);
  }
  scene.hydrophobicContacts=window.hydrophobicLayout.hydrophobicContacts;
  scene.annotations=window.hydrophobicLayout.annotations;
  window.packScene(scene);
  const drawer = new window.InteractionDrawerClass('draw-area', {allowInteraction:false});
  drawer.addByJSON(JSON.stringify({scene}));
  window.__sceneJson = drawer.getJson();
  window.__renderDone = true;
} catch (error) {
  document.getElementById('legend').textContent = 'Render error: ' + error;
  window.__renderError = String(error.stack || error);
}
</script></body></html>`;
fs.writeFileSync(path.join(outputRoot, 'actual.html'), actualHtml);
console.log(outputRoot);
