"""
Token tabanlı kimlik doğrulama.

Akış:
  1. GET /janus/v2/public-key       → RSA public key modulus al
  2. Şifreyi RSA PKCS1_v1_5 ile şifrele
  3. POST /janus/authenticate        → token al (24 saat geçerli)
  4. Her istekte Authorization: Token <id> header'ı ekle
  5. Token süresi dolmadan önce otomatik yenile
"""
from __future__ import annotations

import datetime
import uuid
from typing import Optional

import requests

from sangfor_scp.exceptions import SCPAuthError


def fetch_public_key_modulus(host: str, verify_ssl: bool = False, timeout: int = 30) -> str:
    """GET /janus/v2/public-key → RSA modulus (hex). Kimlik doğrulama gerektirmez."""
    host = host.rstrip("/")
    resp = requests.get(f"{host}/janus/v2/public-key", verify=verify_ssl, timeout=timeout)
    if resp.status_code != 200:
        # Eski endpoint'i dene
        resp = requests.get(f"{host}/janus/public-key", verify=verify_ssl, timeout=timeout)
    if resp.status_code != 200:
        raise SCPAuthError(
            message=f"Failed to fetch public key: {resp.text}",
            status_code=resp.status_code,
        )

    data = resp.json()
    modulus = data.get("data", {}).get("public_key") or data.get("public_key", "")
    if not modulus:
        raise SCPAuthError(message="Public key modulus not found in response.")
    # Belgede \n ile bitebilir, temizle
    return modulus.strip().rstrip("\\n")


def encrypt_password(password: str, modulus: str) -> str:
    """
    SCP public key ile RSA PKCS1_v1_5 şifreleme (login ve VM parolası için).
    pycryptodome (Crypto) veya pycryptodomex (Cryptodome) gerektirir;
    Fedora/RHEL yalnızca pycryptodomex paketler.
    """
    from binascii import a2b_hex, b2a_hex

    try:
        from Crypto.PublicKey import RSA
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.Util.number import bytes_to_long
    except ImportError:
        try:
            from Cryptodome.PublicKey import RSA  # type: ignore[no-redef]
            from Cryptodome.Cipher import PKCS1_v1_5  # type: ignore[no-redef]
            from Cryptodome.Util.number import bytes_to_long  # type: ignore[no-redef]
        except ImportError as exc:
            raise ImportError(
                "Password encryption requires pycryptodome or pycryptodomex. "
                "Install it with: pip install pycryptodome "
                "(Fedora: dnf install python3-pycryptodomex, "
                "Debian/Ubuntu: apt install python3-pycryptodome)"
            ) from exc

    n = bytes_to_long(a2b_hex(modulus))
    public_key = RSA.construct((n, 0x10001)).publickey()
    encrypted = PKCS1_v1_5.new(public_key).encrypt(password.encode("utf-8"))
    return b2a_hex(encrypted).decode("utf-8")


class TokenAuth:
    """
    Token tabanlı SCP kimlik doğrulama yöneticisi.

    Şifre şifrelemesi için pycryptodome gereklidir:
        pip install pycryptodome
    """

    TOKEN_TTL_HOURS = 23   # 24 saatlik token, 1 saat erken yenile

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        verify_ssl: bool = False,
        timeout: int = 30,
    ):
        self.host = host.rstrip("/")
        self.username = username
        self._plaintext_password = password
        self.verify_ssl = verify_ssl
        self.timeout = timeout

        self._token_id: Optional[str] = None
        self._expires_at: Optional[datetime.datetime] = None

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def authenticate(self) -> str:
        """Login yap, token al ve sakla. Token id'sini döndürür."""
        modulus = self._fetch_public_key_modulus()
        encrypted_password = self._encrypt_password(self._plaintext_password, modulus)

        cookie_token = uuid.uuid4().hex
        headers = {
            "Content-Type": "application/json",
            "Cookie": f"aCMPAuthToken={cookie_token}",
        }
        body = {
            "auth": {
                "passwordCredentials": {
                    "username": self.username,
                    "password": encrypted_password,
                }
            }
        }

        resp = requests.post(
            f"{self.host}/janus/authenticate",
            json=body,
            headers=headers,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )

        if resp.status_code not in (200, 201):
            raise SCPAuthError(
                message=f"Token authentication failed: {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json()
        # Yanıt yapısı: data.access.token.id
        try:
            token_data = data["data"]["access"]["token"]
            self._token_id = token_data["id"]
            self._expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                hours=self.TOKEN_TTL_HOURS
            )
        except (KeyError, TypeError) as exc:
            raise SCPAuthError(
                message=f"Unexpected authenticate response structure: {data}",
            ) from exc

        return self._token_id

    def is_expired(self) -> bool:
        """Token süresi dolmuş mu?"""
        if self._token_id is None or self._expires_at is None:
            return True
        return datetime.datetime.now(datetime.timezone.utc) >= self._expires_at

    def refresh_if_needed(self) -> None:
        """Süre dolmuşsa yeniden login yap."""
        if self.is_expired():
            self.authenticate()

    @property
    def token_id(self) -> Optional[str]:
        return self._token_id

    def get_auth_header(self) -> dict:
        """Her istekte eklenecek Authorization header'ını döndürür."""
        self.refresh_if_needed()
        return {"Authorization": f"Token {self._token_id}"}

    # ------------------------------------------------------------------ #
    # Yardımcı metodlar                                                   #
    # ------------------------------------------------------------------ #

    def _fetch_public_key_modulus(self) -> str:
        """GET /janus/v2/public-key → modulus string"""
        return fetch_public_key_modulus(self.host, self.verify_ssl, self.timeout)

    @staticmethod
    def _encrypt_password(password: str, modulus: str) -> str:
        """RSA PKCS1_v1_5 ile şifreleme."""
        return encrypt_password(password, modulus)
