"""Create and open portable Docking Universal protocol bundles."""

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def create_bundle(protocol_path, control_root, output, control_compound=None):
    """Package an approved protocol and retained control evidence as one file."""
    protocol_path = Path(protocol_path).resolve()
    control_root = Path(control_root).resolve()
    output = Path(output).resolve()
    protocol = json.loads(protocol_path.read_text())
    if not protocol.get("unknown_docking_allowed"):
        raise ValueError("only an approved protocol can be bundled")

    with tempfile.TemporaryDirectory(prefix="docking-universal-bundle-") as temporary:
        root = Path(temporary)
        packaged_control = root / "control"
        assets = packaged_control / "assets"
        receptor = Path(protocol["locked_inputs"]["receptor"]).expanduser().resolve()
        box = Path(protocol["locked_inputs"]["box"]).expanduser().resolve()
        receptor_copy = _copy(receptor, assets / receptor.name)
        box_copy = _copy(box, assets / box.name)
        protocol["locked_inputs"].update({
            "receptor": f"assets/{receptor_copy.name}",
            "box": f"assets/{box_copy.name}",
        })

        evidence = packaged_control / "evidence"
        evidence_files = []
        patterns = (
            "report/control_*.png", "report/control_*.json", "report/control_*.csv",
            "**/selected_visuals/*.png", "**/selected_visuals/**/*.png",
            "**/experimental_interactions.png", "**/comparison_summary.json",
        )
        seen = set()
        for pattern in patterns:
            for source in sorted(control_root.glob(pattern)):
                if not source.is_file() or source.resolve() in seen:
                    continue
                seen.add(source.resolve())
                destination = _copy(source, evidence / source.name)
                evidence_files.append({
                    "path": str(destination.relative_to(packaged_control)),
                    "sha256": sha256(destination),
                })

        experimental = next(iter(sorted(control_root.glob("**/*_experimental.sdf"))), None)
        if experimental is None:
            experimental = next(iter(sorted(control_root.glob("**/crystal_ligand.sdf"))), None)
        if experimental:
            retained = _copy(experimental, packaged_control / "00_inputs" / experimental.name)
            evidence_files.append({
                "path": str(retained.relative_to(packaged_control)),
                "sha256": sha256(retained),
            })

        protocol["control_evidence"] = {
            "compound": control_compound or "not recorded",
            "artifacts": evidence_files,
        }
        bundled_protocol = packaged_control / "protocol.json"
        bundled_protocol.write_text(json.dumps(protocol, indent=2) + "\n")

        manifest_files = []
        for path in sorted(packaged_control.glob("**/*")):
            if path.is_file():
                manifest_files.append({
                    "path": str(path.relative_to(root)), "sha256": sha256(path),
                })
        (root / "bundle_manifest.json").write_text(json.dumps({
            "schema_name": "docking-universal-protocol-bundle",
            "schema_version": 1,
            "protocol": "control/protocol.json",
            "files": manifest_files,
        }, indent=2) + "\n")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.glob("**/*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root))
    return output


def extract_bundle(bundle_path):
    """Verify and extract a .duprotocol, returning its internal protocol path."""
    bundle_path = Path(bundle_path).expanduser().resolve()
    root = Path(tempfile.mkdtemp(prefix="docking-universal-protocol-")).resolve()
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            for member in archive.infolist():
                destination = (root / member.filename).resolve()
                if root not in destination.parents and destination != root:
                    raise ValueError("unsafe path in protocol bundle")
            archive.extractall(root)
        manifest = json.loads((root / "bundle_manifest.json").read_text())
        if manifest.get("schema_name") != "docking-universal-protocol-bundle" or manifest.get("schema_version") != 1:
            raise ValueError("unsupported Docking Universal protocol bundle")
        for record in manifest.get("files", []):
            path = root / record["path"]
            if not path.is_file() or sha256(path) != record["sha256"]:
                raise ValueError(f"protocol bundle file failed verification: {record['path']}")
        protocol = root / manifest["protocol"]
        if not protocol.is_file():
            raise ValueError("protocol bundle does not contain protocol.json")
        return protocol
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def resolve_locked_path(protocol_path, stored_path):
    path = Path(stored_path).expanduser()
    if not path.is_absolute():
        path = Path(protocol_path).resolve().parent / path
    return path.resolve()
