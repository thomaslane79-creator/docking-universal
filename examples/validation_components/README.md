# Modified-residue validation definitions

These two small, public CSO definitions let the cross-platform integration
suite exercise the reviewed GeoStd/CCD-to-Meeko bridge against the deposited
CSO residues in the bundled 1HVR example without performing a network request.

- `CSO_geostd.cif` is the CSO restraint definition from the pinned
  `phenix-project/geostd` revision recorded by Docking Universal. GeoStd's
  license and copyright notices are retained with the bundled minimal library.
- `CSO_ccd.cif` is the public RCSB PDB Chemical Component Dictionary entry for
  CSO retrieved on 2026-09-28.

They are validation fixtures, not an implicit general-purpose component
database. Production preparation still discloses exact requested component
identifiers and requires consent before downloading a missing definition.
