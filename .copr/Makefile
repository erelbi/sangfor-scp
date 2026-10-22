# Copr "make_srpm" yöntemi için: Copr bu dosyayı kendi Fedora chroot'unda
#   make -f .copr/Makefile srpm outdir=<dizin> spec=<spec yolu>
# olarak çalıştırır. Spec'teki sürüm PyPI'de varsa sdist oradan indirilir (Fedora
# incelemesi Source ile SRPM içindeki arşivin birebir aynı olmasını ister); yoksa
# (yayınlanmamış sürüm) depodaki koddan üretilir. Commit vX.Y.Z etiketindeyse PyPI
# yüklemesi (release.yml) için en fazla 20 dk beklenir.
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
	ver="$$(rpmspec -q --qf '%{version}\n' --srpm $(spec) | head -1)"; \
	if git -C $(TOP) tag --points-at HEAD 2>/dev/null | grep -qx "v$$ver"; then \
		for i in $$(seq 1 40); do \
			curl -fsI -o /dev/null "$$url" && break; \
			echo "v$$ver etiketli: PyPI yüklemesi bekleniyor ($$i/40)"; sleep 30; \
		done; \
	fi; \
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
