PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
PACKAGE_DIR ?= $(PREFIX)/libexec/docking-universal

.PHONY: test test-integration test-release install uninstall

test:
	./tests/test_cli.sh
	./tests/test_install.sh
	$${DOCKING_UNIVERSAL_PYTHON:-python} -m unittest tests/test_run_selection.py tests/test_guided_options.py tests/test_report_cavity.py

test-integration:
	./bin/docking-universal validate integration

test-release:
	./bin/docking-universal validate release

install:
	install -d "$(DESTDIR)$(BINDIR)"
	install -d "$(DESTDIR)$(PACKAGE_DIR)/bin"
	install -d "$(DESTDIR)$(PACKAGE_DIR)/libexec"
	install -d "$(DESTDIR)$(PACKAGE_DIR)/tests"
	install -d "$(DESTDIR)$(PACKAGE_DIR)/examples"
	install -m 0755 bin/docking-universal "$(DESTDIR)$(BINDIR)/docking-universal"
	install -m 0755 bin/docking-universal "$(DESTDIR)$(PACKAGE_DIR)/bin/docking-universal"
	install -m 0644 VERSION "$(DESTDIR)$(PACKAGE_DIR)/VERSION"
	install -m 0644 Makefile "$(DESTDIR)$(PACKAGE_DIR)/Makefile"
	install -m 0755 libexec/docking-universal-* "$(DESTDIR)$(PACKAGE_DIR)/libexec/"
	cp -R tests/. "$(DESTDIR)$(PACKAGE_DIR)/tests/"
	cp -R examples/. "$(DESTDIR)$(PACKAGE_DIR)/examples/"

uninstall:
	rm -f "$(DESTDIR)$(BINDIR)/docking-universal"
	rm -rf "$(DESTDIR)$(PACKAGE_DIR)"
