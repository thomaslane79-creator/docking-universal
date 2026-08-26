# GitHub essentials for Docking Universal

A practical guide for scientific users who are new to GitHub.

## What this guide is for

This guide covers the parts of GitHub that matter when obtaining, updating, citing, troubleshooting, or contributing to Docking Universal. No prior GitHub experience is assumed. Using Docking Universal does not require contributing code.

The routine path is simple: obtain a known software version, run the installer, retain that version with the study record, and update deliberately rather than automatically during an active analysis.

<!-- pagebreak -->

## 1. GitHub and Git are not the same thing

- **GitHub** is the website where the Docking Universal repository, releases, issues, and proposed changes are published.
- **Git** is the program that downloads the repository and keeps its recorded file history.
- A **repository** is the project folder and its history.
- A **clone** is an updateable local copy of the repository.
- A **commit** identifies a recorded software state.
- A **branch** keeps proposed work separate from the main version.
- A **pull request** asks that a branch be reviewed and combined with the main project.

A GitHub account is not required to view, clone, or download this public repository. It is useful when reporting issues or proposing changes.

## 2. Obtain the software

For a one-time snapshot, open the repository, choose **Code**, then **Download ZIP**, and extract the archive.

For a copy that can be updated, clone it with Git:

```bash
git clone https://github.com/thomaslane79-creator/docking-universal.git
cd docking-universal
```

Keep this software folder separate from study inputs, protocols, outputs, and reports.

<!-- pagebreak -->

## 3. Install and confirm the command

From the cloned or extracted Docking Universal folder, run:

```bash
bash install.sh
docking-universal check-install
docking-universal --help
```

The installer creates both required Conda environments and installs a host-side `docking-universal` launcher. Normal use does not require manual Conda activation or separate environment creation.

If Conda is unavailable, the installer stops before changing anything and points to Miniforge. For a fuller workstation check, run:

```bash
docking-universal check-install --full
docking-universal validate integration
```

A passing software validation confirms that expected tools and workflow stages operate in that environment. It does not validate a new biological target or guarantee docking accuracy.

## 4. Keep software and research data distinct

The repository is replaceable software source. Receptor files, ligand libraries, `.duprotocol` bundles, results, reports, and analysis notes are research records and should be stored and backed up according to the relevant data-management plan.

<!-- pagebreak -->

## 5. Update deliberately

If the repository was cloned with Git and its files have not been edited:

```bash
cd /path/to/docking-universal
git pull
bash install.sh
```

Before updating during an active study, record the current Docking Universal and dependency versions, preserve the `.duprotocol` bundle and study directory, and avoid mixing results from different software versions without documenting the comparison.

If Git says local changes would be overwritten, stop rather than forcing the update. Git is protecting files that differ from the shared version.

## 6. Report a problem safely

Before opening a public GitHub issue:

- remove confidential, unpublished, patient-derived, or access-controlled data unless sharing is explicitly permitted;
- run `docking-universal check-install` and record any missing or failing tool;
- record the operating system, architecture, Docking Universal version, exact command, expected result, and observed result;
- include the smallest public or synthetic example that reproduces the problem;
- paste text errors as text when practical.

Assume anything posted in a GitHub issue can be read and copied by anyone.

<!-- pagebreak -->

## 7. Optional: suggest a change

You do not need to contribute code to use the software. If you want to correct documentation or propose an improvement, create a branch, make one focused change, inspect it, commit it, push the branch, and open a pull request.

```bash
git switch -c your-name/short-description
git status
git diff
git add path/to/file
git commit -m "Explain the change"
git push -u origin your-name/short-description
```

A pushed branch is a proposal. It does not alter the main project until a maintainer reviews and merges it.

## Quick reference

- One-time copy: **Code → Download ZIP**
- Updateable copy: `git clone REPOSITORY_ADDRESS`
- Install or update the command: `bash install.sh`
- Check dependencies: `docking-universal check-install --full`
- See commands: `docking-universal --help`
- Run the main guided workflow: `docking-universal run`
- Report a reproducible problem: open a GitHub issue without restricted data

Use the main README for command selection, the installation guide for platform details, and the guided-workflow manual for scientific workflow choices. This guide explains project access and version-control basics; it is not a docking protocol and does not replace target-specific validation.
