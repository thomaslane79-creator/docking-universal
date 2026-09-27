import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NextEnvironmentContractTests(unittest.TestCase):
    def _environment_text(self, name: str) -> str:
        return (ROOT / "environments" / name).read_text(encoding="utf-8").lower()

    def _dependencies(self, name: str) -> set[str]:
        return {
            line.strip()[2:]
            for line in self._environment_text(name).splitlines()
            if line.strip().startswith("- ")
        }

    def test_gui_host_uses_python_312_and_pyqt6_without_pymol(self):
        dependencies = self._dependencies("gui-next.yml")
        self.assertIn("python=3.12", dependencies)
        self.assertIn("pyqt6", dependencies)
        self.assertFalse(any(item.startswith("pymol-open-source") for item in dependencies))
        self.assertNotIn("pyqt", dependencies)

    def test_pymol_companion_uses_python_312_and_pymol_31_without_pyqt6(self):
        dependencies = self._dependencies("pymol-next.yml")
        self.assertIn("python=3.12", dependencies)
        self.assertIn("pymol-open-source=3.1.0", dependencies)
        self.assertIn("plip=2.3.1", dependencies)
        self.assertNotIn("pyqt6", dependencies)

    def test_candidate_environments_are_conda_forge_only(self):
        for name in ("gui-next.yml", "pymol-next.yml"):
            with self.subTest(environment=name):
                self.assertIn("- conda-forge", self._environment_text(name))
                self.assertIn("- nodefaults", self._environment_text(name))

    def test_desktop_source_does_not_import_pyqt5(self):
        sources = list((ROOT / "libexec" / "docking_universal" / "gui").glob("*.py"))
        sources.append(ROOT / "libexec" / "docking-universal-desktop.py")
        for source in sources:
            with self.subTest(source=source.name):
                text = source.read_text(encoding="utf-8")
                self.assertNotIn("from PyQt5", text)
                self.assertNotIn("import PyQt5", text)


if __name__ == "__main__":
    unittest.main()
