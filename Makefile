PREFIX ?= /usr/local
BINDIR ?= $(PREFIX)/bin
LIBEXECDIR ?= $(PREFIX)/libexec/docking-universal

.PHONY: test install uninstall

test:
	./tests/test_cli.sh
	$${DOCKING_UNIVERSAL_PYTHON:-python} -m unittest tests/test_run_selection.py tests/test_report_cavity.py

install:
	install -d "$(DESTDIR)$(BINDIR)"
	install -d "$(DESTDIR)$(LIBEXECDIR)"
	install -m 0755 bin/docking-universal "$(DESTDIR)$(BINDIR)/docking-universal"
	install -m 0755 libexec/docking-universal-* "$(DESTDIR)$(LIBEXECDIR)/"

uninstall:
	rm -f "$(DESTDIR)$(BINDIR)/docking-universal"
	rm -rf "$(DESTDIR)$(LIBEXECDIR)"
