#!/usr/bin/env bash
# RPM ve DEB paketlerini container içinde derler; sisteme paket kurmaz.
#
#   packaging/build.sh            # rpm + deb
#   packaging/build.sh rpm        # sadece rpm (Fedora)
#   packaging/build.sh deb        # sadece deb (Debian)
#   packaging/build.sh test       # derlenmiş paketleri temiz container'larda kur ve dene
#
# Çıktı: dist/packages/
# Gerekenler: podman veya docker, python3 -m build (sdist için)
#
# Ortam değişkenleri:
#   FEDORA_IMAGE (varsayılan registry.fedoraproject.org/fedora:44)
#   DEBIAN_IMAGE (varsayılan docker.io/library/debian:trixie)
#   DEB_TEST_IMAGES (varsayılan "debian:trixie ubuntu:24.04")
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist/packages"
WORK="$ROOT/build/packaging"
FEDORA_IMAGE="${FEDORA_IMAGE:-registry.fedoraproject.org/fedora:44}"
DEBIAN_IMAGE="${DEBIAN_IMAGE:-docker.io/library/debian:trixie}"
DEB_TEST_IMAGES="${DEB_TEST_IMAGES:-docker.io/library/debian:trixie docker.io/library/ubuntu:24.04}"

ENGINE="$(command -v podman || command -v docker || true)"
[ -n "$ENGINE" ] || { echo "podman veya docker gerekli" >&2; exit 1; }

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
SPEC_VERSION="$(sed -n 's/^Version: *//p' "$ROOT/packaging/rpm/python-sangfor-scp.spec")"
DEB_VERSION="$(sed -n '1s/.*(\(.*\)-[^-]*).*/\1/p' "$ROOT/packaging/debian/changelog")"
if [ "$VERSION" != "$SPEC_VERSION" ] || [ "$VERSION" != "$DEB_VERSION" ]; then
    echo "Sürümler uyuşmuyor: pyproject=$VERSION spec=$SPEC_VERSION debian=$DEB_VERSION" >&2
    exit 1
fi
SDIST="sangfor_scp-$VERSION.tar.gz"

run() { "$ENGINE" run --rm -v "$WORK:/work:Z" -v "$OUT:/out:Z" "$@"; }

sdist() {
    rm -rf "$WORK"
    mkdir -p "$WORK" "$OUT"
    python3 -m build --sdist --outdir "$WORK" "$ROOT" >/dev/null
    cp -r "$ROOT/packaging/rpm" "$ROOT/packaging/debian" "$WORK/"
    echo "sdist: $SDIST"
}

build_rpm() {
    echo "== RPM ($FEDORA_IMAGE)"
    run "$FEDORA_IMAGE" bash -euo pipefail -c "
        dnf -y -q install rpm-build pyproject-rpm-macros python3-devel python3-pytest \
            python3-pip python3-setuptools python3-wheel python3-requests python3-urllib3 python3-pycryptodomex >/dev/null
        mkdir -p ~/rpmbuild/SOURCES ~/rpmbuild/SPECS
        cp /work/$SDIST ~/rpmbuild/SOURCES/
        cp /work/rpm/python-sangfor-scp.spec ~/rpmbuild/SPECS/
        rpmbuild -ba ~/rpmbuild/SPECS/python-sangfor-scp.spec 2>&1 | tail -25
        cp ~/rpmbuild/RPMS/noarch/*.rpm ~/rpmbuild/SRPMS/*.rpm /out/
    "
}

build_deb() {
    echo "== DEB ($DEBIAN_IMAGE)"
    run "$DEBIAN_IMAGE" bash -euo pipefail -c "
        export DEBIAN_FRONTEND=noninteractive
        apt-get -qq update
        apt-get -qq install -y --no-install-recommends build-essential debhelper dh-python \
            pybuild-plugin-pyproject python3-all python3-setuptools python3-wheel \
            python3-requests python3-urllib3 python3-pytest >/dev/null
        mkdir -p /build && cd /build
        cp /work/$SDIST python-sangfor-scp_$VERSION.orig.tar.gz
        tar xzf python-sangfor-scp_$VERSION.orig.tar.gz
        cd sangfor_scp-$VERSION
        cp -r /work/debian debian
        dpkg-buildpackage -us -uc -b 2>&1 | tail -25
        cp ../*.deb /out/
    "
}

test_packages() {
    echo "== RPM kurulum testi ($FEDORA_IMAGE)"
    "$ENGINE" run --rm -v "$OUT:/out:Z" -v "$ROOT/packaging:/pkg:ro,Z" "$FEDORA_IMAGE" bash -euo pipefail -c "
        dnf -y -q install /out/python3-sangfor-scp-$VERSION-*.noarch.rpm >/dev/null
        dnf -y -q install python3-pycryptodomex >/dev/null
        python3 /pkg/smoke_test.py
    "
    for image in $DEB_TEST_IMAGES; do
        echo "== DEB kurulum testi ($image)"
        "$ENGINE" run --rm -v "$OUT:/out:Z" -v "$ROOT/packaging:/pkg:ro,Z" "$image" bash -euo pipefail -c "
            export DEBIAN_FRONTEND=noninteractive
            apt-get -qq update
            apt-get -qq install -y /out/python3-sangfor-scp_${VERSION}-*_all.deb >/dev/null
            apt-get -qq install -y python3-pycryptodome >/dev/null
            python3 /pkg/smoke_test.py
        "
    done
}

case "${1:-all}" in
    rpm)  sdist; build_rpm ;;
    deb)  sdist; build_deb ;;
    all)  sdist; build_rpm; build_deb ;;
    test) test_packages ;;
    *)    echo "kullanım: $0 [all|rpm|deb|test]" >&2; exit 2 ;;
esac

echo "== Paketler ($OUT)"
ls -1 "$OUT"
