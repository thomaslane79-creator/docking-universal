# GitHub release checklist

Docking Universal is a research-preview package. The repository is ready to
publish when the following items are checked:

1. Keep the package source, `environment.yml`, `environments/vina.yml`,
   `docs/`, `examples/`, `tests/`, `README.md`, `CHANGELOG.md`, `LICENSE`, and
   `CITATION.cff`.
2. Do not publish generated `study/` folders or local `runs/`; they are ignored
   so a fresh user starts from the documented inputs.
3. Run `bash install.sh`, then run `make test` on the target platform.
4. Run `docking-universal check-install --full`, `docking-universal validate
   integration`, and the release suite when publishing a scientific-workflow
   change. Record the platform and validation output.
5. Use the two tutorials as demonstrations: the 1HVR/XK2 retrospective control
   followed by the rilpivirine held-out screen, and the 2R8N/indinavir
   ligand-free exploratory workflow.
6. Describe the project as rigid-receptor structural docking preparation,
   replicated search, pose clustering, and visualization. Do not present
   scores as measured affinities or one control as broad validation.

The compact fixtures under `tests/inputs/` and parser expectations under
`tests/expected_outputs/` are intentionally small and reviewable. Full local
studies remain reproducible but are not required repository contents.
