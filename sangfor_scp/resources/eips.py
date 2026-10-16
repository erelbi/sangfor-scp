"""
Elastic IP (EIP) yönetimi.

EIP'ler VM'lere bağlanarak dışarıdan erişim sağlar.
Admin'in önce EIP havuzu (floatingippool) yapılandırması gerekir.
SCP API'de EIP'ler "floatingip" olarak adlandırılır.

Kapsanan endpoint'ler:
  - GET    /janus/20180725/floatingips                     → EIP listesi
  - POST   /janus/20180725/floatingips                     → EIP tahsis et
  - GET    /janus/20180725/floatingips/{id}                → EIP detayı
  - PUT    /janus/20180725/floatingips/{id}                → Bant genişliği düzenle
  - DELETE /janus/20180725/floatingips/{id}                → EIP serbest bırak
  - POST   /janus/20180725/floatingips/{id}/binding        → Bağla
  - DELETE /janus/20180725/floatingips/{id}/unbinding      → Çıkar
  - GET    /janus/20180725/floatingippools                 → EIP havuzları

Not: Bant genişliği API'de kbps cinsindendir; bandwidth_mb parametreleri
otomatik olarak kbps'e çevrilir (1 Mbps = 1000 kbps).
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class EIPsResource(PaginatedResource):
    """
    Elastic IP yönetimi.

    Kullanım:
        # EIP tahsis et
        eip = client.eips.allocate(project_id="tenant-id", bandwidth_mb=100)
        eip_id = eip["id"]

        # VM NIC'ine bağla
        task_id = client.eips.bind(eip_id, vpc_id="vpc-uuid", port_id="port-uuid")
        client.tasks.wait(task_id)

        # Çıkar
        client.eips.unbind(eip_id)

        # Serbest bırak
        client.eips.release(eip_id)
    """

    _BASE = "/janus/20180725/floatingips"
    _POOL_BASE = "/janus/20180725/floatingippools"

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
            project_id:          Tenant ID
            router_id:           Router ID
            floating_ip_pool_id: EIP havuzu ID
            floating_ip:         EIP adresi
            bind_vpc_id:         Bağlı cihazın VPC ID'si
            bind_az_id:          Bağlı cihazın resource pool ID'si
            bind_type:           vm | router_primary | router_second
            keywords:            Arama metni
        """
        params = {
            "page_num": page_num,
            "page_size": page_size,
            **{k: v for k, v in filters.items() if v is not None},
        }
        result = self._get(self._BASE, params=params)
        # Doküman yanıtı düz liste olarak gösteriyor → sayfalı formata çevir
        if isinstance(result, list):
            return {"data": result, "total_size": len(result), "next_page_num": ""}
        return result

    # ------------------------------------------------------------------ #
    # CRUD                                                                #
    # ------------------------------------------------------------------ #

    def get(self, eip_id: str) -> Dict[str, Any]:
        """
        Tek EIP detayını döndürür.

        Returns:
            id, project_id, subnet_id, floating_ip, floatingip_pool_id,
            floating_port_id, sharedbandwidth_id, bandwidth,
            binding_info (sadece bağlıysa) vb.
        """
        return self._get(f"{self._BASE}/{eip_id}")

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Tüm EIP'leri liste olarak döndürür."""
        return list(self.list_all(**filters))

    def allocate(
        self,
        project_id: str,
        bandwidth_mb: Optional[int] = 100,
        floatingip_pool_id: Optional[str] = None,
        subnet_id: Optional[str] = None,
        floating_ip: Optional[str] = None,
        az_ids: Optional[List[str]] = None,
        line_type: Optional[str] = None,
        sharedbandwidth_id: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Yeni EIP tahsis eder.

        Args:
            project_id:         Tenant ID
            bandwidth_mb:       Bant genişliği (Mbps). sharedbandwidth_id
                                verilirse None geçilebilir.
            floatingip_pool_id: EIP havuzu ID (None → otomatik)
            subnet_id:          EIP havuzu subnet ID
            floating_ip:        Belirli IP iste (None → havuzdan otomatik)
            az_ids:             İlişkili resource pool ID'leri
            line_type:          Hat tipi ID
            sharedbandwidth_id: Paylaşımlı bant genişliği ID

        Returns:
            {"id": str, "floating_ip": str, "port_id": str, ...}
        """
        body: Dict[str, Any] = {"project_id": project_id, **extra}
        optional = {
            "floatingip_pool_id": floatingip_pool_id,
            "subnet_id": subnet_id,
            "floating_ip": floating_ip,
            "az_ids": az_ids,
            "line_type": line_type,
            "sharedbandwidth_id": sharedbandwidth_id,
        }
        body.update({k: v for k, v in optional.items() if v is not None})
        if bandwidth_mb is not None:
            kbps = bandwidth_mb * 1000
            body["bandwidth"] = {"qos_uplink": kbps, "qos_downlink": kbps}
        return self._post(self._BASE, body=body, idempotent=True)

    def release(self, eip_id: str) -> None:
        """EIP'yi siler (havuza iade eder)."""
        self._delete(f"{self._BASE}/{eip_id}")

    def update_bandwidth(self, eip_id: str, bandwidth_mb: int) -> Dict[str, Any]:
        """
        EIP bant genişliğini günceller (SCP 6.3.70+).
        Giden ve gelen bant genişliği aynı olmak zorundadır.
        """
        kbps = bandwidth_mb * 1000
        body = {"qos_uplink": kbps, "qos_downlink": kbps}
        return self._put(f"{self._BASE}/{eip_id}", body=body)

    # ------------------------------------------------------------------ #
    # Bağlama / Çıkarma                                                   #
    # ------------------------------------------------------------------ #

    def bind(
        self,
        eip_id: str,
        vpc_id: str,
        port_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        **extra: Any,
    ) -> Optional[str]:
        """
        EIP'yi VM, NFV cihazı veya sanal IP'ye bağlar. task_id döner.

        Args:
            eip_id:     EIP ID
            vpc_id:     Hedef cihazın VPC ID'si
            port_id:    Hedef NIC port ID
            ip_address: Hedef iç IP adresi

        Returns:
            task_id veya None
        """
        body: Dict[str, Any] = {"vpc_id": vpc_id, **extra}
        if port_id is not None:
            body["port_id"] = port_id
        if ip_address is not None:
            body["ip_address"] = ip_address

        result = self._post(f"{self._BASE}/{eip_id}/binding", body=body, idempotent=True)
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def unbind(self, eip_id: str) -> Optional[str]:
        """
        EIP'yi bağlı olduğu cihazdan çıkarır. task_id döner.
        EIP tahsis edilmiş kalır, tekrar bağlanabilir.
        """
        result = self._delete(f"{self._BASE}/{eip_id}/unbinding")
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    # ------------------------------------------------------------------ #
    # Filtreli sorgular                                                   #
    # ------------------------------------------------------------------ #

    def list_unbound(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Herhangi bir cihaza bağlı olmayan EIP'leri iterate eder."""
        return (e for e in self.list_all(**filters) if not e.get("binding_info"))

    def list_bound(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Bir cihaza bağlı olan EIP'leri iterate eder."""
        return (e for e in self.list_all(**filters) if e.get("binding_info"))

    # ------------------------------------------------------------------ #
    # EIP havuzları                                                       #
    # ------------------------------------------------------------------ #

    def list_pools(self, **filters: Any) -> List[Dict[str, Any]]:
        """
        EIP havuzlarını döndürür.

        Filtreler:
            floatingip_pool_id, name, line_type_id, query

        Returns:
            [{"id", "name", "ip_count", "allocation_pools", "az_ids", ...}]
        """
        params = {k: v for k, v in filters.items() if v is not None}
        result = self._get(self._POOL_BASE, params=params or None)
        if isinstance(result, list):
            return result
        return result.get("data", []) if result else []
