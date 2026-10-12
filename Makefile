# GSP Surround: system-wide install, packaging and release files.
#   make install [PREFIX=/usr/local] [DESTDIR=DIR]   install the app (what the .deb contains)
#   make uninstall [PREFIX=...] [DESTDIR=DIR]        remove it again
#   make deb                                         dist/gsp-surround_<version>_all.deb
#   make dist                                        dist/gsp-surround-<version>.tar.gz (source, from git HEAD)
#   make checksums                                   dist/SHA256SUMS (builds dist and deb first)
#   make artifacts                                   everything the release pipeline publishes
#   make check [STRICT=1]                            validate desktop entry, AppStream file, unit, scripts
#   make test                                        run the unit tests
#   make clean
# The version comes from the VERSION file. Nothing generated is meant to be committed (see .gitignore).
SHELL := /bin/bash

VERSION  := $(shell cat VERSION)
PREFIX  ?= /usr/local
DESTDIR ?=
APPDIR   = $(PREFIX)/share/gsp-surround
BINDIR   = $(PREFIX)/bin
DATADIR  = $(PREFIX)/share
# udev reads /usr/lib/udev/rules.d and /etc/udev/rules.d, but not /usr/local
UDEVDIR ?= $(if $(filter /usr,$(PREFIX)),$(PREFIX)/lib/udev/rules.d,/etc/udev/rules.d)
UNITDIR ?= $(PREFIX)/lib/systemd/user

# one date for everything, so builds are reproducible: the commit date (git), else the VERSION file's date
SOURCE_DATE_EPOCH ?= $(shell git log -1 --format=%ct 2>/dev/null || stat -c %Y VERSION)
export SOURCE_DATE_EPOCH
RELEASE_DATE := $(shell date -u -d @$(SOURCE_DATE_EPOCH) +%Y-%m-%d)

