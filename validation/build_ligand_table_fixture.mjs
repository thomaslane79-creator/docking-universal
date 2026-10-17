// Synthetic import fixture, not experimental chemistry or docking results.
import fs from 'node:fs/promises';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const wb = Workbook.create();
const notes = wb.worksheets.add('Read me');
notes.getRange('A1:B2').values = [['Purpose', 'Description'], ['Synthetic fixture', 'Choose Compounds for import; no docking results.']];
const compounds = wb.worksheets.add('Compounds');
compounds.getRange('A1:D7').values = [
  ['Name', 'SMILES', 'Other chemistry', 'ID'],
  ['Alcohol', 'CCO', 'CCN', '001'],
  ['Chiral acid', 'C[C@H](O)C(=O)O', 'CC', '002'],
  ['Salt', '[NH4+].[Cl-]', 'CO', '003'],
  ['Invalid', 'not_smiles', 'CCC', '004'],
  ['Numeric', 123, 'CCO', '005'],
  ['Formula', null, 'CCO', '006'],
];
compounds.getRange('B7').formulas = [['="CCO"']];
for (const [sheet, range] of [[notes, 'A1:B2'], [compounds, 'A1:D7']]) {
  sheet.showGridLines = false;
  sheet.getRange(range).format.font = {name: 'Arial', size: 10};
  sheet.getRange(range).format.columnWidth = 26;
  sheet.getRange(range).format.rowHeight = 22;
  sheet.getRange(range.split(':')[0] + ':' + range.split(':')[1].replace(/\d+$/, '1')).format = {
    fill: '#26374A', font: {name: 'Arial', size: 10, bold: true, color: '#FFFFFF'},
  };
}
notes.getRange('B1:B2').format.columnWidth = 65;
wb.recalculate();
console.log((await wb.inspect({kind: 'region', sheetId: 'Compounds', range: 'A1:D7', maxChars: 2500})).ndjson);
await fs.mkdir('tests/fixtures', {recursive: true});
await fs.mkdir('validation/runs/tabular-ligands-20261017', {recursive: true});
await (await SpreadsheetFile.exportXlsx(wb)).save('tests/fixtures/ligand_tables.xlsx');
const png = await wb.render({sheetName: 'Compounds', range: 'A1:D7', scale: 1.5, format: 'png'});
await fs.writeFile('validation/runs/tabular-ligands-20261017/fixture.png', new Uint8Array(await png.arrayBuffer()));
