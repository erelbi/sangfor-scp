"""
Sangfor SCP API kütüphanesi — hata hiyerarşisi.

HTTP durum kodları ve API hata kodları bu sınıflara dönüştürülür.
"""
from __future__ import annotations
from typing import Optional


class SCPError(Exception):
    """Tüm SCP hatalarının tabanı."""

    def __init__(
        self,
        message: str = "",
        status_code: Optional[int] = None,
        errcode: Optional[str] = None,
        response: Optional[dict] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errcode = errcode          # API'nin döndürdüğü hata kodu (0x...)
        self.response = response or {}

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"status_code={self.status_code}, "
            f"errcode={self.errcode!r})"
        )


class SCPAuthError(SCPError):
    """401 — Kimlik doğrulama başarısız veya token geçersiz."""


class SCPForbiddenError(SCPError):
    """403 — Yetki yetersiz."""


class SCPNotFoundError(SCPError):
    """404 — Kaynak bulunamadı."""


class SCPConflictError(SCPError):
    """409 — Kaynak zaten mevcut (idempotency ihlali)."""


class SCPRateLimitError(SCPError):
    """429 — Rate limit aşıldı. GET: 600/dk, diğerleri: 100/dk."""


class SCPBadRequestError(SCPError):
    """400 — Hatalı parametre veya kaynak bağımlılığı sorunu."""


class SCPServerError(SCPError):
    """500 — Sunucu taraflı iç hata."""


class SCPTaskError(SCPError):
    """Asenkron task başarısız sonuçlandı (status='failure')."""

    def __init__(self, message: str = "", task_id: str = "", task_data: Optional[dict] = None):
        super().__init__(message)
        self.task_id = task_id
        self.task_data = task_data or {}


class SCPTimeoutError(SCPError):
    """tasks.wait() çağrısında bekleme süresi aşıldı."""

    def __init__(self, message: str = "", task_id: str = "", timeout: int = 0):
        super().__init__(message)
        self.task_id = task_id
        self.timeout = timeout


_STATUS_TO_EXCEPTION = {
    400: SCPBadRequestError,
    401: SCPAuthError,
    403: SCPForbiddenError,
    404: SCPNotFoundError,
    409: SCPConflictError,
    429: SCPRateLimitError,
    500: SCPServerError,
}


def raise_for_status(status_code: int, body: dict) -> None:
    """HTTP durum koduna göre uygun exception fırlatır."""
    exc_cls = _STATUS_TO_EXCEPTION.get(status_code, SCPError)
    message = body.get("message", "")
    errcode = body.get("errcode") or str(body.get("code", ""))
    raise exc_cls(
        message=message,
        status_code=status_code,
        errcode=errcode,
        response=body,
    )
