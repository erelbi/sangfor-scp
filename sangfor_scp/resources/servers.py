"""
Sanal Makine (Server/VM) yönetimi.

Kapsanan endpoint'ler:
  - GET    /janus/20180725/servers                        → VM listesi (sayfalı)
  - POST   /janus/20180725/servers                        → VM oluştur
  - GET    /janus/20180725/servers/{id}                   → VM detayı
  - PUT    /janus/20180725/servers/{id}                   → VM güncelle / yeniden adlandır
  - DELETE /janus/20180725/servers/{id}                   → VM sil (eski yöntem)
  - POST   /janus/20180725/servers/action                 → Toplu işlem
  - POST   /janus/20180725/servers/{id}/start             → VM başlat
  - POST   /janus/20180725/servers/{id}/stop              → VM durdur
  - POST   /janus/20180725/servers/{id}/reboot            → VM yeniden başlat
  - POST   /janus/20180725/servers/{id}/suspend           → VM askıya al
  - POST   /janus/20180725/servers/{id}/restore           → VM geri yükle (çöp kutusundan)
  - POST   /janus/20180725/servers/{id}/clone             → VM klonla
  - POST   /janus/20180725/servers/{id}/migrate           → VM taşı
  - POST   /janus/20180725/servers/{id}/remote-consoles   → Konsol URL'i al
  - POST   /janus/20180725/servers/{id}/server-password   → Parola sıfırla
  - POST   /janus/20180725/servers/{id}/action            → Disk ekle/çıkar (eski yöntem)
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

        # VM yeniden adlandır
        client.servers.rename("vm-uuid", "yeni-isim")

        # Güç yönetimi
        client.servers.stop("vm-uuid")
        client.servers.start("vm-uuid")

        # Konsol URL'i al
        info = client.servers.get_console("vm-uuid")
        print(info["url"])
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

    def update(
        self,
        server_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        cores: Optional[int] = None,
        sockets: Optional[int] = None,
        memory_mb: Optional[int] = None,
        os_type: Optional[str] = None,
        group_id: Optional[str] = None,
        networks: Optional[Dict[str, Any]] = None,
        disks: Optional[Dict[str, Any]] = None,
        advance_param: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> Optional[str]:
        """
        VM özelliklerini günceller. Asenkron işlem, task_id döner.
        Sadece gönderilen alanlar güncellenir, diğerleri değişmez.

        Args:
            server_id:    VM ID
            name:         Yeni VM adı (yeniden adlandırma)
            description:  Açıklama
            cores:        Çekirdek sayısı
            sockets:      Soket sayısı
            memory_mb:    Bellek (MB)
            os_type:      İşletim sistemi tipi
            group_id:     Grup ID
            networks:     NIC değişiklikleri dict
            disks:        Disk değişiklikleri dict
            advance_param: Gelişmiş parametreler dict

        Returns:
            task_id (str) veya None
        """
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if cores is not None:
            body["cores"] = cores
        if sockets is not None:
            body["sockets"] = sockets
        if memory_mb is not None:
            body["memory_mb"] = memory_mb
        if os_type is not None:
            body["os_type"] = os_type
        if group_id is not None:
            body["group_id"] = group_id
        if networks is not None:
            body["networks"] = networks
        if disks is not None:
            body["disks"] = disks
        if advance_param is not None:
            body["advance_param"] = advance_param
        body.update(extra)

        result = self._put(f"{self._BASE}/{server_id}", body=body)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def rename(self, server_id: str, new_name: str) -> Optional[str]:
        """
        VM'i yeniden adlandırır. task_id döner.

        Args:
            server_id: VM ID
            new_name:  Yeni VM adı

        Returns:
            task_id (str) veya None
        """
        return self.update(server_id, name=new_name)

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
        """VM üzerinde bir action çalıştırır (eski /action endpoint), task_id döner."""
        body = {"action": action, **params}
        result = self._post(f"{self._BASE}/{server_id}/action", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def start(self, server_id: str) -> Optional[str]:
        """
        VM'i başlatır. task_id döner.

        Endpoint: POST /janus/20180725/servers/{id}/start
        """
        result = self._post(f"{self._BASE}/{server_id}/start", body={}, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def stop(self, server_id: str, force: bool = False) -> Optional[str]:
        """
        VM'i kapatır. task_id döner.

        Args:
            server_id: VM ID
            force:     True → güç kesme (data kaybı riski), False → graceful shutdown

        Endpoint: POST /janus/20180725/servers/{id}/stop
        """
        body = {"force": 1} if force else {}
        result = self._post(f"{self._BASE}/{server_id}/stop", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def reboot(self, server_id: str, force: bool = False) -> Optional[str]:
        """
        VM'i yeniden başlatır. task_id döner.

        Args:
            server_id: VM ID
            force:     True → zorla yeniden başlatma, False → internal restart

        Endpoint: POST /janus/20180725/servers/{id}/reboot
        """
        body = {"force": 1} if force else {}
        result = self._post(f"{self._BASE}/{server_id}/reboot", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def suspend(self, server_id: str) -> Optional[str]:
        """
        VM'i askıya alır. task_id döner.

        Endpoint: POST /janus/20180725/servers/{id}/suspend
        """
        result = self._post(f"{self._BASE}/{server_id}/suspend", body={}, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def resume(self, server_id: str) -> Optional[str]:
        """Askıya alınmış VM'i devam ettirir. (eski /action endpoint)"""
        return self._action(server_id, "resume")

    def power_on(self, server_id: str) -> Optional[str]:
        """VM'i başlatır. (start() ile eşdeğer, geriye dönük uyumluluk)"""
        return self.start(server_id)

    def power_off(self, server_id: str, force: bool = False) -> Optional[str]:
        """VM'i kapatır. (stop() ile eşdeğer, geriye dönük uyumluluk)"""
        return self.stop(server_id, force=force)

    # ------------------------------------------------------------------ #
    # Toplu İşlemler                                                      #
    # ------------------------------------------------------------------ #

    def batch_action(
        self,
        server_ids: List[str],
        action: str,
    ) -> None:
        """
        Birden fazla VM üzerinde toplu işlem yapar.

        Args:
            server_ids: VM ID listesi
            action:     İşlem adı. Geçerli değerler:
                        - "soft_del_servers_action"   → Çöp kutusuna taşı (soft delete)
                        - "start_servers_action"      → Toplu başlat
                        - "stop_servers_action"       → Toplu durdur
                        - "poweroff_servers_action"   → Toplu güç kes
                        - "reboot_servers_action"     → Toplu yeniden başlat
                        - "suspend_servers_action"    → Toplu askıya al

        Not: HTTP 204 döner, task_id yoktur.

        Endpoint: POST /janus/20180725/servers/action
        """
        body = {
            "server_ids": server_ids,
            "server_action": {action: ""},
        }
        self._post(f"{self._BASE}/action", body=body)

    def soft_delete(self, server_ids: List[str]) -> None:
        """
        VM(leri) çöp kutusuna taşır (soft delete).
        Geri almak için restore() kullanılır.

        Args:
            server_ids: VM ID listesi
        """
        self.batch_action(server_ids, "soft_del_servers_action")

    def restore(self, server_id: str) -> Optional[str]:
        """
        Çöp kutusundaki VM'i geri yükler. task_id döner.

        Args:
            server_id: VM ID

        Endpoint: POST /janus/20180725/servers/{id}/restore
        """
        result = self._post(f"{self._BASE}/{server_id}/restore", body={})
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

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
    # Klonlama & Taşıma                                                   #
    # ------------------------------------------------------------------ #

    def clone(
        self,
        server_id: str,
        name: str,
        az_id: Optional[str] = None,
        storage_tag_id: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        VM'i klonlar. Asenkron işlem, task_id ve yeni VM uuid'si döner.

        Args:
            server_id:      Klonlanacak VM ID
            name:           Yeni VM adı
            az_id:          Hedef resource pool (None → aynı pool)
            storage_tag_id: Hedef storage tag (None → aynı storage)

        Returns:
            {"task_id": "...", "uuid": "yeni-vm-uuid"}

        Endpoint: POST /janus/20180725/servers/{id}/clone
        """
        body: Dict[str, Any] = {"name": name}
        if az_id is not None:
            body["az_id"] = az_id
        if storage_tag_id is not None:
            body["storage_tag_id"] = storage_tag_id
        body.update(extra)
        return self._post(f"{self._BASE}/{server_id}/clone", body=body, idempotent=True)

    def migrate(
        self,
        server_id: str,
        host_id: Optional[str] = None,
        storage_tag_id: Optional[str] = None,
        **extra: Any,
    ) -> Optional[str]:
        """
        VM'i farklı host veya storage'a taşır. Asenkron işlem, task_id döner.

        Args:
            server_id:      VM ID
            host_id:        Hedef fiziksel host ID (None → otomatik seçim)
            storage_tag_id: Hedef storage tag (None → mevcut)

        Returns:
            task_id (str) veya None

        Endpoint: POST /janus/20180725/servers/{id}/migrate
        """
        body: Dict[str, Any] = {}
        if host_id is not None:
            body["host_id"] = host_id
        if storage_tag_id is not None:
            body["storage_tag_id"] = storage_tag_id
        body.update(extra)
        result = self._post(f"{self._BASE}/{server_id}/migrate", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    # ------------------------------------------------------------------ #
    # Konsol & Parola                                                     #
    # ------------------------------------------------------------------ #

    def get_console(
        self,
        server_id: str,
        protocol: str = "vnc",
        console_type: str = "novnc",
    ) -> Dict[str, Any]:
        """
        VM konsol URL'ini döndürür.

        Args:
            server_id:    VM ID
            protocol:     Protokol: "vnc" | "spice" | "rdp"
            console_type: Konsol tipi: "novnc" | "xvpvnc"

        Returns:
            {"url": "https://...", ...}

        Endpoint: POST /janus/20180725/servers/{id}/remote-consoles
        """
        body = {
            "remote_console": {
                "protocol": protocol,
                "type": console_type,
            }
        }
        return self._post(f"{self._BASE}/{server_id}/remote-consoles", body=body)

    def reset_password(self, server_id: str, encrypted_password: str) -> None:
        """
        VM parolasını sıfırlar.

        Args:
            server_id:          VM ID
            encrypted_password: RSA ile şifrelenmiş yeni parola

        Not: Parolanın SCP public key ile RSA şifrelenmiş olması gerekir.

        Endpoint: POST /janus/20180725/servers/{id}/server-password
        """
        body = {"password": encrypted_password}
        self._post(f"{self._BASE}/{server_id}/server-password", body=body)

    # ------------------------------------------------------------------ #
    # Bilgi sorguları                                                     #
    # ------------------------------------------------------------------ #

    def list_running(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Sadece çalışan VM'leri iterate eder."""
        return self.list_all(status="running", **filters)

    def list_by_az(self, az_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Belirli resource pool'daki VM'leri iterate eder."""
        return self.list_all(az_id=az_id, **filters)
