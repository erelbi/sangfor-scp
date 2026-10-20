#!/usr/bin/env bash
# Copr projesini oluşturur ve GitHub deposundan otomatik derlenen paketi ekler.
#
# Bir kez yapılacaklar:
#   1. https://accounts.fedoraproject.org  → Fedora hesabı
#   2. https://copr.fedorainfracloud.org/api/ → giriş yap, çıkan içeriği
#      ~/.config/copr dosyasına kaydet (chmod 600)
#   3. sudo dnf install copr-cli
#
# Sonra:
#   packaging/copr/setup.sh                 # proje + paket + ilk derleme
#   CHROOTS="fedora-44-x86_64" packaging/copr/setup.sh   # chroot listesini değiştir
#
# Kullanıcılar kurulumu şöyle yapar:
#   sudo dnf copr enable <copr-kullanıcısı>/sangfor-scp
#   sudo dnf install python3-sangfor-scp
set -euo pipefail

PROJECT="${PROJECT:-sangfor-scp}"
PACKAGE="python-sangfor-scp"
REPO_URL="${REPO_URL:-https://github.com/erelbi/sangfor-scp}"
SPEC="packaging/rpm/python-sangfor-scp.spec"

command -v copr-cli >/dev/null || { echo "copr-cli yok: sudo dnf install copr-cli" >&2; exit 1; }
[ -f "${COPR_CONFIG:-$HOME/.config/copr}" ] || { echo "~/.config/copr yok: https://copr.fedorainfracloud.org/api/" >&2; exit 1; }

OWNER="$(copr-cli whoami)"

# Varsayılan: Copr'da açık olan tüm Fedora sürümleri + rawhide + EPEL 10 (Rocky/Alma/RHEL 10).
# EPEL 9 yok: EL9'daki setuptools (53) pyproject.toml [project] tablosunu okuyamıyor.
if [ -z "${CHROOTS:-}" ]; then
    CHROOTS="$(copr-cli list-chroots | awk '{print $1}' \
        | grep -E '^(fedora-[0-9]+|fedora-rawhide|epel-10)-x86_64$' | sort -V | tr '\n' ' ')"
fi
[ -n "$CHROOTS" ] || { echo "chroot bulunamadı" >&2; exit 1; }
CHROOT_ARGS=()
for c in $CHROOTS; do CHROOT_ARGS+=(--chroot "$c"); done
echo "Sahip: $OWNER  Proje: $PROJECT  Chroot'lar: $CHROOTS"

if copr-cli get-package "$OWNER/$PROJECT" --name "$PACKAGE" >/dev/null 2>&1; then
    echo "Paket zaten var, ayarları güncelleniyor"
    ACTION=edit-package-scm
else
    if ! copr-cli list-packages "$OWNER/$PROJECT" >/dev/null 2>&1; then
        copr-cli create "$PROJECT" "${CHROOT_ARGS[@]}" \
            --description "Python client and scp-health CLI for the Sangfor Cloud Platform (SCP) Open-API" \
            --instructions "sudo dnf copr enable $OWNER/$PROJECT && sudo dnf install python3-sangfor-scp"
    fi
    ACTION=add-package-scm
fi

# make_srpm: .copr/Makefile depodaki koddan sdist + SRPM üretir.
# --webhook-rebuild on: GitHub webhook'u gelince (push / etiket) yeniden derler.
copr-cli "$ACTION" "$OWNER/$PROJECT" \
    --name "$PACKAGE" \
    --clone-url "$REPO_URL.git" \
    --spec "$SPEC" \
    --method make_srpm \
    --webhook-rebuild on

copr-cli build-package "$OWNER/$PROJECT" --name "$PACKAGE"

cat <<MSG

Bitti. Her push'ta otomatik derleme için GitHub webhook'u ekle:
  1. https://copr.fedorainfracloud.org/coprs/$OWNER/$PROJECT/integrations/
     sayfasındaki GitHub webhook adresini kopyala
  2. $REPO_URL/settings/hooks → Add webhook
     Payload URL: (kopyalanan adres), Content type: application/json,
     olaylar: "Just the push event" (etiketler de push olayıdır)
MSG
