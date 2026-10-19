"""
Alarm (alert) sorgulama.

Kapsanan endpoint'ler:
  - GET /janus/20190725/alarms             → Anlık (açık / onaylanmış) alarmlar (sayfalı)
  - GET /janus/20190725/alarms/{id}        → Alarm detayı
  - GET /janus/20190725/alarm-histories    → Tüm alarmlar (çözülenler dahil, sayfalı)

Notlar:
  - Seviye: p1 = kritik, p2 = orta, p3 = düşük. Dokümanda iki tablo çelişiyor;
    gerçek ortamda %90 disk doluluk alarmı p1 geliyor.
  - Durum: open (bekliyor), ack (onaylandı), close (çözüldü — sadece geçmişte).
  - alarm-histories AK/SK kullanıcısında yetki gerektirebilir (0x120220010001).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sangfor_scp.base import PaginatedResource

LEVEL_NAMES = {"p1": "critical", "p2": "medium", "p3": "low"}

# "Disk partition details: E:\（99.23%）, /dev/vda2（100.00%）" → [("E:\\", 99.23), ...]
_PARTITION_RE = re.compile(r"([^\s,，]+?)\s*[（(]\s*([\d.]+)\s*%\s*[）)]")


class AlarmsResource(PaginatedResource):
    """
    Alarm sorgulama.

    Kullanım:
        # Tüm açık kritik alarmlar
        for a in client.alarms.list_all(level="p1"):
            print(a["object_name"], a["description"])

        # Bir host'un alarmları
        client.alarms.list(object_id="host-005056b20b3b")

        # Politika bazında sayım
        client.alarms.count_by("policy_name")
    """

    _BASE = "/janus/20190725/alarms"
    _HISTORY = "/janus/20190725/alarm-histories"

    def _list_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """
        Filtreler:
            level:       p1 | p2 | p3
            status:      open | ack
            object_type: vm | host | storage | ...
            object_id:   Nesne ID'si (ör. host-xxxx, VM UUID)
            policy_id:   Alarm politikası ID
            start_time / end_time: "YYYY-MM-DD HH:MM:SS"
            az_ids:      Resource pool ID listesi (virgülle birleştirilir)
        """
        return self._get(self._BASE, params=_params(page_num, page_size, filters))

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Tüm anlık alarmları liste olarak döndürür."""
        return list(self.list_all(**filters))

    def get(self, alarm_id: str) -> Dict[str, Any]:
        """Tek alarmın detayını döndürür."""
        return self._get(f"{self._BASE}/{alarm_id}")

    def history(self, page_size: int = 100, **filters: Any) -> Iterator[Dict[str, Any]]:
        """
        Çözülenler dahil tüm alarmları iterate eder.
        Filtreler list_all ile aynı (status hariç).

        Raises:
            SCPForbiddenError: Kullanıcının "View list of all alerts" yetkisi yoksa
        """
        page_num = 0
        while True:
            result = self._get(self._HISTORY, params=_params(page_num, page_size, filters))
            for item in result.get("data", []):
                yield item
            next_page = result.get("next_page_num", "")
            if next_page == "":
                break
            page_num = int(next_page)

    def count_by(self, field: str, **filters: Any) -> List[Tuple[Any, int]]:
        """
        Anlık alarmları bir alana göre sayar, çoktan aza sıralı döndürür.

        Örnek: client.alarms.count_by("policy_name")
               → [("High VM Logical Disk rate", 29), ("VMware VM Alert", 6), ...]
        """
        counts: Dict[Any, int] = {}
        for alarm in self.list_all(**filters):
            key = alarm.get(field)
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

    @staticmethod
    def parse_partitions(alarm: Dict[str, Any]) -> List[Tuple[str, float]]:
        """
        Disk doluluk alarmının açıklamasından bölüm ve doluluk oranlarını çıkarır.

        Returns:
            [("D:\\", 99.99), ("/dev/mapper/centos-home", 99.88), ...]
            Disk alarmı değilse boş liste.
        """
        text = alarm.get("description") or ""
        marker = text.find("Disk partition")
        if marker < 0:
            return []
        return [(p, float(v)) for p, v in _PARTITION_RE.findall(text[marker:])]


def _params(page_num: int, page_size: int, filters: Dict[str, Any]) -> Dict[str, Any]:
    params: Dict[str, Any] = {"page_num": page_num, "page_size": page_size}
    for key, value in filters.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        params[key] = value
    return params
