# Local study runs

Use this ignored folder for studies created while developing or using the
package. It keeps large docking output out of the repository root and out of a
GitHub release by default.

```text
runs/
├── active/          current user studies
├── archived_local/  retained historical local runs
└── README.md
```

The repository's portable teaching material belongs in `examples/tutorials/`;
the small checked output fixtures and curated public reference run belong in
`tests/`. Do not treat files here as versioned expected results.
