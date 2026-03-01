"""
Tüm resource sınıflarının tabanı.

BaseResource      — HTTP yardımcı metodları (get/post/put/delete)
PaginatedResource — abstract _list_page() + otomatik list_all() iterator
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Iterator, Optional

if TYPE_CHECKING:
    from sangfor_scp.client import SCPClient


class BaseResource:
    """
    Her resource sınıfının atası.

    Doğrudan kullanılmaz; alt sınıflar HTTP metodlarını
    bu sınıf üzerinden çağırır.
    """

    def __init__(self, client: "SCPClient"):
        self._client = client

    # ------------------------------------------------------------------ #
    # HTTP yardımcıları                                                   #
    # ------------------------------------------------------------------ #

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return self._client.request("GET", path, params=params)

    def _post(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        idempotent: bool = True,
    ) -> Any:
        return self._client.request("POST", path, json=body, idempotent=idempotent)

    def _put(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        idempotent: bool = True,
    ) -> Any:
        return self._client.request("PUT", path, json=body, idempotent=idempotent)

    def _delete(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return self._client.request("DELETE", path, params=params)


class PaginatedResource(BaseResource, ABC):
    """
    Sayfalı API endpoint'leri için abstract temel sınıf.

    Alt sınıflar _list_page() metodunu implement eder.
    list_all()  → tüm kayıtları tek tek yield eder (lazy)
    list_page() → ham sayfa yanıtını döndürür (manuel kontrol)

    Yanıt formatı (SCP standart pagination):
    {
        "total_size": int,
        "page_num":   int,
        "page_size":  int,
        "next_page_num": str,   # "" → son sayfa
        "data": list
    }
    """

    @abstractmethod
    def _list_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """
        Tek bir sayfa döndürür.

        Args:
            page_num:  İstenen sayfa numarası (0 tabanlı)
            page_size: Sayfa başına kayıt sayısı (max 100)
            **filters: API'ye özel filtre parametreleri

        Returns:
            SCP standart sayfalı yanıt dict'i
        """
        ...

    def list_all(
        self,
        page_size: int = 100,
        **filters: Any,
    ) -> Iterator[Dict[str, Any]]:
        """
        next_page_num == "" olana kadar tüm sayfaları dolaşır
        ve her kaydı tek tek yield eder.

        Kullanım:
            for server in client.servers.list_all(az_id="xxx"):
                print(server["id"])
        """
        page_num = 0
        while True:
            result = self._list_page(page_num, page_size, **filters)
            data = result.get("data", [])
            for item in data:
                yield item
            next_page = result.get("next_page_num", "")
            if next_page == "":
                break
            page_num = int(next_page)

    def list_page(
        self,
        page_num: int = 0,
        page_size: int = 100,
        **filters: Any,
    ) -> Dict[str, Any]:
        """
        Ham sayfa yanıtını döndürür.
        Manuel pagination kontrolü için kullanılır.

        Returns:
            {"total_size": N, "page_num": 0, "data": [...], ...}
        """
        return self._list_page(page_num, page_size, **filters)

    def count(self, **filters: Any) -> int:
        """
        Toplam kayıt sayısını döndürür.
        Sadece ilk sayfayı çeker (1 kayıt yeterli).
        """
        result = self._list_page(page_num=0, page_size=1, **filters)
        return result.get("total_size", 0)
