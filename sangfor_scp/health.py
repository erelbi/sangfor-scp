"""
Platform sağlık raporu — sadece okuma yapar, hiçbir şeyi değiştirmez.

Toplanan veriler:
  - Overview (kapasite özeti), hostlar (CPU modeli, CPU/RAM kullanımı)
  - Anlık alarmlar (disk doluluk alarmları ayrıştırılır)
  - Son N günün task'ları ve başarısız olanlar (nedene göre gruplanır)
  - Kayıp (vm_lost) VM'ler
  - İsteğe bağlı: her HCI VM'in CPU tipi (cpu_scan=True, VM başına 1 istek)

Kullanım:
    from sangfor_scp import SCPClient
    from sangfor_scp.health import collect, render_text, write_csv

    report = collect(client, days=30, cpu_scan=True)
    print(render_text(report))
    write_csv(report, "rapor/")

Komut satırı: scp-health --help
"""
from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import requests

from sangfor_scp.exceptions import SCPError, SCPRateLimitError, SCPServerError
from sangfor_scp.resources.alarms import LEVEL_NAMES, AlarmsResource

if TYPE_CHECKING:
    from sangfor_scp.client import SCPClient

ProgressFn = Callable[[str], None]

MEMORY_WARN = 0.85
DISK_WARN = 90.0


@dataclass
class HealthReport:
    generated_at: str
    days: int
    overview: Dict[str, Any] = field(default_factory=dict)
    hosts: List[Dict[str, Any]] = field(default_factory=list)
    alarms: List[Dict[str, Any]] = field(default_factory=list)
    tasks: List[Dict[str, Any]] = field(default_factory=list)
    lost_vms: List[Dict[str, Any]] = field(default_factory=list)
    vm_status: Dict[str, Dict[str, int]] = field(default_factory=dict)
    cpu_types: List[Dict[str, Any]] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)

    # ---------------------------------------------------------------- #
    # Türetilmiş görünümler                                             #
    # ---------------------------------------------------------------- #

    @property
    def failed_tasks(self) -> List[Dict[str, Any]]:
        return [t for t in self.tasks if t.get("status") == "failure"]

    def disk_alarms(self) -> List[Dict[str, Any]]:
        """Disk doluluk alarmları, en dolu bölüme göre azalan sırada."""
        rows = []
        for alarm in self.alarms:
            parts = AlarmsResource.parse_partitions(alarm)
            if not parts:
                continue
            rows.append({
                "vm": alarm.get("object_name"),
                "pool": alarm.get("az_name"),
                "level": alarm.get("level"),
                "since": alarm.get("start_time"),
                "repeat": alarm.get("converge_count"),
                "max_pct": max(p for _, p in parts),
                "partitions": ", ".join(f"{name} %{pct:.2f}" for name, pct in parts),
            })
        return sorted(rows, key=lambda r: r["max_pct"], reverse=True)

    def other_alarms(self) -> List[Dict[str, Any]]:
        return [a for a in self.alarms if not AlarmsResource.parse_partitions(a)]

    def failure_groups(self) -> List[Tuple[str, str, int, List[Dict[str, Any]]]]:
        """Başarısız task'ları (işlem, neden) ikilisine göre gruplar."""
        groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for task in self.failed_tasks:
            groups[(task.get("action") or "", failure_reason(task.get("description") or ""))].append(task)
        return sorted(
            ((a, r, len(ts), ts) for (a, r), ts in groups.items()),
            key=lambda g: g[2],
            reverse=True,
        )

    def cpu_generations(self) -> Dict[Tuple[str, str], List[str]]:
        """(cluster, CPU modeli) → host adları."""
        out: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for host in self.hosts:
            out[(host.get("cluster_name") or "", _cpu_model(host))].append(host.get("name") or "")
        return dict(out)

    def host_cpu_vms(self) -> List[Dict[str, Any]]:
        return [v for v in self.cpu_types if v.get("cpu_type") == "host"]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -------------------------------------------------------------------- #
# Toplama                                                               #
# -------------------------------------------------------------------- #

