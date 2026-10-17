// Keep schematic residues legible but secondary; never alter source 3D data.
window.poseDiagramStyle = {textSize:10, lineWidth:0.9};
window.matchResidueBondScale = function(structure, ligand) {
  const medianBond = s => {
    const atoms = new Map(s.atoms.map(a => [a.id, a.coordinates]));
    const lengths = s.bonds.map(b => {
      const a = atoms.get(b.from), c = atoms.get(b.to);
      return Math.hypot(a.x-c.x, a.y-c.y);
    }).filter(n => Number.isFinite(n) && n > 0).sort((a,b) => a-b);
    const i = Math.floor(lengths.length/2);
    return lengths.length ? (lengths[i] + lengths[Math.floor((lengths.length-1)/2)])/2 : null;
  };
  const ligandBond = medianBond(ligand), residueBond = medianBond(structure);
  if (!ligandBond || !residueBond) throw new Error('Cannot establish residue/ligand drawing scale');
  const relativeBondSize = 0.7;
  const scale = relativeBondSize*ligandBond/residueBond;
  const center = {
    x:structure.atoms.reduce((n,a) => n+a.coordinates.x,0)/structure.atoms.length,
    y:structure.atoms.reduce((n,a) => n+a.coordinates.y,0)/structure.atoms.length,
  };
  for (const atom of structure.atoms) {
    atom.coordinates = {x:center.x+(atom.coordinates.x-center.x)*scale,
                        y:center.y+(atom.coordinates.y-center.y)*scale};
  }
  structure.additionalInformation = Object.assign({}, structure.additionalInformation, {
    drawingScalePolicy:'ligand-relative-residue-bonds-v1', residueScaleFactor:scale,
    residueToLigandBondRatio:relativeBondSize,
    ligandMedianBondLength:ligandBond, originalResidueMedianBondLength:residueBond,
  });
  return scale;
};
