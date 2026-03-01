"""
Elastic IP (EIP) yönetimi.

EIP'ler VM'lere bağlanarak dışarıdan erişim sağlar.
Admin'in önce EIP havuzu (pool) yapılandırması gerekir.

Kapsanan endpoint'ler:
  - GET    /janus/20180725/eips             → EIP listesi (sayfalı)
  - POST   /janus/20180725/eips             → EIP tahsis et
  - GET    /janus/20180725/eips/{id}        → EIP detayı
  - DELETE /janus/20180725/eips/{id}        → EIP serbest bırak
  - POST   /janus/20180725/eips/{id}/action → Bağla / Çıkar
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class EIPsResource(PaginatedResource):
    """
    Elastic IP yönetimi.

    Kullanım:
        # EIP tahsis et
        eip = client.eips.allocate(az_id="...", bandwidth_mb=100)
        eip_id = eip["id"]

        # VM'e bağla
        client.eips.bind(eip_id, server_id="vm-uuid", port_id="port-uuid")

        # Çıkar
        client.eips.unbind(eip_id)

        # Serbest bırak
        client.eips.release(eip_id)
    """

    _BASE = "/janus/20180725/eips"

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
        EIP listesi (sayfalı).

        Filtreler:
            az_id:     Resource pool ID
            status:    active | inactive | binding | ...
            server_id: Bağlı VM ID
            ip:        EIP adresi
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

    def get(self, eip_id: str) -> Dict[str, Any]:
        """
        Tek EIP detayını döndürür.

        Returns:
            id, ip, status, az_id, bandwidth_mb,
            server_id (bağlı VM), port_id vb.
        """
        return self._get(f"{self._BASE}/{eip_id}")

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Tüm EIP'leri liste olarak döndürür."""
        return list(self.list_all(**filters))

    def allocate(
        self,
        az_id: str,
        bandwidth_mb: int = 100,
        name: str = "",
        description: str = "",
        ip: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Yeni EIP tahsis eder.

        Args:
            az_id:        Resource pool ID
            bandwidth_mb: Bant genişliği (Mbps)
            name:         EIP adı
            description:  Açıklama
            ip:           Belirli IP iste (None → havuzdan otomatik)

        Returns:
            {"id": str, "ip": str, ...}
        """
        body: Dict[str, Any] = {
            "az_id": az_id,
            "bandwidth_mb": bandwidth_mb,
            "name": name,
            "description": description,
            **extra,
        }
        if ip is not None:
            body["ip"] = ip
        return self._post(self._BASE, body=body, idempotent=True)

    def release(self, eip_id: str) -> None:
        """EIP'yi serbest bırakır (havuza iade eder)."""
        self._delete(f"{self._BASE}/{eip_id}")

    # ------------------------------------------------------------------ #
    # Bağlama / Çıkarma                                                   #
    # ------------------------------------------------------------------ #

    def bind(
        self,
        eip_id: str,
        server_id: str,
        port_id: Optional[str] = None,
        **extra: Any,
    ) -> Optional[str]:
        """
        EIP'yi VM'e bağlar. task_id döner.

        Args:
            eip_id:    EIP ID
            server_id: Hedef VM ID
            port_id:   VM NIC port ID (None → VM'in ilk NIC'i)

        Returns:
            task_id veya None
        """
        body: Dict[str, Any] = {
            "action": "bind",
            "server_id": server_id,
            **extra,
        }
        if port_id is not None:
            body["port_id"] = port_id

        result = self._post(f"{self._BASE}/{eip_id}/action", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def unbind(self, eip_id: str) -> Optional[str]:
        """
        EIP'yi VM'den çıkarır. task_id döner.
        EIP tahsis edilmiş kalır, tekrar bağlanabilir.
        """
        body = {"action": "unbind"}
        result = self._post(f"{self._BASE}/{eip_id}/action", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def update_bandwidth(self, eip_id: str, bandwidth_mb: int) -> Dict[str, Any]:
        """EIP bant genişliğini günceller."""
        body = {"bandwidth_mb": bandwidth_mb}
        return self._put(f"{self._BASE}/{eip_id}", body=body)

    # ------------------------------------------------------------------ #
    # Filtreli sorgular                                                   #
    # ------------------------------------------------------------------ #

    def list_unbound(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Herhangi bir VM'e bağlı olmayan EIP'leri iterate eder."""
        return self.list_all(status="inactive", **filters)

    def list_bound(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """VM'e bağlı olan EIP'leri iterate eder."""
        return self.list_all(status="active", **filters)
