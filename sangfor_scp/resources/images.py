"""
Image (VM imaj) yönetimi.

SCP'de iki tip imaj vardır:
  - ISO   → Optik sürücüden mount edilir, işletim sistemi kurulum gerektirir
  - aCloud → Yerleşik imaj, sistem diski önceden yapılandırılmış

Kapsanan endpoint'ler:
  - GET /janus/20180725/images         → Image listesi (sayfalı)
  - GET /janus/20180725/images/{id}    → Tek image detayı
  - GET /janus/20180725/storages/tags  → Storage tag listesi (resource_pools.py'da da var)
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class ImagesResource(PaginatedResource):
    """
    VM imaj sorguları.

    Kullanım:
        # Tüm public aCloud imajları
        for img in client.images.list_all(disk_format="aCloud", image_type="public"):
            print(img["id"], img["name"])

        # Belirli imaj detayı
        detail = client.images.get("image-uuid")
    """

    _BASE = "/janus/20180725/images"

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
        Image listesi (sayfalı).

        Filtreler:
            disk_format:  ISO | aCloud
            image_type:   public | private
            az_id:        Resource pool ID
            name:         Kısmi ad araması
            os_type:      İşletim sistemi tipi
            status:       active | ...
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

    def get(self, image_id: str) -> Dict[str, Any]:
        """
        Tek image detayını döndürür.

        Returns:
            id, name, status, disk_format, image_type,
            os_type, size_mb, visibility, azs (resource pool listesi),
            disks (aCloud için sistem diski bilgisi) vb.
        """
        return self._get(f"{self._BASE}/{image_id}")

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Tüm imajları liste olarak döndürür."""
        return list(self.list_all(**filters))

    def list_iso(self, az_id: Optional[str] = None, **filters: Any) -> Iterator[Dict[str, Any]]:
        """ISO formatındaki imajları iterate eder."""
        return self.list_all(disk_format="ISO", az_id=az_id, **filters)

    def list_acloud(self, az_id: Optional[str] = None, **filters: Any) -> Iterator[Dict[str, Any]]:
        """aCloud (yerleşik) imajları iterate eder."""
        return self.list_all(disk_format="aCloud", az_id=az_id, **filters)

    def find_by_name(self, name: str, **filters: Any) -> Optional[Dict[str, Any]]:
        """
        Ada göre imaj arar (tam eşleşme).
        Bulamazsa None döner.
        """
        for img in self.list_all(**filters):
            if img.get("name") == name:
                return img
        return None
