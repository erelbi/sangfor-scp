"""
Sanal Makine (Server/VM) yönetimi.

Kapsanan endpoint'ler:
  - GET    /janus/20180725/servers              → VM listesi (sayfalı)
  - POST   /janus/20180725/servers              → VM oluştur
  - GET    /janus/20180725/servers/{id}         → VM detayı
  - DELETE /janus/20180725/servers/{id}         → VM sil
  - POST   /janus/20180725/servers/{id}/action  → Güç işlemleri

Güç işlemi action değerleri:
  power_on, power_off, force_power_off, reboot, force_reboot
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class ServersResource(PaginatedResource):
    """
    VM yönetimi.

    Kullanım:
        # Tüm VM'leri iterate et
        for vm in client.servers.list_all(az_id="xxx"):
            print(vm["id"], vm["name"], vm["status"])

        # VM oluştur ve task'i bekle
        result = client.servers.create(
            az_id="...",
            image_id="...",
            storage_tag_id="...",
            cores=2,
            memory_mb=2048,
            name="my-vm",
            networks=[{"vif_id": "net0", "vpc_id": "...", "subnet_id": "..."}],
        )
        task = client.tasks.wait(result["task_id"])
        vm_id = result["uuids"][0]

        # Güç yönetimi
        client.servers.power_off("vm-uuid")
        client.servers.power_on("vm-uuid")
    """

    _BASE = "/janus/20180725/servers"

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
        VM listesi (sayfalı).

        Filtreler:
            az_id:      Resource pool ID
            name:       Kısmi ad araması
            status:     running | stopped | error | ...
            tenant_id:  Tenant ID (admin için)
            host_id:    Fiziksel node ID
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

    def get(self, server_id: str) -> Dict[str, Any]:
        """
        Tek VM detayını döndürür.

        Returns:
            id, name, status, az_id, host_id,
            cores, memory_mb, disks, networks,
            created_at vb.
        """
        return self._get(f"{self._BASE}/{server_id}")

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Tüm VM'leri liste olarak döndürür."""
        return list(self.list_all(**filters))

    def create(
        self,
        az_id: str,
        image_id: str,
        storage_tag_id: str,
        cores: int,
        memory_mb: int,
        name: str,
        networks: List[Dict[str, Any]],
        disks: Optional[List[Dict[str, Any]]] = None,
        count: int = 1,
        sockets: int = 1,
        description: str = "",
        power_on: bool = True,
        location: Optional[Dict[str, Any]] = None,
        advance_param: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Yeni VM(ler) oluşturur. Asenkron işlem, task_id döner.

        Args:
            az_id:          Resource pool ID
            image_id:       Kullanılacak imaj ID
            storage_tag_id: Storage tag ID
            cores:          Çekirdek sayısı
            memory_mb:      Bellek (MB)
            name:           VM adı
            networks:       NIC listesi. Her eleman:
                            {
                              "vif_id": "net0",
                              "vpc_id": "...",
                              "subnet_id": "...",
                              "connect": 1,
                              "model": "virtio"  # isteğe bağlı
                            }
            disks:          Disk listesi (None → imajdan otomatik)
                            aCloud imaj için:
                              [{"id": "ide0", "type": "derive_disk",
                                "size_mb": 81920, "preallocate": 0}]
                            ISO imaj için:
                              [{"id": "ide0", "type": "new_disk",
                                "size_mb": 51200}]
            count:          Aynı anda oluşturulacak VM sayısı
            sockets:        Soket sayısı
            description:    Açıklama
            power_on:       Oluşturma sonrası güç aç (0/1)
            location:       {"id": "cluster"} (varsayılan cluster)
            advance_param:  Gelişmiş parametreler dict

        Returns:
            {
                "uuids":   ["vm-uuid-1", ...],
                "task_id": "task-uuid"
            }
        """
        body: Dict[str, Any] = {
            "az_id": az_id,
            "image_id": image_id,
            "storage_tag_id": storage_tag_id,
            "cores": cores,
            "sockets": sockets,
            "memory_mb": memory_mb,
            "count": count,
            "name": name,
            "description": description,
            "networks": networks,
            "power_on": 1 if power_on else 0,
            "location": location or {"id": "cluster"},
        }

        if disks is not None:
            body["disks"] = disks

        if advance_param:
            body["advance_param"] = advance_param

        body.update(extra)

        return self._post(self._BASE, body=body, idempotent=True)

    def delete(
        self,
        server_id: str,
        delete_disks: bool = True,
    ) -> Optional[str]:
        """
        VM'i siler. Asenkron işlem, task_id döner.

        Args:
            server_id:    VM ID
            delete_disks: İlişkili diskleri de sil (varsayılan True)

        Returns:
            task_id (str) veya None
        """
        params = {"delete_disk": 1 if delete_disks else 0}
        result = self._delete(f"{self._BASE}/{server_id}", params=params)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def find_by_name(self, name: str, **filters: Any) -> Optional[Dict[str, Any]]:
        """Ada göre VM arar (tam eşleşme). Bulamazsa None döner."""
        for vm in self.list_all(**filters):
            if vm.get("name") == name:
                return vm
        return None

    # ------------------------------------------------------------------ #
    # Güç İşlemleri                                                       #
    # ------------------------------------------------------------------ #

    def _action(self, server_id: str, action: str, **params: Any) -> Optional[str]:
        """VM üzerinde bir action çalıştırır, task_id döner."""
        body = {"action": action, **params}
        result = self._post(f"{self._BASE}/{server_id}/action", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def power_on(self, server_id: str) -> Optional[str]:
        """VM'i başlatır. task_id döner."""
        return self._action(server_id, "power_on")

    def power_off(self, server_id: str, force: bool = False) -> Optional[str]:
        """
        VM'i kapatır.
        force=True → güç kesme (data kaybı riski var)
        """
        action = "force_power_off" if force else "power_off"
        return self._action(server_id, action)

    def reboot(self, server_id: str, force: bool = False) -> Optional[str]:
        """
        VM'i yeniden başlatır.
        force=True → zorla yeniden başlatma
        """
        action = "force_reboot" if force else "reboot"
        return self._action(server_id, action)

    def suspend(self, server_id: str) -> Optional[str]:
        """VM'i askıya alır."""
        return self._action(server_id, "suspend")

    def resume(self, server_id: str) -> Optional[str]:
        """Askıya alınmış VM'i devam ettirir."""
        return self._action(server_id, "resume")

    # ------------------------------------------------------------------ #
    # Disk İşlemleri                                                      #
    # ------------------------------------------------------------------ #

    def attach_volume(
        self,
        server_id: str,
        volume_id: str,
        device_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        VM'e disk ekler. task_id döner.

        Args:
            server_id: VM ID
            volume_id: Disk ID
            device_id: Cihaz adı (örn. "ide1"), None → otomatik
        """
        body: Dict[str, Any] = {
            "action": "attach_volume",
            "volume_id": volume_id,
        }
        if device_id:
            body["device_id"] = device_id
        result = self._post(f"{self._BASE}/{server_id}/action", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def detach_volume(
        self,
        server_id: str,
        volume_id: str,
    ) -> Optional[str]:
        """VM'den disk çıkarır. task_id döner."""
        body = {"action": "detach_volume", "volume_id": volume_id}
        result = self._post(f"{self._BASE}/{server_id}/action", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    # ------------------------------------------------------------------ #
    # Bilgi sorguları                                                     #
    # ------------------------------------------------------------------ #

    def list_running(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Sadece çalışan VM'leri iterate eder."""
        return self.list_all(status="running", **filters)

    def list_by_az(self, az_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Belirli resource pool'daki VM'leri iterate eder."""
        return self.list_all(az_id=az_id, **filters)