APP_FILES    := $(wildcard app/*.py)
SCRIPT_FILES := $(wildcard scripts/*.sh scripts/*.py)
DATA_FILES   := data/devices.conf data/filter-chain.conf.in data/gsp-surround.service.in \
                data/gsp-surround.desktop data/io.github.sudashiii.GspSurround.metainfo.xml.in
ICON_FILES   := $(shell find data/icons -type f)

# where things are built (overridable, so tests can build elsewhere)
BUILDDIR ?= build
DISTDIR  ?= dist
DEB            := $(DISTDIR)/gsp-surround_$(VERSION)_all.deb
TARBALL        := $(DISTDIR)/gsp-surround-$(VERSION).tar.gz
DEB_MAINTAINER ?= $(shell git log -1 --format='%an <%ae>' 2>/dev/null || echo 'GSP Surround maintainers')

METAINFO = $(DATADIR)/metainfo/io.github.sudashiii.GspSurround.metainfo.xml

.PHONY: install uninstall deb dist checksums artifacts check test clean

install:
	install -d $(DESTDIR)$(APPDIR)
	cp --parents --preserve=mode,timestamps gsp-surround VERSION $(APP_FILES) $(SCRIPT_FILES) \
	    $(DATA_FILES) $(ICON_FILES) $(DESTDIR)$(APPDIR)/
	printf 'installed by make install; install.sh/uninstall.sh then only handle the per-user setup\n' \
	    > $(DESTDIR)$(APPDIR)/PACKAGED
	find $(DESTDIR)$(APPDIR) -type d -exec chmod 755 {} +
	find $(DESTDIR)$(APPDIR) -type f -perm /u+x -exec chmod 755 {} +
	find $(DESTDIR)$(APPDIR) -type f ! -perm /u+x -exec chmod 644 {} +
	install -D -m 644 README.md $(DESTDIR)$(DATADIR)/doc/gsp-surround/README.md
	install -D -m 644 LICENSE $(DESTDIR)$(DATADIR)/doc/gsp-surround/LICENSE
	install -d $(DESTDIR)$(BINDIR)
	ln -sf ../share/gsp-surround/gsp-surround $(DESTDIR)$(BINDIR)/gsp-surround
	install -d $(DESTDIR)$(DATADIR)/applications
	sed 's|@BIN@|gsp-surround|' data/gsp-surround.desktop > $(DESTDIR)$(DATADIR)/applications/gsp-surround.desktop
	chmod 644 $(DESTDIR)$(DATADIR)/applications/gsp-surround.desktop
	install -D -m 644 data/icons/hicolor/scalable/apps/gsp-surround.svg \
	    $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/gsp-surround.svg
	install -d $(DESTDIR)$(DATADIR)/metainfo
	sed -e 's|@VERSION@|$(VERSION)|' -e 's|@DATE@|$(RELEASE_DATE)|' \
	    data/io.github.sudashiii.GspSurround.metainfo.xml.in > $(DESTDIR)$(METAINFO)
	chmod 644 $(DESTDIR)$(METAINFO)
	install -d $(DESTDIR)$(UDEVDIR)
	bash -c '. scripts/common.sh; udev_rules $$(device_lines | awk "{print \$$1}")' \
	    > $(DESTDIR)$(UDEVDIR)/70-gsp-surround.rules
	chmod 644 $(DESTDIR)$(UDEVDIR)/70-gsp-surround.rules
	install -d $(DESTDIR)$(UNITDIR)/pipewire.service.wants
	sed 's|@APPLY@|$(APPDIR)/scripts/apply.sh|' data/gsp-surround.service.in > $(DESTDIR)$(UNITDIR)/gsp-surround.service
	chmod 644 $(DESTDIR)$(UNITDIR)/gsp-surround.service
	ln -sf ../gsp-surround.service $(DESTDIR)$(UNITDIR)/pipewire.service.wants/gsp-surround.service
	@if [ -z "$(DESTDIR)" ] && command -v udevadm >/dev/null 2>&1; then \
	    udevadm control --reload || true; udevadm trigger --subsystem-match=hidraw --action=change || true; fi

uninstall:
	rm -rf $(DESTDIR)$(APPDIR) $(DESTDIR)$(DATADIR)/doc/gsp-surround
	rm -f $(DESTDIR)$(BINDIR)/gsp-surround $(DESTDIR)$(DATADIR)/applications/gsp-surround.desktop \
	    $(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/gsp-surround.svg $(DESTDIR)$(METAINFO) \
	    $(DESTDIR)$(UDEVDIR)/70-gsp-surround.rules $(DESTDIR)$(UNITDIR)/gsp-surround.service \
	    $(DESTDIR)$(UNITDIR)/pipewire.service.wants/gsp-surround.service
	-rmdir $(DESTDIR)$(UNITDIR)/pipewire.service.wants 2>/dev/null
	@if [ -z "$(DESTDIR)" ] && command -v udevadm >/dev/null 2>&1; then udevadm control --reload || true; fi

deb:
	rm -rf $(BUILDDIR)/deb
	$(MAKE) --no-print-directory install DESTDIR=$(abspath $(BUILDDIR))/deb PREFIX=/usr
	install -d $(BUILDDIR)/deb/DEBIAN
	install -D -m 644 LICENSE $(BUILDDIR)/deb/usr/share/doc/gsp-surround/copyright
	sed -e 's|@VERSION@|$(VERSION)|' -e 's|@MAINTAINER@|$(DEB_MAINTAINER)|' \
	    -e "s|@SIZE@|$$(du -sk --exclude=DEBIAN $(BUILDDIR)/deb | cut -f1)|" \
	    packaging/deb/control.in > $(BUILDDIR)/deb/DEBIAN/control
	install -m 755 packaging/deb/postinst packaging/deb/postrm $(BUILDDIR)/deb/DEBIAN/
	mkdir -p $(DISTDIR)
	dpkg-deb --root-owner-group --build $(BUILDDIR)/deb $(DEB)

dist:
	mkdir -p $(DISTDIR)
	git archive --format=tar --prefix=gsp-surround-$(VERSION)/ HEAD | gzip -n -9 > $(TARBALL)

checksums: dist deb
	cd $(DISTDIR) && sha256sum gsp-surround_$(VERSION)_all.deb gsp-surround-$(VERSION).tar.gz > SHA256SUMS

artifacts: checksums

# a validator that is not installed is skipped (and reported), unless STRICT=1
check: PREFIX = /usr
check:
	rm -rf $(BUILDDIR)/check
	$(MAKE) --no-print-directory install DESTDIR=$(abspath $(BUILDDIR))/check PREFIX=/usr
	for f in gsp-surround scripts/*.sh packaging/deb/postinst packaging/deb/postrm; do bash -n $$f || exit 1; done
	python3 -c 'import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]' \
	    $(APP_FILES) scripts/fetch_ir.py $(wildcard packaging/*.py)
	@run() { tool=$$1; shift; \
	    if command -v $$tool >/dev/null 2>&1; then echo "$$tool $$*"; "$$tool" "$$@" || exit 1; \
	    else echo "skipped: $$tool is not installed"; [ -z "$(STRICT)" ] || exit 1; fi; }; \
	  run xmllint --noout $(ICON_FILES) $(BUILDDIR)/check$(METAINFO); \
	  run desktop-file-validate $(BUILDDIR)/check$(DATADIR)/applications/gsp-surround.desktop; \
	  run appstreamcli validate --no-net $(BUILDDIR)/check$(METAINFO); \
	  mkdir -p $(BUILDDIR)/check/unit && \
	  sed -e 's|@APPLY@|/bin/true|' -e '/^PartOf=/d' -e '/^After=/d' data/gsp-surround.service.in \
	      > $(BUILDDIR)/check/unit/gsp-surround.service; \
	  if command -v systemd-analyze >/dev/null 2>&1; then \
	    out=$$(systemd-analyze --user verify $(BUILDDIR)/check/unit/gsp-surround.service 2>&1); \
	    if [ -n "$$out" ]; then echo "$$out"; exit 1; fi; echo 'systemd-analyze: unit ok (it only warns, so any output fails)'; \
	  else echo 'skipped: systemd-analyze is not installed'; [ -z "$(STRICT)" ] || exit 1; fi

test:
	python3 -m unittest discover tests

clean:
	rm -rf $(BUILDDIR) $(DISTDIR)
