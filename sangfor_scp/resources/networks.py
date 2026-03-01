"""
Ağ yönetimi — VPC ve Subnet.

SCP'de VM'ler VPC (Virtual Private Cloud) ağlarına bağlanır.
Her VPC içinde bir veya daha fazla Subnet bulunabilir.

Kapsanan endpoint'ler:
  VPC:
    GET    /janus/20180725/vpcs           → VPC listesi (sayfalı)
    POST   /janus/20180725/vpcs           → VPC oluştur
    GET    /janus/20180725/vpcs/{id}      → VPC detayı
    DELETE /janus/20180725/vpcs/{id}      → VPC sil
    PUT    /janus/20180725/vpcs/{id}      → VPC güncelle

  Subnet:
    GET    /janus/20180725/subnets        → Subnet listesi (sayfalı)
    POST   /janus/20180725/subnets        → Subnet oluştur
    GET    /janus/20180725/subnets/{id}   → Subnet detayı
    DELETE /janus/20180725/subnets/{id}   → Subnet sil
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sangfor_scp.base import PaginatedResource


class NetworksResource(PaginatedResource):
    """
    VPC ve Subnet yönetimi.

    Kullanım:
        # VPC listesi
        for vpc in client.networks.list_vpcs(az_id="xxx"):
            print(vpc["id"], vpc["name"])

        # Subnet oluştur
        result = client.networks.create_subnet(
            vpc_id="...",
            az_id="...",
            cidr="192.168.10.0/24",
            name="subnet-01",
        )
    """

    _VPC_BASE    = "/janus/20180725/vpcs"
    _SUBNET_BASE = "/janus/20180725/subnets"

    # ------------------------------------------------------------------ #
    # PaginatedResource — VPC için varsayılan _list_page                  #
    # ------------------------------------------------------------------ #

    def _list_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """VPC listesi için varsayılan implementasyon."""
        return self._list_vpcs_page(page_num, page_size, **filters)

    # ------------------------------------------------------------------ #
    # VPC                                                                 #
    # ------------------------------------------------------------------ #

    def _list_vpcs_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """VPC listesi (tek sayfa)."""
        params = {
            "page_num": page_num,
            "page_size": page_size,
            **{k: v for k, v in filters.items() if v is not None},
        }
        return self._get(self._VPC_BASE, params=params)

    def list_vpcs(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """
        Tüm VPC'leri iterate eder.

        Filtreler:
            az_id:  Resource pool ID
            name:   Kısmi ad araması
            status: active | ...
            shared: 0 (private) | 1 (shared)
        """
        page_num = 0
        page_size = 100
        while True:
            result = self._list_vpcs_page(page_num, page_size, **filters)
            data = result.get("data", [])
            for item in data:
                yield item
            if result.get("next_page_num", "") == "":
                break
            page_num = int(result["next_page_num"])

    def get_vpc(self, vpc_id: str) -> Dict[str, Any]:
        """
        Tek VPC detayını döndürür.

        Returns:
            id, name, status, az_id, type, shared, description vb.
        """
        return self._get(f"{self._VPC_BASE}/{vpc_id}")

    def create_vpc(
        self,
        az_id: str,
        name: str,
        description: str = "",
        shared: int = 0,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Yeni VPC oluşturur.

        Args:
            az_id:       Resource pool ID
            name:        VPC adı
            description: Açıklama
            shared:      0 (private) | 1 (shared)

        Returns:
            {"id": str, ...}  veya  {"task_id": str}
        """
        body: Dict[str, Any] = {
            "az_id": az_id,
            "name": name,
            "description": description,
            "shared": shared,
            **extra,
        }
        return self._post(self._VPC_BASE, body=body, idempotent=True)

    def delete_vpc(self, vpc_id: str) -> Optional[str]:
        """VPC'yi siler. task_id döner."""
        result = self._delete(f"{self._VPC_BASE}/{vpc_id}")
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def update_vpc(
        self,
        vpc_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """VPC adını / açıklamasını günceller."""
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        body.update(extra)
        return self._put(f"{self._VPC_BASE}/{vpc_id}", body=body)

    def find_vpc_by_name(self, name: str, **filters: Any) -> Optional[Dict[str, Any]]:
        """Ada göre VPC arar (tam eşleşme). Bulamazsa None döner."""
        for vpc in self.list_vpcs(**filters):
            if vpc.get("name") == name:
                return vpc
        return None

    # ------------------------------------------------------------------ #
    # Subnet                                                              #
    # ------------------------------------------------------------------ #

    def _list_subnets_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """Subnet listesi (tek sayfa)."""
        params = {
            "page_num": page_num,
            "page_size": page_size,
            **{k: v for k, v in filters.items() if v is not None},
        }
        return self._get(self._SUBNET_BASE, params=params)

    def list_subnets(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        """
        Tüm subnet'leri iterate eder.

        Filtreler:
            az_id:  Resource pool ID
            vpc_id: VPC ID
            name:   Kısmi ad araması
            status: active | ...
        """
        page_num = 0
        page_size = 100
        while True:
            result = self._list_subnets_page(page_num, page_size, **filters)
            data = result.get("data", [])
            for item in data:
                yield item
            if result.get("next_page_num", "") == "":
                break
            page_num = int(result["next_page_num"])

    def get_subnet(self, subnet_id: str) -> Dict[str, Any]:
        """
        Tek subnet detayını döndürür.

        Returns:
            id, name, status, vpc_id, az_id,
            cidr, gateway_ip, allocation_pools,
            shared, description vb.
        """
        return self._get(f"{self._SUBNET_BASE}/{subnet_id}")

    def create_subnet(
        self,
        vpc_id: str,
        az_id: str,
        cidr: str,
        name: str,
        gateway_ip: Optional[str] = None,
        description: str = "",
        dns_nameservers: Optional[List[str]] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Yeni subnet oluşturur.

        Args:
            vpc_id:           Bağlı VPC ID
            az_id:            Resource pool ID
            cidr:             IP aralığı (örn. "192.168.1.0/24")
            name:             Subnet adı
            gateway_ip:       Gateway IP (None → otomatik)
            description:      Açıklama
            dns_nameservers:  DNS sunucu listesi

        Returns:
            {"id": str, ...}  veya  {"task_id": str}
        """
        body: Dict[str, Any] = {
            "vpc_id": vpc_id,
            "az_id": az_id,
            "cidr": cidr,
            "name": name,
            "description": description,
            **extra,
        }
        if gateway_ip is not None:
            body["gateway_ip"] = gateway_ip
        if dns_nameservers is not None:
            body["dns_nameservers"] = dns_nameservers

        return self._post(self._SUBNET_BASE, body=body, idempotent=True)

    def delete_subnet(self, subnet_id: str) -> Optional[str]:
        """Subnet'i siler. task_id döner."""
        result = self._delete(f"{self._SUBNET_BASE}/{subnet_id}")
        if result and isinstance(result, dict):
            return result.get("task_id")
        return None

    def find_subnet_by_name(self, name: str, **filters: Any) -> Optional[Dict[str, Any]]:
        """Ada göre subnet arar (tam eşleşme). Bulamazsa None döner."""
        for subnet in self.list_subnets(**filters):
            if subnet.get("name") == name:
                return subnet
        return None
