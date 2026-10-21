#!/usr/bin/env bash
# PKGBUILD ve .SRCINFO'daki sha256sums değerini PyPI'deki sdist'ten günceller.
# Sürüm PyPI'ye yüklendikten SONRA çalıştırılır (bump-version.sh, dosya PyPI'de
# varsa bunu kendisi çağırır).
#
#   packaging/arch/update-checksum.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PKGBUILD="$DIR/PKGBUILD"
SRCINFO="$DIR/.SRCINFO"

VER="$(sed -n 's/^pkgver=//p' "$PKGBUILD")"
URL="https://files.pythonhosted.org/packages/source/s/sangfor_scp/sangfor_scp-$VER.tar.gz"

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
if ! curl -fsSL -o "$TMP" "$URL"; then
    echo "PyPI'de henüz yok: $URL" >&2
    exit 1
fi
SUM="$(sha256sum "$TMP" | cut -d' ' -f1)"

sed -i "s/^sha256sums=.*/sha256sums=('$SUM')/" "$PKGBUILD"
sed -i "s/^\tsha256sums = .*/\tsha256sums = $SUM/" "$SRCINFO"
echo "AUR sha256 ($VER): $SUM"
