"""
Gerçek ortamda VM oluşturma testi.

Kimlik bilgileri proje kökündeki .env dosyasından okunur (git'e girmez):
    SCP_HOST=10.x.x.x
    SCP_ACCESS_KEY=...
    SCP_SECRET_KEY=...
    SCP_REGION=cn-south-1      # isteğe bağlı

Kullanım:
    # 1) Sadece okuma: resource pool, imaj, storage tag, ağ ve örnek VM NIC yapısı
    python examples/vm_create_test.py discover

    # 2) VM oluştur, task'ı bekle, doğrula (--cleanup → sonra sil)
    #    --network verilmezse NIC'siz VM oluşur
    python examples/vm_create_test.py create --az AZ --image IMG --storage-tag TAG \\
        --disks '[{"id": "ide0", "type": "new_disk", "size_mb": 10240}]' \\
        --network '{"vif_id": "net0", "vpc_id": "...", "subnet_id": "...", "connect": 1}' \\
        --cleanup

    Klasik ağ NIC'i: device_id=switch ID, port_id=VLAN grubu ID ve ip_info zorunlu
    (bkz. client.networks.classic_nic()).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sangfor_scp import SCPClient, SCPError  # noqa: E402


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_client() -> SCPClient:
    load_env(Path(__file__).resolve().parent.parent / ".env")
    missing = [k for k in ("SCP_HOST", "SCP_ACCESS_KEY", "SCP_SECRET_KEY") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Eksik ortam değişkeni: {', '.join(missing)} (.env dosyasına ekleyin)")
    return SCPClient(
        host=os.environ["SCP_HOST"],
        access_key=os.environ["SCP_ACCESS_KEY"],
        secret_key=os.environ["SCP_SECRET_KEY"],
        region=os.environ.get("SCP_REGION", "cn-south-1"),
    )


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def try_call(label: str, fn):
    try:
        return fn()
    except SCPError as exc:
        print(f"  [HATA] {label}: {exc}")
        return None


def discover(client: SCPClient) -> None:
    section("Resource pool'lar")
    pools = try_call("resource_pools.list", client.resource_pools.list) or []
    for az in pools:
        print(f"  {az.get('id')}  {az.get('name')}  type={az.get('type')}")

    for az in pools:
        section(f"Storage tag'ler — {az.get('name')}")
        for tag in try_call("storage_tags", lambda: client.resource_pools.storage_tags(az["id"])) or []:
            print(f"  {tag.get('id')}  {tag.get('name')}")

    section("İmajlar (ilk 20)")
    images = try_call("images.list", client.images.list) or []
    for img in images[:20]:
        print(f"  {img.get('id')}  {img.get('name')}  type={img.get('image_type')}  "
              f"os={img.get('os_type')}  status={img.get('status')}")

    section("VPC / Subnet")
    vpcs = try_call("list_vpcs", lambda: list(client.networks.list_vpcs())) or []
    for vpc in vpcs:
        print(f"  VPC {vpc.get('id')}  {vpc.get('name')}")
        for sn in try_call("list_subnets", lambda: list(client.networks.list_subnets(vpc_id=vpc["id"]))) or []:
            print(f"    subnet {sn.get('id')}  {sn.get('name')}  {sn.get('cidr')}")
    if not vpcs:
        print("  (VPC yok)")

    section("Klasik ağ switch'leri ve VLAN grupları (port_id)")
    switches = try_call("list_classic_switches", lambda: list(client.networks.list_classic_switches())) or []
    for sw in switches:
        print(f"  switch {sw.get('id')}  {sw.get('name')}  az={sw.get('az_id')}")
        for g in sw.get("vlan_group") or []:
            print(f"    vlan_group {g.get('id')}  {g.get('name')}  {g.get('type')}  {g.get('vlan_range')}")
    if not switches:
        print("  (klasik switch yok)")

    section("Örnek VM NIC yapısı (create için 'networks' şablonu)")
    servers = try_call("servers.list_page", lambda: client.servers.list_page(page_size=1)) or {}
    sample = (servers.get("data") or [None])[0]
    if sample:
        detail = try_call("servers.get", lambda: client.servers.get(sample["id"])) or sample
        print(f"  VM: {detail.get('name')} ({detail.get('id')})")
        for key in ("networks", "nics", "interfaces"):
            if key in detail:
                print(f"  {key}: {json.dumps(detail[key], indent=2, ensure_ascii=False)}")
        for key in ("disks", "storage_tag_id", "az_id", "image_id"):
            if key in detail:
                print(f"  {key}: {json.dumps(detail[key], ensure_ascii=False)}")
    else:
        print("  (VM yok)")


def create(client: SCPClient, args: argparse.Namespace) -> None:
    name = args.name or f"sdk-test-{time.strftime('%Y%m%d-%H%M%S')}"
    networks = [json.loads(n) for n in args.network]
    disks = json.loads(args.disks) if args.disks else None

    section(f"VM oluşturuluyor: {name}")
    result = client.servers.create(
        az_id=args.az,
        image_id=args.image,
        storage_tag_id=args.storage_tag,
        cores=args.cores,
        memory_mb=args.memory_mb,
        name=name,
        networks=networks,
        disks=disks,
        power_on=not args.no_power_on,
    )
    print(f"  yanıt: {result}")
    task_id = result.get("task_id")
    uuids = result.get("uuids") or []

    if task_id:
        section("Task bekleniyor")
        task = client.tasks.wait(
            task_id,
            timeout=args.timeout,
            progress_callback=lambda t: print(f"  status={t.get('status')} progress={t.get('progress')}"),
        )
        print(f"  [OK] task tamamlandı: {task.get('status')}")

    for vm_id in uuids:
        section(f"Doğrulama — {vm_id}")
        vm = client.servers.get(vm_id)
        print(f"  name={vm.get('name')} status={vm.get('status')} "
              f"cores={vm.get('cores')} memory_mb={vm.get('memory_mb')}")

    if args.cleanup:
        for vm_id in uuids:
            section(f"Temizlik — {vm_id} siliniyor")
            del_task = client.servers.delete(vm_id)
            if del_task:
                client.tasks.wait(del_task, timeout=args.timeout)
            print("  [OK] silindi")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="Sadece okuma: create için gereken ID'leri listeler")

    c = sub.add_parser("create", help="VM oluşturur")
    c.add_argument("--az", required=True, help="Resource pool ID")
    c.add_argument("--image", required=True, help="İmaj ID")
    c.add_argument("--storage-tag", required=True, help="Storage tag ID")
    c.add_argument("--network", action="append", default=[], help="NIC JSON (birden çok verilebilir; boş → NIC'siz VM)")
    c.add_argument("--disks", help="Disk listesi JSON (boş → imajdan)")
    c.add_argument("--name", help="VM adı (varsayılan sdk-test-<zaman>)")
    c.add_argument("--cores", type=int, default=1)
    c.add_argument("--memory-mb", type=int, default=1024)
    c.add_argument("--no-power-on", action="store_true")
    c.add_argument("--timeout", type=int, default=900)
    c.add_argument("--cleanup", action="store_true", help="Test sonunda VM'i sil")

    args = parser.parse_args()
    client = make_client()
    if args.cmd == "discover":
        discover(client)
    else:
        create(client, args)


if __name__ == "__main__":
    main()
