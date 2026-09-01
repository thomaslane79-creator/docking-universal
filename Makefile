PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBEXECDIR ?= $(PREFIX)/libexec/docking-universal

.PHONY: test test-integration test-release setup install install-conda uninstall

test:
	./tests/test_install.sh
	./tests/test_bootstrap_install.sh
	./tests/test_cli.sh
	./tests/test_failure_semantics.sh
	./tests/test_receptor_input_validation.sh
	./tests/test_prepare_support.sh
	./tests/test_receptor_input_filter.sh
	./tests/test_receptor_failure_diagnosis.sh
	./tests/test_fpocket_selection.sh
	./tests/test_ligand_pocket_merge.sh
	./tests/test_fpocket_candidate_classification.sh
	./tests/test_fpocket_ranked_selection.sh
	./tests/test_docking_box_artifacts.sh
	./tests/test_adjacent_pocket_extension.sh
	./tests/test_pymol_review_scene.sh
	./tests/test_receptor_command_builders.sh
	./tests/test_receptor_structural_audits.sh
	./tests/test_receptor_attempt_runner.sh
	./tests/test_ligand_detection_helpers.sh
	./tests/test_fpocket_runner.sh
	./tests/test_receptor_preparation_routes.sh
	PYTHONPATH="$(CURDIR)/libexec$${PYTHONPATH:+:$$PYTHONPATH}" $${DOCKING_UNIVERSAL_PYTHON:-python} -m unittest tests/test_run_selection.py tests/test_guided_options.py tests/test_report_cavity.py tests/test_pdbfixer_preclean.py tests/test_ccd_audit.py tests/test_protocol_types.py tests/test_protocol_region.py tests/test_graphical_chooser.py tests/test_depict2d.py tests/test_retained_report_artifacts.py tests/test_process_runner.py tests/test_reuse_equivalence.py

test-integration:
	./bin/docking-universal validate integration

test-release:
	./bin/docking-universal validate release

setup:
	./install.sh

install:
	install -d "$(DESTDIR)$(BINDIR)"
	install -d "$(DESTDIR)$(LIBEXECDIR)"
	install -d "$(DESTDIR)$(LIBEXECDIR)/docking-universal-prepare.d"
	install -d "$(DESTDIR)$(LIBEXECDIR)/validation-assets/test_inputs"
	install -d "$(DESTDIR)$(LIBEXECDIR)/validation-assets/tutorials/01_bound_ligand/inputs"
	install -d "$(DESTDIR)$(LIBEXECDIR)/validation-assets/tutorials/02_ligand_free_cavity/inputs"
	install -m 0755 bin/docking-universal "$(DESTDIR)$(BINDIR)/docking-universal"
	install -m 0755 $(filter-out libexec/docking-universal-prepare.d,$(wildcard libexec/docking-universal-*)) "$(DESTDIR)$(LIBEXECDIR)/"
	install -m 0644 libexec/docking-universal-prepare.d/*.sh "$(DESTDIR)$(LIBEXECDIR)/docking-universal-prepare.d/"
	install -m 0644 libexec/docking_universal_bundle.py "$(DESTDIR)$(LIBEXECDIR)/"
	install -m 0644 libexec/docking_universal_pocket_review.py "$(DESTDIR)$(LIBEXECDIR)/"
	install -m 0644 libexec/docking_universal_process.py "$(DESTDIR)$(LIBEXECDIR)/"
	install -m 0644 libexec/docking_universal_region.py "$(DESTDIR)$(LIBEXECDIR)/"
	install -m 0644 libexec/docking_universal_reuse.py "$(DESTDIR)$(LIBEXECDIR)/"
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
