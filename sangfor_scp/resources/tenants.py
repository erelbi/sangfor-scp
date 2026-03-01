"""
Tenant (Proje) yönetimi.

SCP'de tenant → OpenStack terminolojisinde "project" olarak geçer.
Admin API üzerinden tenant listesi ve detayları sorgulanabilir.

Kapsanan endpoint'ler:
  - GET /janus/20180725/projects       → Tenant listesi (sayfalı)
  - GET /janus/20180725/projects/{id}  → Tek tenant detayı
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class TenantsResource(PaginatedResource):
    """
    Tenant (proje) sorguları.

    Kullanım:
        for tenant in client.tenants.list_all():
            print(tenant["id"], tenant["name"])

        detail = client.tenants.get("tenant-uuid")
    """

    _BASE = "/janus/20180725/projects"

    # ------------------------------------------------------------------ #
    # PaginatedResource — zorunlu implement                              #
    # ------------------------------------------------------------------ #

    def _list_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """
        Tenant listesi (sayfalı).

        Filtreler:
            keywords:  Tenant adında arama
            enabled:   1 (aktif) | 0 (pasif)
            az_id:     Resource pool ID'sine göre filtre
        """
        params = {
            "page_num": page_num,
            "page_size": page_size,
            **{k: v for k, v in filters.items() if v is not None},
        }
        return self._get(self._BASE, params=params)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Tüm tenant'ları liste olarak döndürür."""
        return list(self.list_all(**filters))

    def get(self, tenant_id: str) -> Dict[str, Any]:
        """
        Tek tenant detayını döndürür.

        Returns:
            {
                "id": str,
                "name": str,
                "user_name": str,
                "enabled": int,
                "azs": [...],   # İlişkili resource pool'lar
                "dhs": [...],
                "role_type": str
            }
        """
        return self._get(f"{self._BASE}/{tenant_id}")

    def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Ada göre tenant arar.
        Bulamazsa None döner, birden fazla bulursa ilkini döner.
        """
        for tenant in self.list_all(keywords=name):
            if tenant.get("name") == name:
                return tenant
        return None

    def list_by_resource_pool(self, az_id: str) -> Iterator[Dict[str, Any]]:
        """Belirli bir resource pool'a bağlı tenant'ları iterate eder."""
        return self.list_all(az_id=az_id)
