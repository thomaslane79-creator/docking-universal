# Test data and reference outputs

`tests/` separates small automated checks from representative scientific data.

```text
tests/
├── inputs/             public, representative structures used for manual smoke tests
├── expected_outputs/   small checked outputs used by automated parser tests
├── expected_runs/      curated, human-reviewable output from completed workflows
├── output/             local generated test output; ignored by Git
└── test_cli.sh         fast command-line regression checks
```

`expected_runs/` is a reference for file layout, visualization, and report
review. It is not a benchmark, a claim of prospective accuracy, or an input to
the docking workflow. Fresh commands should write to a new folder outside this
directory.
