#!/usr/bin/env bash
# Sürümü altı yerde birden günceller: pyproject.toml, sangfor_scp/__init__.py,
# RPM spec, debian/changelog, Arch PKGBUILD/.SRCINFO ve OBS spec/.changes/.dsc.
#
#   packaging/bump-version.sh 0.5.0 "Snapshot yönetimi eklendi"
#
# Sonra:
#   git commit -am "release: v0.5.0" && git tag -a v0.5.0 -m v0.5.0
#   git push origin main v0.5.0      → GitHub Actions paketleri derleyip Release'e ekler
set -euo pipefail

NEW="${1:-}"
MESSAGE="${2:-New upstream release}"
if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "kullanım: $0 X.Y.Z [\"değişiklik notu\"]" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="$ROOT/packaging/rpm/python-sangfor-scp.spec"
DEBCL="$ROOT/packaging/debian/changelog"
MAINTAINER="sangfor-scp maintainers <erelbi@users.noreply.github.com>"
RPM_PACKAGER="Ergün Elvan Bilsel <bilselergun@gmail.com>"   # Fedora paketçisi

OLD="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
if [ "$OLD" = "$NEW" ]; then
    echo "Sürüm zaten $NEW" >&2
    exit 1
fi

sed -i "s/^version = \"$OLD\"/version = \"$NEW\"/" "$ROOT/pyproject.toml"
sed -i "s/^__version__ = \"$OLD\"/__version__ = \"$NEW\"/" "$ROOT/sangfor_scp/__init__.py"

# RPM: Version, Release=1, changelog girişi en üste
RPM_DATE="$(LC_ALL=C date '+%a %b %d %Y')"
sed -i "s/^Version: .*/Version:        $NEW/; s/^Release: .*/Release:        1%{?dist}/" "$SPEC"
sed -i "/^%changelog/a * $RPM_DATE $RPM_PACKAGER - $NEW-1\n- $MESSAGE\n" "$SPEC"

# Debian: yeni changelog girişi en üste
DEB_DATE="$(LC_ALL=C date -R)"
{
    printf 'python-sangfor-scp (%s-1) unstable; urgency=medium\n\n' "$NEW"
    printf '  * %s\n\n' "$MESSAGE"
    printf ' -- %s  %s\n\n' "$MAINTAINER" "$DEB_DATE"
    cat "$DEBCL"
} > "$DEBCL.new"
mv "$DEBCL.new" "$DEBCL"

# Arch (AUR): pkgver, pkgrel=1 ve .SRCINFO. sha256 PyPI yüklemesinden sonra
# packaging/arch/update-checksum.sh ile yazılır.
ARCH="$ROOT/packaging/arch"
sed -i "s/^pkgver=.*/pkgver=$NEW/; s/^pkgrel=.*/pkgrel=1/" "$ARCH/PKGBUILD"
sed -i -e "s/^\tpkgver = .*/\tpkgver = $NEW/" -e "s/^\tpkgrel = .*/\tpkgrel = 1/" \
       -e "s/sangfor_scp-$OLD\.tar\.gz/sangfor_scp-$NEW.tar.gz/" "$ARCH/.SRCINFO"
if ! "$ARCH/update-checksum.sh" 2>/dev/null; then
    echo "Not: PyPI yüklemesinden sonra packaging/arch/update-checksum.sh çalıştır (AUR sha256)"
fi

# openSUSE (OBS): Version ve .changes girişi en üste
OBS="$ROOT/packaging/obs"
sed -i "s/^Version: .*/Version:        $NEW/" "$OBS/python-sangfor-scp.spec"
{
    printf -- '-------------------------------------------------------------------\n'
    printf '%s - %s\n\n' "$(LC_ALL=C date -u '+%a %b %e %H:%M:%S UTC %Y')" "$RPM_PACKAGER"
    printf -- '- Update to version %s:\n  * %s\n\n' "$NEW" "$MESSAGE"
    cat "$OBS/python-sangfor-scp.changes"
} > "$OBS/python-sangfor-scp.changes.new"
mv "$OBS/python-sangfor-scp.changes.new" "$OBS/python-sangfor-scp.changes"
# OBS Debian/Ubuntu: .dsc sürümü ve tarball adı (debian.tar.gz yüklemede
# packaging/debian'dan üretilir)
sed -i -e "s/^Version: .*/Version: $NEW-1/" \
       -e "s/sangfor_scp-$OLD\.tar\.gz/sangfor_scp-$NEW.tar.gz/" "$OBS/python-sangfor-scp.dsc"

echo "$OLD → $NEW"
grep -n "^version" "$ROOT/pyproject.toml"
grep -n "__version__" "$ROOT/sangfor_scp/__init__.py"
grep -n "^Version" "$SPEC"
head -1 "$DEBCL"
