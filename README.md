# sangfor-scp

[![PyPI version](https://badge.fury.io/py/sangfor-scp.svg)](https://pypi.org/project/sangfor-scp/)
[![Python](https://img.shields.io/pypi/pyversions/sangfor-scp)](https://pypi.org/project/sangfor-scp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

📖 **[Live Examples & API Docs →](https://erelbi.github.io/sangfor-scp/)**

**Sangfor Cloud Platform (SCP) Open-API Python Client Library**

A clean, Pythonic wrapper for the Sangfor Cloud Platform REST API.
Supports EC2 (AWS4-HMAC-SHA256) and Token-based authentication with a **single login on initialization** — no repeated auth delays between calls.

---

## Features

- **Single login** — authenticate once in `__init__`, session reused for all requests
- **Auto token refresh** — 24-hour tokens renewed transparently
- **Automatic pagination** — `list_all()` iterates every page lazily; no manual page tracking needed
- **Async task support** — `tasks.wait()` polls until completion, raises on failure or timeout
- **Idempotency** — automatic `X-Client-Token` headers on POST/PUT requests
- **Both auth methods** — EC2 signature (recommended) and Token-based (RSA encrypted)
- **SSL flexibility** — optional SSL verification disable (for self-signed certs)

### Covered APIs (Top 20 Critical Features)

| Resource | Operations |
|---|---|
| **Virtual Machines** | list, get, get_config (CPU type, BIOS…), create, update/rename, delete, power on/off/reboot/suspend, clone, migrate (with CPU-compatibility preflight), console URL, password reset, batch ops, soft delete & restore |
| **Tasks** | get, wait (with timeout & progress callback), list / list_since / list_failed |
| **Alarms** | active alarms (filter by level/status/object), history, count_by, disk-partition parsing |
| **Metrics** | host / VM / resource pool time series (CPU, RAM, IO, network), min/max/avg summary |
| **Resource Pools (AZ)** | list, get, overview, storage tags |
| **Tenants** | list, get, find by name |
| **VPC Networks** | list, create, get, update, delete |
| **Subnets** | list, create, get, delete |
| **Images** | list (ISO/aCloud), get |
| **Volumes (Disks)** | list, create, get, delete, resize, attach, detach |
| **Elastic IPs** | allocate, bind, unbind, release, update bandwidth |
| **Physical Hosts** | list, get, interfaces |
| **System** | version, maintenance mode, platform info, license |

---

## Installation

```bash
pip install sangfor-scp
```

With Token-based authentication support (RSA encryption):

```bash
pip install sangfor-scp[token-auth]
```

### Distribution repositories

```bash
# Fedora 43+, EPEL 10 (Copr)
sudo dnf copr enable erelbi/sangfor-scp && sudo dnf install python3-sangfor-scp

# openSUSE Tumbleweed (OBS); for Leap use openSUSE_Leap_16.0 or openSUSE_Leap_15.6
sudo zypper addrepo https://download.opensuse.org/repositories/home:erelbi/openSUSE_Tumbleweed/home:erelbi.repo
sudo zypper refresh && sudo zypper install python3-sangfor-scp   # Leap 15.6: python311-sangfor-scp

# Debian 12/13, Ubuntu 24.04/26.04 (OBS); set R to Debian_12, Debian_13, xUbuntu_24.04 or xUbuntu_26.04
R=https://download.opensuse.org/repositories/home:/erelbi/xUbuntu_24.04
curl -fsSL "$R/Release.key" | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/home_erelbi.gpg >/dev/null
echo "deb $R/ /" | sudo tee /etc/apt/sources.list.d/home_erelbi.list
sudo apt update && sudo apt install python3-sangfor-scp
```

### RPM / DEB packages

Native packages install the library system-wide together with the
`scp-health` command. Build them in containers (podman or docker; nothing is
installed on the host):

```bash
packaging/build.sh          # → dist/packages/*.rpm, *.deb
packaging/build.sh test     # install & smoke-test in clean Fedora, Debian and Ubuntu containers
```

```bash
sudo dnf install ./dist/packages/python3-sangfor-scp-*.noarch.rpm   # Fedora 44
sudo apt install ./dist/packages/python3-sangfor-scp_*_all.deb       # Debian 13, Ubuntu 24.04
```

Token authentication additionally needs `python3-pycryptodomex` (Fedora) or
`python3-pycryptodome` (Debian/Ubuntu); both are pulled in as recommended packages.

---

## Quick Start

### EC2 Authentication (Recommended)

```python
from sangfor_scp import SCPClient

client = SCPClient(
    host="10.134.37.79",
    access_key="your_access_key",
    secret_key="your_secret_key",
    region="cn-south-1",
    verify_ssl=False,   # SCP uses self-signed certs by default
)
```

### Token-Based Authentication

```python
from sangfor_scp import SCPClient

client = SCPClient(
    host="10.134.37.79",
    username="admin",
    password="your_password",
    verify_ssl=False,
)
```

---

## Usage Examples

### List All Virtual Machines

```python
# Iterates all pages automatically — no pagination code needed
for vm in client.servers.list_all():
    print(vm["id"], vm["name"], vm["status"])

# Filter by resource pool
for vm in client.servers.list_all(az_id="az-uuid", status="running"):
    print(vm["name"])
```

### Create a VM and Wait for Completion

```python
result = client.servers.create(
    az_id="az-uuid",
    image_id="image-uuid",
    storage_tag_id="storage-tag-uuid",
    cores=2,
    memory_mb=2048,
    name="my-vm",
    networks=[{
        "vif_id": "net0",
        "vpc_id": "vpc-uuid",
        "subnet_id": "subnet-uuid",
        "connect": 1,
        "model": "virtio",
    }],
    power_on=True,
)

# Wait up to 5 minutes for the VM to be ready
task = client.tasks.wait(result["task_id"], timeout=300)
vm_id = result["uuids"][0]
print(f"VM created: {vm_id}")
```

### Declarative Provisioning (Terraform-style)

Describe the whole machine once — names are resolved to IDs, the spec is
validated (image active in pool, IP not in use, VLAN exists, disk sizes),
and `apply` waits until the VM is running.

```yaml
# examples/specs/web-01.yaml
name: web-01
resource_pool: POOL-A
image: ubuntu-2404-template            # aCloud template with vmtools
storage_tag: High Performance Storage
cores: 2
memory_gb: 4
disks: [{size_gb: 150}, {size_gb: 20}]
networks:
  - {switch: edge-switch-1, vlan: vlan100, ip: 192.168.100.50, netmask: 255.255.255.0, gateway: 192.168.100.1}
hostname: web-01
power_on: true
```

```bash
python examples/provision.py plan    examples/specs/web-01.yaml
SCP_VM_PASSWORD=... python examples/provision.py apply examples/specs/web-01.yaml
python examples/provision.py destroy examples/specs/web-01.yaml
```

```python
plan = client.provisioner.plan(spec)   # read-only; action: create | no-op | drift
print(plan.summary())
vm = client.provisioner.apply(spec, on_event=print)
client.provisioner.destroy(spec)
```

Re-running `apply` for an existing VM is a no-op; differences from the spec
are reported as drift and never changed automatically.

### Rename / Update a VM

```python
# Rename
task_id = client.servers.rename("vm-uuid", "new-name")
client.tasks.wait(task_id)

# Update multiple properties at once (only passed fields are changed)
task_id = client.servers.update(
    "vm-uuid",
    name="renamed-vm",
    cores=4,
    memory_mb=8192,
    description="Updated description",
)
client.tasks.wait(task_id)
```

### Power Operations

```python
client.servers.stop("vm-uuid")
client.servers.stop("vm-uuid", force=True)     # force power off
client.servers.start("vm-uuid")
client.servers.reboot("vm-uuid")
client.servers.reboot("vm-uuid", force=True)   # force reboot
client.servers.suspend("vm-uuid")
```

### Clone a VM

```python
result = client.servers.clone(
    "vm-uuid",
    name="cloned-vm",
    az_id="az-uuid",           # optional: target resource pool
    storage_tag_id="tag-uuid", # optional: target storage
)
client.tasks.wait(result["task_id"])
new_vm_id = result["uuid"]
```

### Migrate a VM

```python
# Preflight only — sends nothing to the API
check = client.servers.check_migration("vm-uuid", "host-xxxx")
print(check["ok"], check["cpu_type"], check["problems"])

# Migrate. az_id and storage_location default to the target host's pool
# and the VM's current datastore. With check=True (default) the call raises
# SCPPreflightError instead of submitting a migration that SCP would reject,
# e.g. a VM with cpu_type="host" moving to a host with a different CPU model.
task_id = client.servers.migrate("vm-uuid", host_id="host-xxxx", auto_poweron=True)
client.tasks.wait(task_id)
```

> `migrate()` before v0.4.0 sent `host_id`/`storage_tag_id`, which the API does not accept.
> The body now follows the Open-API spec: `az_id`, `storage_location`, `compute_location`.

### Get Console URL (VNC/SPICE/RDP)

```python
info = client.servers.get_console("vm-uuid")
print(info["url"])   # Open in browser for noVNC console

# SPICE console
info = client.servers.get_console("vm-uuid", protocol="spice")
```

### Batch Operations

```python
vm_ids = ["vm-uuid-1", "vm-uuid-2", "vm-uuid-3"]

# Soft delete (move to recycle bin)
client.servers.soft_delete(vm_ids)

# Restore from recycle bin
task_id = client.servers.restore("vm-uuid-1")
client.tasks.wait(task_id)

# Other batch actions
client.servers.batch_action(vm_ids, "start_servers_action")
client.servers.batch_action(vm_ids, "stop_servers_action")
client.servers.batch_action(vm_ids, "reboot_servers_action")
```

### Disk Management

```python
# Create a standalone disk
result = client.volumes.create(
    az_id="az-uuid",
    storage_tag_id="tag-uuid",
    size_mb=102400,   # 100 GB
    name="data-disk",
)
client.tasks.wait(result["task_id"])
volume_id = result["volume_id"]

# Attach to a VM
task_id = client.servers.attach_volume("vm-uuid", volume_id)
client.tasks.wait(task_id)

# Detach
task_id = client.servers.detach_volume("vm-uuid", volume_id)
client.tasks.wait(task_id)
```

### Network Management

```python
# List VPCs
for vpc in client.networks.list_vpcs(az_id="az-uuid"):
    print(vpc["id"], vpc["name"])

# Create Subnet
result = client.networks.create_subnet(
    vpc_id="vpc-uuid",
    az_id="az-uuid",
    cidr="192.168.10.0/24",
    name="subnet-app",
    gateway_ip="192.168.10.1",
)

# List subnets in a VPC
for subnet in client.networks.list_subnets(vpc_id="vpc-uuid"):
    print(subnet["id"], subnet["cidr"])
```

### Classic Network (non-VPC environments)

```python
# Find the VLAN group (port) on an edge-connected virtual switch
group = client.networks.find_vlan_group("vlan100", az_id="az-uuid")

# Classic network NICs require port_id and ip_info
nic = client.networks.classic_nic(
    switch_id=group["switch_id"],
    vlan_group_id=group["id"],
    ip_address="192.168.100.50",
    netmask="255.255.255.0",
    gateway="192.168.100.1",
)
result = client.servers.create(..., networks=[nic])
```

### Elastic IP

```python
# List EIP pools
pools = client.eips.list_pools()

# Allocate (bandwidth in Mbps, converted to kbps for the API)
eip = client.eips.allocate(
    project_id="tenant-id",
    bandwidth_mb=100,
    floatingip_pool_id=pools[0]["id"],
)
eip_id = eip["id"]

# Bind to a VM NIC
task_id = client.eips.bind(eip_id, vpc_id="vpc-uuid", port_id="port-uuid")
client.tasks.wait(task_id)

# Bound / unbound EIPs
for e in client.eips.list_bound():
    print(e["floating_ip"], e["binding_info"]["ip_address"])

# Unbind and release
client.eips.unbind(eip_id)
client.eips.release(eip_id)
```

### Platform Overview

```python
# Resource utilization summary
overview = client.resource_pools.overview()
print(f"Total VMs: {overview['server']['total']}")
print(f"Running VMs: {overview['server']['running_count']}")

# SCP version
info = client.system.version()
print(info["build_version"])
```

### Alarms

```python
# Active critical alarms
for alarm in client.alarms.list_all(level="p1"):          # p1 critical, p2 medium, p3 low
    print(alarm["object_name"], alarm["description"])

client.alarms.count_by("policy_name")                      # [("High VM Logical Disk rate", 29), ...]

# Disk-usage alarms → partitions
for alarm in client.alarms.list_all():
    for partition, pct in client.alarms.parse_partitions(alarm):
        print(alarm["object_name"], partition, pct)
```

### Metrics

```python
# Last 24 h of host CPU/RAM (granularity picked automatically)
data = client.metrics.host("host-xxxx", timegap="24h")
print(data["cpu.util"]["datapoints"][-1])                  # ("2026-10-19T21:40:00", 14.2)

client.metrics.host_summary("host-xxxx", timegap="7d")     # {"cpu.util": {"min", "max", "avg", "last", "count"}, ...}
client.metrics.server_summary("vm-uuid", timegap="1h")     # VM: object_type "server"
client.metrics.az("az-uuid", metric_names=["disk.util"])   # resource pool storage usage

# A past window: stop_time is the platform's local time (same clock as the returned timestamps)
client.metrics.server("vm-uuid", ["cpu.util", "net.in.bps"],
                      timegap="6h", granularity=300, stop_time="2026-10-20 18:00:00")
```

The API shifts `stop_time` by the platform's UTC offset and rejects some windows
(a window older than 24 h needs `timegap` > 24h; a window crossing the 24 h mark is
refused). `metrics.query()` corrects the shift (offset auto-detected once, or set
`client.metrics.utc_offset`) and widens/trims the request so any window works.

### Task History

```python
for task in client.tasks.list_failed(days=30):
    print(task["begin_time"], task["action"], task["description"])

client.tasks.list(object_id="vm-uuid")                     # history of one VM
```

### Health Report (CLI)

Read-only report of alarms, VM disk usage, failed tasks grouped by cause,
host CPU generations, memory pressure, capacity and lost VMs.

```bash
pip install sangfor-scp
export SCP_HOST=https://10.x.x.x SCP_ACCESS_KEY=... SCP_SECRET_KEY=...   # or a .env file

scp-health                                   # text summary
scp-health --days 7 --csv report/            # also write CSV files (Excel-ready)
scp-health --cpu-scan --workers 4 --csv report/   # + CPU type of every HCI VM (1 request per VM)
```

From Python:

```python
from sangfor_scp.health import collect, render_text, write_csv
report = collect(client, days=30, cpu_scan=False)
print(render_text(report))
```

### Async Task with Progress Callback

```python
def on_progress(task_data):
    print(f"Progress: {task_data['progress']}% — {task_data.get('description', '')}")

task = client.tasks.wait(
    task_id="task-uuid",
    timeout=600,
    poll_interval=5,
    progress_callback=on_progress,
)
```

### Manual Pagination

```python
# Get a single page with full metadata
page = client.servers.list_page(page_num=0, page_size=10)
print(f"Total VMs: {page['total_size']}")
print(f"Next page: {page['next_page_num']}")

# Count without fetching all records
total = client.servers.count(az_id="az-uuid")
print(f"VM count in pool: {total}")
```

---

## Error Handling

```python
from sangfor_scp import (
    SCPError,
    SCPNotFoundError,
    SCPAuthError,
    SCPRateLimitError,
    SCPTaskError,
    SCPTimeoutError,
)

try:
    vm = client.servers.get("nonexistent-id")
except SCPNotFoundError:
    print("VM not found")

try:
    task = client.tasks.wait("task-uuid", timeout=60)
except SCPTaskError as e:
    print(f"Task failed: {e.message}")
    print(f"Task data: {e.task_data}")
except SCPTimeoutError as e:
    print(f"Timed out after {e.timeout}s")
```

---

## Requirements

- Python >= 3.8
- `requests >= 2.28.0`
- `urllib3 >= 1.26.0`
- `pycryptodome >= 3.17` *(only for Token-based auth)*

---

## SCP Version Compatibility

| SCP Version | Supported |
|---|---|
| 5.8.8R6+ | Basic APIs |
| 6.3.0+ | Full VM, Tenant, Network APIs |
| 6.3.70+ | AK/SK self-service, Tenant resource pool query |
| 6.8.0+ | Banner alerts, Email, G2H proxy, EIP APIs |
| 6.10.0+ | Extended host query APIs |
| 6.11.1+ | Latest API version (20240725) |

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the
development setup and guidelines. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md) and report security issues privately as
described in [SECURITY.md](SECURITY.md).

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Special Thanks

<div align="center">

![Onur Çılbır](https://raw.githubusercontent.com/erelbi/sangfor-scp/main/onurcilbir.png)

### 🏆 A Tribute to the Man Who Started It All

**Thank you, Onur Çılbır.**

Not every hero wears a cape. Some wear a smile while casually introducing their colleagues
to a 200-page Chinese cloud platform API specification and saying *"it shouldn't be that hard."*

Onur Çılbır is that hero. Or villain. The line is blurry at this point.

It was Onur who, with the enthusiasm of someone who clearly would not be doing the actual implementation,
introduced us to **Sangfor Cloud Platform** — a technology so full of surprises that we are still
finding new ones. AWS4-HMAC-SHA256 signatures, RSA-encrypted passwords, version-specific endpoints,
pagination quirks, and the eternal mystery of `next_page_num: ""` — none of this would have been
possible without his *generous* recommendation.

> *"It has an Open API, it'll be straightforward,"* — Onur Çılbır, allegedly.

Thanks to Onur, we now intimately understand what it means to spend an afternoon reading about
idempotency tokens, only to discover that the endpoint you need was added in *"SCP 6.3.70 and later."*
We have read more XML-era authentication documentation than any living person should.
We have emerged changed. Possibly for the worse.

**We did not ask for this. But here we are, and we shipped it anyway.**

*— The grateful (and slightly traumatized) survivors of this project*

</div>
