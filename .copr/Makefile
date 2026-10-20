# Copr "make_srpm" yöntemi için: Copr bu dosyayı kendi Fedora chroot'unda
#   make -f .copr/Makefile srpm outdir=<dizin> spec=<spec yolu>
# olarak çalıştırır. sdist'i depodaki koddan üretir (PyPI'ye yüklenmesini beklemez),
# böylece her push / etiket için SRPM hazırlanır.
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
	cd $(TOP) && python3 -m build --sdist --no-isolation --outdir $(WORK) .
	rpmbuild -bs $(spec) \
		--define "_sourcedir $(WORK)" \
		--define "_srcrpmdir $(outdir)"
	rm -rf $(WORK)
