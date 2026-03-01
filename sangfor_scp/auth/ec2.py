"""
EC2 (AWS4-HMAC-SHA256) kimlik doğrulama.

SCP, AWS Signature Version 4 uyumlu imzalama kullanır.
Her istek için Authorization ve X-Amz-Date header'ları üretilir.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
from urllib.parse import urlparse

from requests.auth import AuthBase


class EC2Signer(AuthBase):
    """
    requests.auth.AuthBase alt sınıfı.
    Session'a bağlandığında her isteği otomatik imzalar.

    Kullanım:
        session.auth = EC2Signer(ak, sk, region, service)
    """

    ALGORITHM = "AWS4-HMAC-SHA256"

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        region: str = "cn-south-1",
        service: str = "open-api",
    ):
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.service = service

    # ------------------------------------------------------------------ #
    # requests hook                                                        #
    # ------------------------------------------------------------------ #

    def __call__(self, r):
        ec2_headers = self._build_headers(r)
        r.headers.update(ec2_headers)
        return r

    # ------------------------------------------------------------------ #
    # İmza üretimi                                                        #
    # ------------------------------------------------------------------ #

    def _build_headers(self, r) -> dict:
        now = datetime.datetime.utcnow()
        amzdate = now.strftime("%Y%m%dT%H%M%SZ")
        datestamp = now.strftime("%Y%m%d")

        parsed = urlparse(r.url)
        host = parsed.hostname
        path = parsed.path or "/"

        body = r.body or b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        body_hash = hashlib.sha256(body).hexdigest()

        # Canonical headers — sadece cookie;x-amz-date imzalanır
        canonical_headers = f"x-amz-date:{amzdate}\n"
        signed_headers = "x-amz-date"

        canonical_request = "\n".join([
            r.method.upper(),
            path,
            "",                     # canonical query string (boş bırakıldı)
            canonical_headers,
            signed_headers,
            body_hash,
        ])

        credential_scope = "/".join([
            datestamp, self.region, self.service, "aws4_request"
        ])

        string_to_sign = "\n".join([
            self.ALGORITHM,
            amzdate,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])

        signing_key = self._get_signing_key(datestamp)
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        authorization = (
            f"{self.ALGORITHM} "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )

        return {
            "Authorization": authorization,
            "X-Amz-Date": amzdate,
        }

    def _get_signing_key(self, datestamp: str) -> bytes:
        k_date = self._sign(("AWS4" + self.secret_key).encode("utf-8"), datestamp)
        k_region = self._sign(k_date, self.region)
        k_service = self._sign(k_region, self.service)
        k_signing = self._sign(k_service, "aws4_request")
        return k_signing

    @staticmethod
    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
