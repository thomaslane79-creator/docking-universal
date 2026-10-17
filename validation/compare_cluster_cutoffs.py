"""Compare retained top-three representatives in one frame; never redock or fit."""
import argparse
import csv
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rdkit import Chem
from rdkit.Chem import rdMolAlign


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analyses", nargs=2, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--pymol", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    reference = Chem.RemoveHs(next(m for m in Chem.SDMolSupplier(str(args.reference)) if m))
    datasets = []
    for analysis in args.analyses:
        manifest = json.loads((analysis / "clustering_manifest.json").read_text())
        with (analysis / "cluster_summary.csv").open() as handle:
            rows = list(csv.DictReader(handle))[:3]
        poses, details = [], []
        for row in rows:
            cluster = analysis / f"cluster_{int(row['cluster_id']):03d}"
            record = json.loads((cluster / "cluster.json").read_text())
            sdf = cluster / "representative.sdf"
            mol = Chem.RemoveHs(next(m for m in Chem.SDMolSupplier(str(sdf)) if m))
            poses.append(mol)
            details.append(dict(rank=int(row["energy_rank"]), cluster_id=int(row["cluster_id"]),
                                pose_id=record["representative_index"] + 1,
                                energy_kcal_mol=float(row["best_energy_kcal_per_mol"]),
                                crystal_rmsd_A=rdMolAlign.CalcRMS(mol, reference, maxMatches=100000),
                                population=int(row["pose_count"]), sdf=str(sdf.resolve())))
        pairs = [{"ranks": [i+1, j+1], "rmsd_A": rdMolAlign.CalcRMS(poses[i], poses[j], maxMatches=100000)}
                 for i in range(3) for j in range(i+1, 3)]
        datasets.append(dict(cutoff_A=manifest["cluster_rmsd_angstrom"],
                             cluster_count=manifest["cluster_count"], pose_count=manifest["pose_count"],
                             representatives=details, pairwise=pairs))
    # One camera derived once from the crystal; no ligand is aligned or fitted.
    lines = ["reinitialize", f'load "{args.reference.resolve()}", crystal',
             "hide everything, all", "remove hydro", "bg_color white",
             "color gray75, crystal", "show sticks, crystal", "set stick_radius, 0.14",
             "set ray_opaque_background, on", "set orthoscopic, on", "orient crystal", "zoom crystal, 4",
             "python", "from pymol import cmd", "shared_view = cmd.get_view()", "python end"]
    for index, data in enumerate(datasets):
        for rep, color in zip(data["representatives"], ("red", "marine", "gold")):
            obj = f"cutoff_{index}_rank_{rep['rank']}"
            lines += [f'load "{rep["sdf"]}", {obj}', f"remove {obj} and hydro",
                      f"show sticks, {obj}", f"color {color}, {obj}", f"disable {obj}"]
    for index in range(2):
        lines += [f"enable cutoff_{index}_*", "python", "cmd.set_view(shared_view)", "python end",
                  "python", f'cmd.png({str((args.out / f"overlay_{index}_front.png").resolve())!r}, width=1400, height=1000, ray=1)', "python end",
                  "turn y, 90", "python", f'cmd.png({str((args.out / f"overlay_{index}_side.png").resolve())!r}, width=1400, height=1000, ray=1)', "python end",
                  f"disable cutoff_{index}_*"]
    lines += ["enable cutoff_0_*", "python", "cmd.set_view(shared_view)", "python end",
              "python", f'cmd.save({str((args.out / "comparison.pse").resolve())!r})', "python end", "quit"]
    pml = args.out / "comparison.pml"
    pml.write_text("\n".join(lines) + "\n")
    subprocess.run([str(args.pymol), "-cq", str(pml.resolve())], check=True, capture_output=True)
    canvas = Image.new("RGB", (1600, 1600), "white")
    draw = ImageDraw.Draw(canvas)
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    title = ImageFont.truetype(font_path, 32)
    body = ImageFont.truetype(font_path, 24)
    draw.text((30, 15), "Indinavir: actual top-three cluster representatives", fill="black", font=title)
    draw.text((30, 58), "Same receptor frame and camera; gray = crystal. No fitting or redocking.", fill="black", font=body)
    for col, data in enumerate(datasets):
        x = col * 800
        draw.text((x+30, 112), f"{data['cutoff_A']:g} Å cutoff · {data['cluster_count']} clusters / {data['pose_count']} poses", fill="black", font=title)
        for row, angle in enumerate(("front", "side")):
            image = Image.open(args.out / f"overlay_{col}_{angle}.png").convert("RGB")
            image.thumbnail((780, 555))
            canvas.paste(image, (x + (800-image.width)//2, 170 + row*575))
        for n, (rep, color) in enumerate(zip(data["representatives"], ("#d90000", "#007bcc", "#a97600"))):
            draw.text((x+30, 1320+n*36), f"Rank {rep['rank']}: pose {rep['pose_id']} · {rep['energy_kcal_mol']:.3f} kcal/mol · {rep['crystal_rmsd_A']:.3f} Å to crystal", fill=color, font=body)
        draw.text((x+30, 1442), "Between representatives (no-fit heavy atoms):", fill="black", font=body)
        for n, pair in enumerate(data["pairwise"]):
            draw.text((x+30, 1478+n*30), f"{pair['ranks'][0]}–{pair['ranks'][1]}: {pair['rmsd_A']:.3f} Å", fill="black", font=body)
    canvas.save(args.out / "comparison.png")
    (args.out / "comparison.json").write_text(json.dumps({"method": "symmetry-aware heavy-atom CalcRMS; no fitting", "datasets": datasets}, indent=2)+"\n")
    print(json.dumps(datasets, indent=2))


if __name__ == "__main__":
    main()
