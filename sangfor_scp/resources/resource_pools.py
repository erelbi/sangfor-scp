"""
Resource Pool (Availability Zone — AZ) yönetimi.

Kapsanan endpoint'ler:
  - GET /janus/20180725/azs              → Resource pool listesi
  - GET /janus/20180725/azs/{az_id}      → Resource pool detayı
  - GET /janus/20180725/overview         → Platform geneli özet
  - GET /janus/20180725/storages/tags    → Storage tag listesi (tenant quota)
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class ResourcePoolsResource(PaginatedResource):
    """
    Resource Pool (AZ) sorguları.

    Kullanım:
        for pool in client.resource_pools.list_all():
            print(pool["id"], pool["name"])

        detail = client.resource_pools.get("az-uuid")
        tags = client.resource_pools.storage_tags("az-uuid")
    """

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
        Resource pool listesi (sayfalı).

        Filtreler:
            type: hci | vmware
            tag:  public (shared) | private (dedicated)
        """
        # Bu endpoint liste döner, standart pagination wrapper yok.
        # Uyum için manuel wrapper oluşturulur.
        params = {k: v for k, v in filters.items() if v is not None}
        result = self._get("/janus/20180725/azs", params=params or None)

        # Yanıt doğrudan list gelebilir
        if isinstance(result, list):
            return {
                "total_size": len(result),
                "page_num": 0,
                "page_size": len(result),
                "next_page_num": "",
                "data": result,
            }
        return result

    # ------------------------------------------------------------------ #
    # Resource Pool CRUD                                                  #
    # ------------------------------------------------------------------ #

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """
        Tüm resource pool'ları liste olarak döndürür.

        Filtreler:
            type: hci | vmware
            tag:  public | private
        """
        return list(self.list_all(**filters))

    def get(self, az_id: str) -> Dict[str, Any]:
        """
        Tek resource pool detayını döndürür.

        Returns:
            id, name, status, type, tag, version,
            virtual_resources, physical_resources, dhs
        """
        return self._get(f"/janus/20180725/azs/{az_id}")

    def overview(self, az_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Platform geneli kaynak özetini döndürür.

        Args:
            az_id: Belirli bir resource pool (None → tüm platform)

        Returns:
            {
                "virtual_resources":  [...],
                "physical_resources": [...],
                "host":   {"total": N, "online_count": N, ...},
                "server": {"total": N, "running_count": N, ...},
                "nfv":    {"total": N, ...},
                "az":     {"total": N, "online_count": N, ...}
            }
        """
        params = {"az_id": az_id} if az_id else None
        return self._get("/janus/20180725/overview", params=params)

    # ------------------------------------------------------------------ #
    # Storage Tags                                                        #
    # ------------------------------------------------------------------ #

    def storage_tags(self, az_id: str) -> List[Dict[str, Any]]:
        """
        Verilen resource pool'daki storage tag'lerini listeler.

        Tenant'lar sadece kotası olan storage tag'lerde VM oluşturabilir.

        Args:
            az_id: Resource pool ID

        Returns:
            [{"id": str, "name": str, "ratio": float, ...}, ...]
        """
        params = {"az_id": az_id}
        result = self._get("/janus/20180725/storages/tags", params=params)
        if isinstance(result, list):
            return result
        return result.get("data", [])
