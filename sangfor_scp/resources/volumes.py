"""
Disk (Volume) yönetimi.

SCP'de diskler VM'lerden bağımsız oluşturulabilir (detached volume)
ve sonradan VM'e eklenebilir. VM oluşturulurken inline disk tanımı
da yapılabilir (servers.py'daki disks parametresi).

Kapsanan endpoint'ler:
  - GET    /janus/20180725/volumes           → Disk listesi (sayfalı)
  - POST   /janus/20180725/volumes           → Disk oluştur
  - GET    /janus/20180725/volumes/{id}      → Disk detayı
  - DELETE /janus/20180725/volumes/{id}      → Disk sil
  - PUT    /janus/20180725/volumes/{id}      → Disk güncelle (genişlet)
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class VolumesResource(PaginatedResource):
    """
    Disk yönetimi.

    Kullanım:
        # Disk oluştur
        result = client.volumes.create(
            az_id="...",
            storage_tag_id="...",
            size_mb=51200,
            name="data-disk-01",
        )
        client.tasks.wait(result["task_id"])
        volume_id = result["volume_id"]

        # VM'e bağla (servers.py üzerinden de yapılabilir)
        task_id = client.servers.attach_volume(server_id, volume_id)
        client.tasks.wait(task_id)
    """

    _BASE = "/janus/20180725/volumes"

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
        Disk listesi (sayfalı).

        Filtreler:
            az_id:      Resource pool ID
            server_id:  Bağlı olduğu VM ID
            status:     available | in-use | error | ...
            name:       Kısmi ad araması
            type:       new_disk | derive_disk
        """
        params = {
            "page_num": page_num,
            "page_size": page_size,
            **{k: v for k, v in filters.items() if v is not None},
        }
        return self._get(self._BASE, params=params)

    # ------------------------------------------------------------------ #
    # CRUD                                                                #
    # ------------------------------------------------------------------ #

    def get(self, volume_id: str) -> Dict[str, Any]:
        """
        Tek disk detayını döndürür.

        Returns:
            id, name, status, size_mb, az_id,
            storage_tag_id, server_id (bağlı VM), type vb.
        """
        return self._get(f"{self._BASE}/{volume_id}")

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Tüm diskleri liste olarak döndürür."""
        return list(self.list_all(**filters))

    def create(
        self,
        az_id: str,
        storage_tag_id: str,
        size_mb: int,
        name: str,
        description: str = "",
        preallocate: int = 0,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Bağımsız disk oluşturur. Asenkron işlem, task_id döner.

        Args:
            az_id:          Resource pool ID
            storage_tag_id: Storage tag ID
            size_mb:        Disk boyutu (MB)
            name:           Disk adı
            description:    Açıklama
            preallocate:    0 (thin) | 1 (thick)

        Returns:
            {"volume_id": str, "task_id": str}
        """
        body: Dict[str, Any] = {
            "az_id": az_id,
            "storage_tag_id": storage_tag_id,
            "size_mb": size_mb,
            "name": name,
            "description": description,
            "preallocate": preallocate,
            **extra,
        }
        return self._post(self._BASE, body=body, idempotent=True)

    def delete(self, volume_id: str) -> Optional[str]:
        """
        Diski siler. Asenkron işlem, task_id döner.
        Disk önce VM'den ayrılmış olmalıdır.
        """
        result = self._delete(f"{self._BASE}/{volume_id}")
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def resize(self, volume_id: str, new_size_mb: int) -> Optional[str]:
        """
        Disk kapasitesini genişletir. Asenkron işlem.
        Küçültme desteklenmez.

        Args:
            volume_id:    Disk ID
            new_size_mb:  Yeni boyut (MB, mevcut boyuttan büyük olmalı)

        Returns:
            task_id
        """
        body = {"size_mb": new_size_mb}
        result = self._put(f"{self._BASE}/{volume_id}", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    # ------------------------------------------------------------------ #
    # Filtreli sorgular                                                   #
    # ------------------------------------------------------------------ #

    def list_available(self, **filters: Any) -> List[Dict[str, Any]]:
        """Henüz VM'e bağlanmamış diskleri liste olarak döndürür."""
        return list(self.list_all(status="available", **filters))

    def list_attached(self, server_id: str) -> List[Dict[str, Any]]:
        """
        Belirli bir VM'e bağlı diskleri döndürür.

        Volumes API server_id filtresi kabul etmediğinden
        VM detayındaki disks alanı kullanılır.
        """
        vm = self._client.servers.get(server_id)
        return vm.get("disks", [])