def collect(
    client: "SCPClient",
    days: int = 30,
    cpu_scan: bool = False,
    workers: int = 4,
    max_rps: float = 8.0,
    progress: Optional[ProgressFn] = None,
) -> HealthReport:
    """
    Sağlık verisini toplar. Bir bölüm başarısız olursa (ör. yetki yok)
    rapor yine üretilir; hata report.errors içine yazılır.

    Args:
        days:     Task geçmişi için gün sayısı
        cpu_scan: True → her HCI VM'in CPU tipini çek (VM başına ~1-4 sn,
                  workers ile paralel)
        workers:  cpu_scan için paralel istek sayısı
        max_rps:  Saniyedeki en fazla istek (API sınırı GET 600/dk = 10/sn)
    """
    say = progress or (lambda _msg: None)
    report = HealthReport(generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), days=days)

    def section(name: str, fn: Callable[[], Any]) -> Any:
        say(f"{name}...")
        try:
            return fn()
        except (SCPError, requests.RequestException) as exc:
            report.errors[name] = str(exc).splitlines()[0][:300]
            return None

    report.overview = section("overview", client.system.overview) or {}
    report.hosts = section("hosts", lambda: list(client.system.list_all_hosts())) or []
    report.alarms = section("alarms", client.alarms.list) or []
    report.tasks = section("tasks", lambda: list(client.tasks.list_since(days))) or []
    servers = section("servers", lambda: list(client.servers.list_all())) or []

    hci_pools = {h.get("az_id") for h in report.hosts if h.get("type") == "h"}
    status: Dict[str, Counter] = defaultdict(Counter)
    for vm in servers:
        status[vm.get("az_name") or vm.get("az_id") or "?"][vm.get("status") or "?"] += 1
        if vm.get("status") == "vm_lost" and vm.get("az_id") in hci_pools:
            report.lost_vms.append(_pick(vm, "id", "name", "az_name", "host_name", "storage_name"))
    report.vm_status = {pool: dict(c) for pool, c in status.items()}

    if cpu_scan:
        targets = [
            vm for vm in servers
            if vm.get("az_id") in hci_pools and vm.get("status") != "vm_lost"
        ]
        say(f"cpu tipi taraması: {len(targets)} VM, {workers} paralel")
        report.cpu_types = _scan_cpu_types(client, targets, report.hosts, workers, max_rps, say)

    return report


def _scan_cpu_types(
    client: "SCPClient",
    vms: List[Dict[str, Any]],
    hosts: List[Dict[str, Any]],
    workers: int,
    max_rps: float,
    say: ProgressFn,
) -> List[Dict[str, Any]]:
    model_by_host = {}
    for host in hosts:
        for key in (host.get("name"), host.get("ip"), host.get("id")):
            if key:
                model_by_host[key] = _cpu_model(host)

    throttle = _Throttle(max_rps)
    done = [0]
    lock = threading.Lock()

    def one(vm: Dict[str, Any]) -> Dict[str, Any]:
        row = _pick(vm, "id", "name", "az_name", "status", "host_name")
        row["cpu_type"] = None
        for attempt in range(3):
            throttle.wait()
            try:
                config = client.servers.get_config(vm["id"])
                row["cpu_type"] = (config.get("advance_param") or {}).get("cpu_type")
                break
            except (SCPRateLimitError, SCPServerError, requests.RequestException) as exc:
                row["error"] = str(exc)[:200]
                time.sleep(2 * (attempt + 1))
            except SCPError as exc:
                row["error"] = str(exc)[:200]
                break
        if row.get("cpu_type") is not None:
            row.pop("error", None)
        row["host_cpu_model"] = model_by_host.get(vm.get("host_name") or "", "")
        with lock:
            done[0] += 1
            if done[0] % 100 == 0:
                say(f"  {done[0]}/{len(vms)}")
        return row

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        rows = list(pool.map(one, vms))
    return sorted(rows, key=lambda r: (r.get("cpu_type") != "host", r.get("cpu_type") or "", r.get("name") or ""))


class _Throttle:
    """Thread'ler arası basit hız sınırlayıcı (istekler arası en az 1/rps sn)."""

    def __init__(self, rps: float):
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            time.sleep(delay)


# -------------------------------------------------------------------- #
# Yardımcılar                                                           #
# -------------------------------------------------------------------- #

_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_PAREN_RE = re.compile(r"\([^)]*\)")


def failure_reason(description: str) -> str:
    """Task hata açıklamasını gruplanabilir kısa bir nedene indirger."""
    text = " ".join(description.split())
    if "CPU models of the source node" in text:
        return "VM CPU tipi 'host' ve kaynak/hedef host CPU modelleri farklı"
    text = re.sub(r"^VM migration failed\.\s*", "", text)
    text = _PAREN_RE.sub("(…)", text)
    text = _IP_RE.sub("x.x.x.x", text)
    return text[:160] or "(açıklama yok)"


