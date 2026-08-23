PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBEXECDIR ?= $(PREFIX)/libexec/docking-universal

.PHONY: test test-integration test-release setup install install-conda uninstall

test:
	./tests/test_install.sh
	./tests/test_bootstrap_install.sh
	./tests/test_cli.sh
	$${DOCKING_UNIVERSAL_PYTHON:-python} -m unittest tests/test_run_selection.py tests/test_guided_options.py tests/test_report_cavity.py tests/test_pdbfixer_preclean.py tests/test_ccd_audit.py

test-integration:
	./bin/docking-universal validate integration

test-release:
	./bin/docking-universal validate release

setup:
	./install.sh

install:
	install -d "$(DESTDIR)$(BINDIR)"
	install -d "$(DESTDIR)$(LIBEXECDIR)"
	install -d "$(DESTDIR)$(LIBEXECDIR)/validation-assets/test_inputs"
	install -d "$(DESTDIR)$(LIBEXECDIR)/validation-assets/tutorials/01_bound_ligand/inputs"
	install -d "$(DESTDIR)$(LIBEXECDIR)/validation-assets/tutorials/02_ligand_free_cavity/inputs"
	install -m 0755 bin/docking-universal "$(DESTDIR)$(BINDIR)/docking-universal"
	install -m 0755 libexec/docking-universal-* "$(DESTDIR)$(LIBEXECDIR)/"
	install -m 0644 libexec/docking_universal_bundle.py "$(DESTDIR)$(LIBEXECDIR)/"
	install -m 0644 VERSION "$(DESTDIR)$(LIBEXECDIR)/VERSION"
	install -m 0644 examples/test_inputs/two_compounds.sdf "$(DESTDIR)$(LIBEXECDIR)/validation-assets/test_inputs/"
	install -m 0644 examples/tutorials/01_bound_ligand/inputs/1HVR.pdb examples/tutorials/01_bound_ligand/inputs/rilpivirine_pubchem.sdf "$(DESTDIR)$(LIBEXECDIR)/validation-assets/tutorials/01_bound_ligand/inputs/"
	install -m 0644 examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb examples/tutorials/02_ligand_free_cavity/inputs/indinavir_pubchem_5362440.sdf "$(DESTDIR)$(LIBEXECDIR)/validation-assets/tutorials/02_ligand_free_cavity/inputs/"

install-conda:
	@test -n "$(CONDA_PREFIX)" || { echo "Error: activate a Conda environment first." >&2; exit 1; }
	$(MAKE) install PREFIX="$(CONDA_PREFIX)"

uninstall:
	rm -f "$(DESTDIR)$(BINDIR)/docking-universal"
	rm -rf "$(DESTDIR)$(LIBEXECDIR)"
