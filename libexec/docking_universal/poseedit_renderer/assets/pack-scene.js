// Deterministic placement using padded atom labels, sampled bonds and contours.
window.packScene = function(scene) {
  const context=document.createElement('canvas').getContext('2d');
  context.font='6.5px Arial';
  const textWidth=text=>context.measureText(text).width;
  const rect = (x,y,w,h)=>({l:x-w/2,r:x+w/2,t:y-h/2,b:y+h/2});
  const hit=(a,b)=>a.l<b.r && b.l<a.r && a.t<b.b && b.t<a.b;
  const pointBox=p=>rect(p.x,p.y,4,4);
  function line(a,b) {
    const n=Math.max(2,Math.ceil(Math.hypot(b.x-a.x,b.y-a.y)/2));
    return Array.from({length:n+1},(_,i)=>({x:a.x+(b.x-a.x)*i/n,y:a.y+(b.y-a.y)*i/n}));
  }
  function geometry(s) {
    const atoms=new Map(s.atoms.map(a=>[a.id,a]));
    return s.atoms.map(a=>rect(a.coordinates.x,a.coordinates.y,
      a.label && a.element!=='C' ? Math.max(8,textWidth(a.label)+4):7,10)).concat(
      s.bonds.flatMap(b=>line(atoms.get(b.from).coordinates,atoms.get(b.to).coordinates).map(pointBox)));
  }
  const contourBoxes=scene.hydrophobicContacts.flatMap(c=>c.controlPoints.slice(1).flatMap((p,i)=>line(c.controlPoints[i],p).map(pointBox)));
  const occupied=geometry(scene.structures[0]).concat(contourBoxes);
  const connectors=[];
  const ligand=scene.structures[0];
  const center=(s,ids)=>{
    const atoms=s.atoms.filter(a=>ids.includes(a.id));
    return {x:atoms.reduce((v,a)=>v+a.coordinates.x,0)/atoms.length,y:atoms.reduce((v,a)=>v+a.coordinates.y,0)/atoms.length};
  };
  const records=[];
  function placeResidues() { for(const s of scene.structures.slice(1)) {
    const pi=scene.piStackings.find(p=>p.toStructure===s.id);
    const hb=scene.atomPairInteractions.find(p=>p.toStructure===s.id);
    const interaction=pi||hb;
    if(!interaction) continue;
    const source=pi?center(ligand,ligand.rings.find(r=>r.id===pi.from).atoms):ligand.atoms.find(a=>a.id===hb.from).coordinates;
    const endpoint=pi?center(s,s.rings.find(r=>r.id===pi.to).atoms):s.atoms.find(a=>a.id===hb.to).coordinates;
    const original=s.atoms.map(a=>({...a.coordinates}));
    let best=null;
    for(const radius of [65,85,105,130,160,200]) {
      for(let k=0;k<72;k++) for(let rotation=0;rotation<8;rotation++) {
        const angle=k*Math.PI/36, turn=rotation*Math.PI/4, c=Math.cos(turn),sn=Math.sin(turn);
        const target={x:source.x+radius*Math.cos(angle),y:source.y+radius*Math.sin(angle)};
        s.atoms.forEach((a,i)=>{const x=original[i].x-endpoint.x,y=original[i].y-endpoint.y;a.coordinates={x:target.x+x*c-y*sn,y:target.y+x*sn+y*c};});
        const boxes=geometry(s);
        let collisions=0;
        for(const box of boxes) if(occupied.some(o=>hit(box,o))) collisions++;
        const route=line(source,target);
        for(const p of route.filter(p=>Math.hypot(p.x-target.x,p.y-target.y)>(pi?25:13))) {
          if(boxes.some(o=>hit(pointBox(p),o)))collisions++;
        }
        const labelObstacles=s.atoms.filter(a=>a.element==='R' && a.label).map(a=>rect(a.coordinates.x,a.coordinates.y,textWidth(a.label)+4,10));
        for(const p of route) if(labelObstacles.some(o=>hit(pointBox(p),o)))collisions++;
        // The first part of a ring-centroid connector necessarily traverses its own ring.
        for(const p of route.filter(p=>Math.hypot(p.x-source.x,p.y-source.y)>27)) {
          if(occupied.some(o=>hit(pointBox(p),o))) collisions++;
        }
        const score=collisions*100000+radius+Math.abs(target.y)*0.06;
        if(!best||score<best.score)best={score,collisions,coords:s.atoms.map(a=>({...a.coordinates})),route,boxes};
      }
      if(best.collisions===0)break;
    }
    s.atoms.forEach((a,i)=>a.coordinates=best.coords[i]);
    occupied.push(...best.boxes,...best.route.slice(14).map(pointBox));
    connectors.push(...best.route);
    records.push({structure:s.structureLabel,remainingGeometryHits:best.collisions});
  } }
  placeResidues();
  const labelRecords=[];
  for(const a of scene.annotations) {
    const origin={...a.coordinates},w=textWidth(a.label)+3,h=9;
    let best=null;
    const contour=scene.hydrophobicContacts.find(c=>c.id===a.additionalInformation.splineId);
    const cps=contour.controlPoints;
    const candidates=cps.slice(1).flatMap((p,i)=>line(cps[i],p));
    const allContours=scene.hydrophobicContacts.map(c=>({id:c.id,points:c.controlPoints.slice(1).flatMap((p,i)=>line(c.controlPoints[i],p))}));
    for(const anchor of candidates) {
      const nearestAtom=ligand.atoms.reduce((best,atom)=>Math.hypot(atom.coordinates.x-anchor.x,atom.coordinates.y-anchor.y)<Math.hypot(best.coordinates.x-anchor.x,best.coordinates.y-anchor.y)?atom:best);
      const dx=anchor.x-nearestAtom.coordinates.x,dy=anchor.y-nearestAtom.coordinates.y,len=Math.hypot(dx,dy)||1;
      const nx=dx/len,ny=dy/len;
      // Position the text edge, rather than its centre, a fixed gap from the curve.
      for(const gap of [7,14,22,30,40]) for(const slide of [-48,-32,-16,0,16,32,48]) for(const side of [1,-1]) {
        const support=Math.abs(nx)*w/2+Math.abs(ny)*h/2;
        const p={x:anchor.x+side*nx*(support+gap)-ny*slide,y:anchor.y+side*ny*(support+gap)+nx*slide};
        const box=rect(p.x,p.y,w,h),hits=occupied.filter(o=>hit(box,o)).length;
        const edgeDistance=q=>Math.hypot(Math.max(box.l-q.x,0,q.x-box.r),Math.max(box.t-q.y,0,q.y-box.b));
        const ownDistance=Math.min(...candidates.map(edgeDistance));
        const ambiguous=allContours.some(c=>c.id!==contour.id && Math.min(...c.points.map(edgeDistance))<=ownDistance+3);
        const score=hits*100000+(ambiguous?50000:0)+Math.hypot(p.x-origin.x,p.y-origin.y)*0.15+ownDistance*5;
        if(!best||score<best.score)best={score,hits,p,box,gap:ownDistance,ambiguous};
      }
    }
    a.coordinates=best.p;occupied.push(best.box);
    labelRecords.push({label:a.label,remainingGeometryHits:best.hits,contourGap:best.gap,ambiguous:best.ambiguous});
  }
  window.__packingAudit={structures:records,labels:labelRecords};
};