def _cpu_model(host: Dict[str, Any]) -> str:
    model = (host.get("cpu") or {}).get("type") or host.get("type") or ""
    model = re.sub(r"\(R\)|\(TM\)|\bCPU\b|@.*$", "", model)
    return " ".join(model.split())


def _pick(d: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    return {k: d.get(k) for k in keys}


def _pct(value: Any) -> str:
    try:
        return f"%{float(value) * 100:.0f}"
    except (TypeError, ValueError):
        return "-"


# -------------------------------------------------------------------- #
# Çıktı                                                                 #
# -------------------------------------------------------------------- #

def render_text(report: HealthReport, top: int = 15) -> str:
    """İnsan okunur Türkçe özet."""
    out: List[str] = []
    w = out.append
    w(f"SCP sağlık raporu — {report.generated_at}")
    w("=" * 60)

    if report.errors:
        w("\nOkunamayan bölümler:")
        for name, msg in report.errors.items():
            w(f"  - {name}: {msg}")

    # Alarmlar
    w(f"\n## Açık alarmlar: {len(report.alarms)}")
    if report.alarms:
        levels = Counter(a.get("level") for a in report.alarms)
        w("  Seviye: " + ", ".join(f"{lvl} ({LEVEL_NAMES.get(lvl, '?')}) {n}" for lvl, n in sorted(levels.items())))
        policies = Counter(a.get("policy_name") for a in report.alarms)
        for name, n in policies.most_common(8):
            w(f"  {n:4}  {name}")

    disks = report.disk_alarms()
    if disks:
        w(f"\n## VM disk doluluğu (≥%{DISK_WARN:.0f}): {len(disks)} VM")
        for r in disks[:top]:
            w(f"  {r['vm']:<32} {r['pool'] or '':<9} {r['partitions'][:70]}  (başlangıç {r['since']})")
        if len(disks) > top:
            w(f"  ... ve {len(disks) - top} VM daha")

    others = report.other_alarms()
    if others:
        w(f"\n## Diğer alarmlar: {len(others)}")
        for a in sorted(others, key=lambda a: (a.get("level") or "", a.get("start_time") or ""))[:top]:
            desc = " ".join((a.get("description") or "").split())[:110]
            w(f"  [{a.get('level')}] {a.get('object_type')}:{a.get('object_name')} — {desc}")

    # Task'lar
    failed = report.failed_tasks
    w(f"\n## Task'lar (son {report.days} gün): {len(report.tasks)} toplam, {len(failed)} başarısız")
    for action, reason, n, _ in report.failure_groups()[:top]:
        w(f"  {n:3}× {action}: {reason}")

    # Hostlar
    if report.hosts:
        w(f"\n## Hostlar: {len(report.hosts)}")
        for (cluster, model), names in sorted(report.cpu_generations().items()):
            w(f"  {cluster:<10} {model:<28} {len(names):2} host  {_short_names(names)}")
        hot = [h for h in report.hosts if _float((h.get("memory") or {}).get("ratio")) >= MEMORY_WARN]
        if hot:
            w(f"  RAM ≥ %{MEMORY_WARN * 100:.0f}: " + ", ".join(
                f"{h.get('name')} {_pct((h.get('memory') or {}).get('ratio'))}"
                for h in sorted(hot, key=lambda h: -_float((h.get("memory") or {}).get("ratio")))
            ))
        offline = [h.get("name") for h in report.hosts if h.get("status") not in ("running", None)]
        if offline:
            w(f"  Çalışmayan: {', '.join(offline)}")

    # Kapasite
    virt = {r.get("name"): r for r in report.overview.get("virtual_resources", [])}
    mem, cpu = virt.get("Memory"), virt.get("CPU")
    if mem or cpu:
        w("\n## Kapasite (HCI)")
        for label, r in (("RAM", mem), ("CPU", cpu)):
            if r and r.get("total"):
                w(f"  {label}: ayrılan {r.get('allocated')} / toplam {r.get('total'):.0f} {r.get('unit')} "
                  f"(%{100 * float(r.get('allocated', 0)) / float(r['total']):.0f})")

    # VM durumları
    if report.vm_status:
        w("\n## VM durumları")
        for pool, counts in sorted(report.vm_status.items()):
            w(f"  {pool:<10} " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if report.lost_vms:
        w(f"  HCI'de kayıp (vm_lost) VM: {len(report.lost_vms)}")

    # CPU tipleri
    if report.cpu_types:
        types = Counter(v.get("cpu_type") for v in report.cpu_types)
        w(f"\n## VM CPU tipleri ({len(report.cpu_types)} VM)")
        for t, n in types.most_common():
            w(f"  {n:5}  {t}")
        host_vms = report.host_cpu_vms()
        if host_vms:
            by_model = Counter(v.get("host_cpu_model") for v in host_vms)
            w("  'host' tipindeki VM'lerin bulunduğu CPU nesli: " +
              ", ".join(f"{m or '?'} {n}" for m, n in by_model.most_common()))
        failed_scan = [v for v in report.cpu_types if v.get("error")]
        if failed_scan:
            w(f"  Okunamayan: {len(failed_scan)} VM")

    return "\n".join(out)


def write_csv(report: HealthReport, directory: str) -> List[str]:
    """
    Raporu CSV dosyalarına yazar (; ayraçlı, UTF-8 BOM — Excel'de doğrudan açılır).

    Returns:
        Yazılan dosya yolları
    """
    os.makedirs(directory, exist_ok=True)
    written: List[str] = []

    def dump(name: str, header: List[str], rows: List[List[Any]]) -> None:
        if not rows:
            return
        path = os.path.join(directory, name)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(header)
            writer.writerows(rows)
        written.append(path)

    dump("alarmlar.csv",
         ["seviye", "durum", "baslangic", "nesne_tipi", "nesne", "pool", "politika", "tekrar", "aciklama"],
         [[a.get("level"), a.get("status"), a.get("start_time"), a.get("object_type"), a.get("object_name"),
           a.get("az_name"), a.get("policy_name"), a.get("converge_count"),
           " ".join((a.get("description") or "").split())] for a in report.alarms])
    dump("disk_doluluk.csv",
         ["vm", "pool", "en_dolu_yuzde", "bolumler", "baslangic", "tekrar"],
         [[r["vm"], r["pool"], f"{r['max_pct']:.2f}", r["partitions"], r["since"], r["repeat"]]
          for r in report.disk_alarms()])
    dump("basarisiz_tasklar.csv",
         ["zaman", "islem", "nesne_tipi", "nesne_id", "kullanici_ip", "neden", "aciklama"],
         [[t.get("begin_time"), t.get("action"), t.get("object_type"), t.get("object_id"), t.get("user_ip"),
           failure_reason(t.get("description") or ""), " ".join((t.get("description") or "").split())]
          for t in report.failed_tasks])
    dump("hostlar.csv",
         ["host", "cluster", "durum", "cpu_modeli", "cpu_kullanim", "ram_kullanim", "ram_gb", "alarm"],
         [[h.get("name"), h.get("cluster_name"), h.get("status"), _cpu_model(h),
           _float((h.get("cpu") or {}).get("ratio")), _float((h.get("memory") or {}).get("ratio")),
           round(_float((h.get("memory") or {}).get("total_mb")) / 1024), h.get("alarm_count")]
          for h in report.hosts])
    dump("kayip_vmler.csv",
         ["vm", "pool", "host", "storage", "id"],
         [[v.get("name"), v.get("az_name"), v.get("host_name"), v.get("storage_name"), v.get("id")]
          for v in report.lost_vms])
    dump("vm_cpu_tipleri.csv",
         ["vm", "pool", "durum", "cpu_tipi", "host", "host_cpu_modeli", "id"],
         [[v.get("name"), v.get("az_name"), v.get("status"), v.get("cpu_type"), v.get("host_name"),
           v.get("host_cpu_model"), v.get("id")] for v in report.cpu_types])
    return written


def write_json(report: HealthReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, ensure_ascii=False, indent=1, default=str)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _short_names(names: List[str]) -> str:
    """['10.0.0.151', '10.0.0.152'] → '.151 .152' (ortak önek kısaltılır)."""
    names = sorted(names, key=lambda n: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", n)])
    prefix = os.path.commonprefix(names)
    prefix = prefix[: prefix.rfind(".") + 1] if "." in prefix else ""
    return " ".join(("." + n[len(prefix):]) if prefix else n for n in names)
