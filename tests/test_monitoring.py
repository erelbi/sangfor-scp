"""alarms, metrics, tasks listesi, migrate ön kontrolü ve health raporu — ağ gerektirmez."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from sangfor_scp.exceptions import SCPPreflightError
from sangfor_scp.health import HealthReport, failure_reason, render_text, write_csv
from sangfor_scp.resources.alarms import AlarmsResource
from sangfor_scp.resources.metrics import (
    MetricsResource,
    format_timegap,
    min_granularity,
    summarize,
    to_seconds,
)
from sangfor_scp.resources.servers import ServersResource
from sangfor_scp.resources.system import SystemResource
from sangfor_scp.resources.tasks import TasksResource


def page(data: List[Dict[str, Any]], next_page: str = "") -> Dict[str, Any]:
    return {"data": data, "next_page_num": next_page, "total_size": len(data)}


# ------------------------------------------------------------------ #
# Alarms                                                              #
# ------------------------------------------------------------------ #

def test_parse_partitions_windows_and_linux():
    alarm = {"description": "The disk partition usage of the VM(x) is above the alert threshold "
                            "(90.00%). It is recommended to expand. Disk partition details: "
                            "E:\\（99.23%）, /dev/mapper/centos-home（99.88%）"}
    assert AlarmsResource.parse_partitions(alarm) == [("E:\\", 99.23), ("/dev/mapper/centos-home", 99.88)]


def test_parse_partitions_non_disk_alarm():
    assert AlarmsResource.parse_partitions({"description": "Host CPU usage 66.35%"}) == []


def test_alarms_pagination_and_list_params():
    client = MagicMock()
    client.request.side_effect = [page([{"id": 1, "policy_name": "a"}], "1"),
                                  page([{"id": 2, "policy_name": "a"}, {"id": 3, "policy_name": "b"}])]
    res = AlarmsResource(client)
    assert res.count_by("policy_name", az_ids=["x", "y"]) == [("a", 2), ("b", 1)]
    _, kwargs = client.request.call_args_list[0]
    assert kwargs["params"]["az_ids"] == "x,y"
    assert client.request.call_args_list[1][1]["params"]["page_num"] == 1


# ------------------------------------------------------------------ #
# Metrics                                                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("value,seconds", [(300, 300), ("1h", 3600), ("7d", 604800), ("90s", 90), ("30m", 1800)])
def test_to_seconds(value, seconds):
    assert to_seconds(value) == seconds


@pytest.mark.parametrize("seconds,text", [(3600, "1h"), (86400, "1d"), (7200, "2h"), (1800, "1800s")])
def test_format_timegap(seconds, text):
    assert format_timegap(seconds) == text


def test_min_granularity_rules():
    assert [min_granularity(s) for s in (3600, 86400, 30 * 86400, 31 * 86400)] == [60, 300, 1800, 43200]


def test_query_normalizes_strings_and_sets_params():
    client = MagicMock()
    client.request.return_value = {
        "cpu.util": {"unit": "%", "granularity": "12h",
                     "datapoints": [["t1", "10.5"], ["t2", "20.5"], ["t3", None]]},
    }
    data = MetricsResource(client).host("host-1", timegap="24h")
    params = client.request.call_args[1]["params"]
    assert params["object_type"] == "host"
    assert params["timegap"] == "1d"
    assert params["granularity"] == "300"
    series = data["cpu.util"]
    assert series["granularity"] == 43200
    assert series["datapoints"] == [("t1", 10.5), ("t2", 20.5), ("t3", None)]
    assert summarize(series) == {"min": 10.5, "max": 20.5, "avg": 15.5, "last": 20.5, "count": 2}


def test_server_uses_server_object_type():
    client = MagicMock()
    client.request.return_value = {}
    MetricsResource(client).server("vm-1")
    assert client.request.call_args[1]["params"]["object_type"] == "server"


def _metrics_with_offset(hours: int = 3):
    from datetime import timedelta
    client = MagicMock()
    client.request.return_value = {}
    res = MetricsResource(client)
    res.utc_offset = timedelta(hours=hours)
    return client, res


def _local_now(hours: int = 3):
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours)


def test_stop_time_is_shifted_by_utc_offset():
    from datetime import timedelta
    client, res = _metrics_with_offset()
    stop = (_local_now() - timedelta(hours=2)).replace(microsecond=0)
    res.query("vm-1", "server", "cpu.util", timegap="6h", granularity=300, stop_time=stop)
    params = client.request.call_args[1]["params"]
    assert params["stop_time"] == (stop + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    assert params["timegap"] == "6h"


def test_old_short_window_is_widened_and_trimmed():
    from datetime import timedelta
    client, res = _metrics_with_offset()
    stop = (_local_now() - timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S")
    client.request.return_value = {"cpu.util": {"datapoints": [
        [fmt(stop - timedelta(hours=10)), "1"], [fmt(stop - timedelta(hours=1)), "2"], [fmt(stop), "3"]]}}
    data = res.query("vm-1", "server", "cpu.util", timegap="4h", granularity=300, stop_time=stop)
    params = client.request.call_args[1]["params"]
    assert params["timegap"] == "25h"
    assert params["granularity"] == "300"
    assert [v for _, v in data["cpu.util"]["datapoints"]] == [2.0, 3.0]


def test_window_crossing_24h_limit_queries_without_stop_time():
    from datetime import timedelta
    client, res = _metrics_with_offset()
    stop = _local_now() - timedelta(hours=2)
    res.query("vm-1", "server", "cpu.util", timegap="48h", stop_time=stop)
    params = client.request.call_args[1]["params"]
    assert params["stop_time"] is None
    assert params["granularity"] == "1800"
    assert to_seconds(params["timegap"]) >= 50 * 3600


def test_utc_offset_autodetect_from_probe():
    from datetime import timedelta
    client = MagicMock()
    last = _local_now(3).strftime("%Y-%m-%dT%H:%M:%S")
    client.request.return_value = {"cpu.util": {"datapoints": [[last, "1"]]}}
    res = MetricsResource(client)
    res.query("vm-1", "server", "cpu.util", timegap="1h", stop_time="2020-01-01 00:00:00")
    assert res.utc_offset == timedelta(hours=3)


# ------------------------------------------------------------------ #
# Tasks                                                               #
# ------------------------------------------------------------------ #

def test_list_failed_filters():
    client = MagicMock()
    client.request.return_value = page([{"status": "failure"}])
    assert TasksResource(client).list_failed(days=7) == [{"status": "failure"}]
    params = client.request.call_args[1]["params"]
    assert params["status"] == "failure"
    assert params["begin_time"] < params["end_time"]


# ------------------------------------------------------------------ #
# Migrate                                                             #
# ------------------------------------------------------------------ #

HOSTS = [
    {"id": "host-a", "name": "10.0.0.1", "ip": "10.0.0.1", "az_id": "az1", "type": "h",
     "status": "running", "cpu": {"type": "Intel Xeon Gold 6348"}},
    {"id": "host-b", "name": "10.0.0.2", "ip": "10.0.0.2", "az_id": "az1", "type": "h",
     "status": "running", "cpu": {"type": "Intel Xeon Gold 6348"}},
    {"id": "host-c", "name": "10.0.0.3", "ip": "10.0.0.3", "az_id": "az1", "type": "h",
     "status": "running", "cpu": {"type": "Intel Xeon 6767P"}},
]
VM_LIST_RECORD = {"id": "vm-1", "name": "vm", "az_id": "az1", "host_id": "host-a",
                  "host_name": "10.0.0.1", "storage_id": "ds-1"}


def make_servers(cpu_type: str) -> tuple:
    def request(method: str, path: str, params: Optional[dict] = None, json: Optional[dict] = None, **_):
        if method == "GET" and path == "/janus/20180725/servers/vm-1":
            return {"id": "vm-1", "name": "vm", "az_id": "az1", "host_name": "10.0.0.1"}
        if method == "GET" and path == "/janus/20240725/servers/vm-1":
            return {"advance_param": {"cpu_type": cpu_type}}
        if method == "GET" and path == "/janus/20190725/hosts":
            return page(HOSTS)
        if method == "GET" and path == "/janus/20180725/servers":
            return page([VM_LIST_RECORD])
        if method == "POST" and path.endswith("/migrate"):
            return {"task_id": "task-1"}
        raise AssertionError(f"beklenmeyen istek {method} {path}")

    client = MagicMock()
    client.request.side_effect = request
    client.system = SystemResource(client)
    return ServersResource(client), client


def test_migrate_blocks_host_cpu_across_generations():
    servers, client = make_servers("host")
    with pytest.raises(SCPPreflightError) as exc:
        servers.migrate("vm-1", host_id="host-c")
    assert "CPU modelleri farklı" in exc.value.problems[0]
    assert not any(c[0][0] == "POST" for c in client.request.call_args_list)


def test_migrate_sends_documented_body():
    servers, client = make_servers("host")
    assert servers.migrate("vm-1", host_id="host-b", auto_poweron=True) == "task-1"
    post = [c for c in client.request.call_args_list if c[0][0] == "POST"][0]
    assert post[1]["json"] == {
        "az_id": "az1",
        "storage_location": "ds-1",
        "compute_location": {"id": "host-b"},
        "auto_poweron": 1,
    }


def test_migrate_named_cpu_type_allows_other_generation():
    servers, _ = make_servers("Haswell-noTSX")
    assert servers.check_migration("vm-1", "host-c")["ok"] is True


def test_migrate_requires_target():
    servers, _ = make_servers("host")
    with pytest.raises(ValueError):
        servers.migrate("vm-1")


def test_migrate_same_host_is_problem():
    servers, _ = make_servers("Haswell-noTSX")
    assert servers.check_migration("vm-1", "host-a")["problems"] == ["VM zaten hedef host üzerinde"]


# ------------------------------------------------------------------ #
# Health                                                              #
# ------------------------------------------------------------------ #

def test_failure_reason_groups_cpu_mismatch():
    a = failure_reason("VM migration failed.\nFailed to migrate VM (k8s-1). ... Error: VM used host CPU but "
                       "the CPU models of the source node (10.0.0.1) and the destination node (10.0.0.2) are different.")
    b = failure_reason("VM migration failed. Failed to migrate VM (k8s-2). Error: VM used host CPU but "
                       "the CPU models of the source node (10.0.0.3) and the destination node (10.0.0.4) are different.")
    assert a == b


def test_render_and_csv(tmp_path):
    report = HealthReport(
        generated_at="2026-10-19 12:00:00",
        days=30,
        hosts=HOSTS,
        alarms=[{"level": "p1", "policy_name": "High VM Logical Disk rate", "object_type": "vm",
                 "object_name": "vm-a", "az_name": "POOL1",
                 "description": "Disk partition details: /dev/vda2（100.00%）"}],
        tasks=[{"status": "failure", "action": "Restart VM", "description": "VM internal shutdown failed."},
               {"status": "finish", "action": "Power on"}],
        cpu_types=[{"name": "vm", "cpu_type": "host", "host_cpu_model": "Intel Xeon Gold 6348"}],
        errors={"alarm_history": "yetki yok"},
    )
    text = render_text(report)
    assert "vm-a" in text and "1 başarısız" in text and "yetki yok" in text
    files = write_csv(report, str(tmp_path))
    names = {os.path.basename(p) for p in files}
    assert {"alarmlar.csv", "disk_doluluk.csv", "basarisiz_tasklar.csv", "hostlar.csv", "vm_cpu_tipleri.csv"} <= names
