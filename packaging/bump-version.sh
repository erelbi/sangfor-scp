#!/usr/bin/env bash
# Sürümü dört yerde birden günceller: pyproject.toml, sangfor_scp/__init__.py,
# RPM spec (Version + %changelog) ve debian/changelog.
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

echo "$OLD → $NEW"
grep -n "^version" "$ROOT/pyproject.toml"
grep -n "__version__" "$ROOT/sangfor_scp/__init__.py"
grep -n "^Version" "$SPEC"
head -1 "$DEBCL"
