# Copr "make_srpm" yöntemi için: Copr bu dosyayı kendi Fedora chroot'unda
#   make -f .copr/Makefile srpm outdir=<dizin> spec=<spec yolu>
# olarak çalıştırır. Spec'teki sürüm PyPI'de varsa sdist oradan indirilir (Fedora
# incelemesi Source ile SRPM içindeki arşivin birebir aynı olmasını ister); yoksa
# (yayınlanmamış sürüm) depodaki koddan üretilir.
#
# Yerelde denemek için:  make -f .copr/Makefile srpm outdir=/tmp/srpm

TOP := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
spec ?= $(TOP)/packaging/rpm/python-sangfor-scp.spec
outdir ?= $(TOP)/dist/srpm
WORK := $(outdir)/.copr-sources

.PHONY: srpm
srpm:
	command -v rpmbuild >/dev/null && python3 -c "import build, setuptools" 2>/dev/null || \
		dnf -y -q install rpm-build python3-build python3-setuptools python3-wheel git
	rm -rf $(WORK) && mkdir -p $(WORK)
	url="$$(rpmspec -P $(spec) | sed -n 's/^Source0*: *//p' | head -1)"; \
	if curl -fsSL -o $(WORK)/$$(basename "$$url") "$$url"; then \
		echo "sdist PyPI'den: $$url"; \
	else \
		echo "PyPI'de yok, depodan üretiliyor"; rm -f $(WORK)/*; \
		cd $(TOP) && python3 -m build --sdist --no-isolation --outdir $(WORK) .; \
	fi
	rpmbuild -bs $(spec) \
		--define "_sourcedir $(WORK)" \
		--define "_srcrpmdir $(outdir)"
	rm -rf $(WORK)
