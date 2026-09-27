import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docking_universal import runtime_inventory


class RuntimeInventoryTests(unittest.TestCase):
    def test_missing_conda_is_unobserved_not_incompatible(self):
        inventory = runtime_inventory.collect_runtime_inventory(which=lambda _name: None)
        self.assertEqual(inventory["conda"]["status"], "absent")
        self.assertEqual(
            {item["status"] for item in inventory["environments"]},
            {"unobserved"},
        )
        self.assertNotIn("incompatible", json.dumps(inventory).lower())

    def test_conda_packages_and_environment_commands_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "docking-universal"
            bin_dir = prefix / ("Scripts" if os.name == "nt" else "bin")
            bin_dir.mkdir(parents=True)
            pymol = bin_dir / "pymol"
            pymol.write_text("#!/bin/sh\n")
            pymol.chmod(0o755)

            package_sets = {
                "docking-universal": {
                    "python": {"name": "python", "version": "3.9.23", "channel": "conda-forge"},
                    "pymol-open-source": {"name": "pymol-open-source", "version": "3.0.0", "channel": "conda-forge"},
                    "qt-main": {"name": "qt-main", "version": "5.15.8", "channel": "conda-forge"},
                },
                "docking-universal-vina": {
                    "python": {"name": "python", "version": "3.10.20"},
                    "vina": {"name": "vina", "version": "1.2.7"},
                },
                "docking-universal-qvinaw": {
                    "qvina": {"name": "qvina", "version": "2.1.0"},
                },
            }
            prefixes = {
                "docking-universal": str(prefix),
                "docking-universal-vina": str(Path(directory) / "docking-universal-vina"),
                "docking-universal-qvinaw": str(Path(directory) / "docking-universal-qvinaw"),
            }
            with patch.object(runtime_inventory, "_conda_environments", return_value=(prefixes, None)), patch.object(
                runtime_inventory,
                "_conda_packages",
                side_effect=lambda _conda, name: (package_sets[name], None),
            ):
                inventory = runtime_inventory.collect_runtime_inventory(which=lambda name: "/conda" if name == "conda" else None)

            environments = {item["name"]: item for item in inventory["environments"]}
            self.assertEqual(environments["docking-universal"]["python_version"], "3.9.23")
            self.assertEqual(environments["docking-universal-vina"]["packages"]["vina"], "1.2.7")
            packages = {item["id"]: item for item in inventory["packages"]}
            self.assertEqual(packages["pymol"]["version"], "3.0.0")
            self.assertEqual(packages["qt"]["version"], "5.15.8")
            commands = {item["id"]: item for item in inventory["commands"]}
            self.assertEqual(commands["pymol_command"]["status"], "available")
            self.assertEqual(commands["pymol_command"]["path"], str(pymol.resolve()))

    def test_human_output_explains_observation_limit(self):
        inventory = runtime_inventory.collect_runtime_inventory(which=lambda _name: None)
        rendered = runtime_inventory.render_runtime_inventory(inventory)
        self.assertIn("Conda environments", rendered)
        self.assertIn("No compatibility conclusion", rendered)

    def test_declared_dependencies_are_recorded_with_content_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements-pip-lock.txt"
            path.write_text("Example==1.2.3\n")
            declaration = runtime_inventory._declaration(path)
            self.assertEqual(declaration["dependencies"], {"example": "1.2.3"})
            self.assertEqual(len(declaration["sha256"]), 64)

    def test_poseedit_runtime_reports_components_without_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            node = Path(directory) / "node"
            chrome = Path(directory) / "chrome"
            node.write_text("node\n")
            chrome.write_text("chrome\n")
            with patch.object(runtime_inventory.subprocess, "run") as called:
                called.return_value.returncode = 0
                called.return_value.stdout = str(Path(directory) / "playwright/index.js")
                called.return_value.stderr = ""
                result = runtime_inventory.discover_poseedit_runtime(
                    which=lambda name: str(node) if name == "node" else None,
                    environment={"DOCKING_UNIVERSAL_CHROME": str(chrome)},
                )
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["components"]["node"]["path"], str(node.resolve()))
            self.assertEqual(result["components"]["chrome"]["path"], str(chrome.resolve()))
            called.assert_called_once()

    def test_poseedit_runtime_names_every_missing_component(self):
        with patch.object(runtime_inventory.platform, "system", return_value="TestOS"):
            result = runtime_inventory.discover_poseedit_runtime(
                which=lambda _name: None, environment={},
            )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["missing"], ["node", "playwright", "chrome"])


if __name__ == "__main__":
    unittest.main()
