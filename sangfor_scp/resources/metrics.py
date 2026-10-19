"""
İzleme verisi (zaman serisi metrikleri).

Kapsanan endpoint:
  - GET /janus/20180725/metrics/{object_id}

Desteklenen object_type ve metrikler (doküman tablo 4.22.2):
  host   : cpu.util, memory.util, io.read.iops, io.write.iops, io.read.speed,
           io.write.speed, net.in.bps, net.out.bps, net.in.pps, net.out.pps
  server : host ile aynı (disk.util YOK)
  az     : cpu.util, memory.util, disk.util
  eip, eip_pool, eip_flow, sbw, sbw_flow, scale_group, disaster, oss: dokümana bakın

Gerçek ortam notları (SCP 6.11.2):
  - VM için object_type "server" olmalı ("vm" → 400).
  - Değerler string döner ("14.86"); bu modül float'a çevirir.
  - timegap birimli olmalı: "1800s", "24h", "7d" geçerli; birimsiz "86400" → 404,
    "30m" → 400. Bu modül süreyi otomatik bu biçime çevirir.
  - granularity ise birimsiz saniye olmalı ("300"; "5m" → 400).
  - granularity verilmezse sunucu tek nokta döndürebilir; bu modül timegap'e
    göre izin verilen en küçük granularity'yi otomatik seçer.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Union

from sangfor_scp.base import BaseResource

HOST_METRICS = ("cpu.util", "memory.util")
SERVER_METRICS = ("cpu.util", "memory.util")
AZ_METRICS = ("cpu.util", "memory.util", "disk.util")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$", re.IGNORECASE)

Duration = Union[int, str]


def to_seconds(value: Duration) -> int:
    """'1h' → 3600, '7d' → 604800, 300 → 300."""
    if isinstance(value, int):
        return value
    match = _DURATION_RE.match(str(value))
    if not match:
        raise ValueError(f"Geçersiz süre: {value!r} (örnek: 300, '1h', '7d')")
    number, unit = match.groups()
    return int(number) * _UNIT_SECONDS[(unit or "s").lower()]


def format_timegap(seconds: int) -> str:
    """API'nin kabul ettiği biçim: 7d, 24h veya 1800s ("m" ve birimsiz değer reddediliyor)."""
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds}s"


def min_granularity(timegap_seconds: int) -> int:
    """Dokümandaki kural: ≤1 saat → 60 sn, ≤1 gün → 300, ≤30 gün → 1800, üstü → 43200."""
    if timegap_seconds <= 3600:
        return 60
    if timegap_seconds <= 86400:
        return 300
    if timegap_seconds <= 30 * 86400:
        return 1800
    return 43200


def summarize(series: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Tek metriğin datapoints listesinden özet çıkarır.

    Returns:
        {"min": .., "max": .., "avg": .., "last": .., "count": N}
        Veri yoksa değerler None, count 0.
    """
    values = [v for _, v in series.get("datapoints", []) if v is not None]
    if not values:
        return {"min": None, "max": None, "avg": None, "last": None, "count": 0}
    return {
        "min": min(values),
        "max": max(values),
        "avg": sum(values) / len(values),
        "last": values[-1],
        "count": len(values),
    }


class MetricsResource(BaseResource):
    """
    İzleme verisi sorgulama.

    Kullanım:
        # Host'un son 24 saatlik CPU/RAM kullanımı
        data = client.metrics.host("host-001b21d61e70", timegap="24h")
        print(data["cpu.util"]["datapoints"][-1])   # ("2026-10-19T20:40:00", 14.2)

        # Özet (min/max/ortalama/son)
        client.metrics.host_summary("host-001b21d61e70", timegap="7d")
        # → {"cpu.util": {"min": 9.1, "max": 61.0, "avg": 22.4, "last": 14.2, "count": 336}, ...}

        # VM
        client.metrics.server("vm-uuid", metric_names=["cpu.util", "net.in.bps"])
    """

    _BASE = "/janus/20180725/metrics"

    def query(
        self,
        object_id: str,
        object_type: str,
        metric_names: Union[str, Sequence[str]],
        timegap: Duration = "1h",
        granularity: Optional[Duration] = None,
        stop_time: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Ham sorgu.

        Args:
            object_id:    Nesne ID (host-xxxx, VM UUID, az UUID, ...)
            object_type:  host | server | az | eip | ...
            metric_names: "cpu.util,memory.util" veya ["cpu.util", "memory.util"]
            timegap:      Zaman aralığı — saniye (int) veya "1h", "24h", "7d"
            granularity:  Nokta aralığı; None → timegap'e göre en küçük geçerli değer
            stop_time:    Bitiş zamanı "YYYY-MM-DD HH:MM:SS" (None → şimdi)
            project_id:   Sadece nesne depolama (oss) için

        Returns:
            {"cpu.util": {"unit": "%", "granularity": 300,
                          "datapoints": [("2026-10-19T20:40:00", 14.2), ...]}, ...}
        """
        if not isinstance(metric_names, str):
            metric_names = ",".join(metric_names)
        gap = to_seconds(timegap)
        gran = to_seconds(granularity) if granularity is not None else min_granularity(gap)
        params = {
            "object_type": object_type,
            "metric_names": metric_names,
            "timegap": format_timegap(gap),
            "granularity": str(gran),
            "stop_time": stop_time,
            "project_id": project_id,
        }
        raw = self._get(f"{self._BASE}/{object_id}", params=params) or {}
        return {name: _normalize(series) for name, series in raw.items()}

    def host(
        self,
        host_id: str,
        metric_names: Union[str, Sequence[str]] = HOST_METRICS,
        timegap: Duration = "1h",
        **kwargs: Any,
    ) -> Dict[str, Dict[str, Any]]:
        """Fiziksel host metrikleri."""
        return self.query(host_id, "host", metric_names, timegap, **kwargs)

    def server(
        self,
        server_id: str,
        metric_names: Union[str, Sequence[str]] = SERVER_METRICS,
        timegap: Duration = "1h",
        **kwargs: Any,
    ) -> Dict[str, Dict[str, Any]]:
        """VM metrikleri (object_type="server")."""
        return self.query(server_id, "server", metric_names, timegap, **kwargs)

    def az(
        self,
        az_id: str,
        metric_names: Union[str, Sequence[str]] = AZ_METRICS,
        timegap: Duration = "1h",
        **kwargs: Any,
    ) -> Dict[str, Dict[str, Any]]:
        """Resource pool metrikleri."""
        return self.query(az_id, "az", metric_names, timegap, **kwargs)

    def host_summary(self, host_id: str, timegap: Duration = "24h", **kwargs: Any) -> Dict[str, Dict[str, Optional[float]]]:
        """Host metriklerinin min/max/avg/last özeti."""
        return {k: summarize(v) for k, v in self.host(host_id, timegap=timegap, **kwargs).items()}

    def server_summary(self, server_id: str, timegap: Duration = "24h", **kwargs: Any) -> Dict[str, Dict[str, Optional[float]]]:
        """VM metriklerinin min/max/avg/last özeti."""
        return {k: summarize(v) for k, v in self.server(server_id, timegap=timegap, **kwargs).items()}


def _normalize(series: Any) -> Dict[str, Any]:
    if not isinstance(series, dict):
        return {"unit": None, "granularity": None, "datapoints": []}
    points: List[tuple] = []
    for point in series.get("datapoints") or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        points.append((point[0], _to_float(point[1])))
    gran = series.get("granularity")
    try:
        gran = to_seconds(gran) if gran is not None else None
    except ValueError:
        pass
    return {"unit": series.get("unit"), "granularity": gran, "datapoints": points}


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
