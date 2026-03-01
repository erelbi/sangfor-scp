"""
Sistem bilgisi resource'ları.

Kapsanan endpoint'ler:
  - GET /janus/20180725/system/version   → SCP versiyon bilgisi
  - GET /janus/20180725/system/maintenance → Bakım modu durumu
  - GET /janus/20180725/platform          → Cluster ve versiyon detayı
  - GET /janus/20180725/hosts             → Fiziksel node listesi
  - GET /janus/20180725/hosts/{id}/interfaces → Node arayüzleri
  - GET /janus/20180725/licenses/summary  → Lisans özeti
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import BaseResource, PaginatedResource


class SystemResource(PaginatedResource):
    """
    Sistem düzeyinde bilgi sorgulama.

    Kullanım:
        info = client.system.version()
        hosts = list(client.system.list_all_hosts())
    """

    # ------------------------------------------------------------------ #
    # Versiyon & Durum                                                    #
    # ------------------------------------------------------------------ #

    def version(self) -> Dict[str, Any]:
        """
        SCP versiyon bilgisini döndürür.

        Returns:
            {
                "build_version": "SCP6.7.33 B-2022-06-07 19:45:13",
                "custom_version": [...]
            }
        """
        return self._get("/janus/20180725/system/version")

    def maintenance_mode(self) -> bool:
        """
        Platform bakım modunda mı?

        Returns:
            True → bakım modunda, False → normal
        """
        result = self._get("/janus/20180725/system/maintenance")
        return bool(result.get("maintain_mode", 0))

    def platform_info(self) -> Dict[str, Any]:
        """
        Cluster ve versiyon bilgisini döndürür.

        Returns:
            manage_mode, region_info, dcluster_info vb.
        """
        return self._get("/janus/20180725/platform")

    def license_summary(self) -> Dict[str, Any]:
        """
        Lisans özet bilgisini döndürür.

        Returns:
            username, status, key_id, products (liste) vb.
        """
        return self._get("/janus/20180725/licenses/summary")

    # ------------------------------------------------------------------ #
    # Fiziksel Node (Host) Yönetimi                                       #
    # ------------------------------------------------------------------ #

    def _list_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """
        Fiziksel node listesi (pagination destekler).

        Filtreler (keyword args):
            az_id:      Resource pool ID
            name:       Node adı (kısmi eşleşme)
            ip:         Node IP
            status:     running | offline
            type:       h (HCI) | vmware
        """
        params = {
            "page_num": page_num,
            "page_size": page_size,
            **filters,
        }
        return self._get("/janus/20190725/hosts", params=params)

    def list_all_hosts(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Tüm fiziksel node'ları iterate eder."""
        return self.list_all(**filters)

    def get_host(self, host_id: str) -> Dict[str, Any]:
        """Tek bir fiziksel node'un detayını döndürür."""
        return self._get(f"/janus/20190725/hosts/{host_id}")

    def list_host_interfaces(
        self,
        host_id: str,
        **filters: Any,
    ) -> List[Dict[str, Any]]:
        """
        Fiziksel node'un ağ arayüzlerini listeler.

        Filtreler:
            function: mgmt | vxlan | business | vs | tercom
            is_qos_config: 1 (trafik kontrolü yapılandırılmış)
        """
        params = {k: v for k, v in filters.items() if v is not None}
        result = self._get(
            f"/janus/20180725/hosts/{host_id}/interfaces",
            params=params or None,
        )
        # Bu endpoint liste döner (sarmalı olmadan)
        return result if isinstance(result, list) else result.get("data", [])

    # ------------------------------------------------------------------ #
    # Platform Overview (resource_pools.py'da da var ama burada kısayol) #
    # ------------------------------------------------------------------ #

    def overview(self, az_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Platform geneli kaynak özetini döndürür.

        Returns:
            virtual_resources, physical_resources, host, server, nfv, az
        """
        params = {"az_id": az_id} if az_id else None
        return self._get("/janus/20180725/overview", params=params)
