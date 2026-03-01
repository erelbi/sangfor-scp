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
| **Virtual Machines** | list, get, create, delete, power on/off/reboot |
| **Tasks** | get, wait (with timeout & progress callback) |
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

### Power Operations

```python
client.servers.power_off("vm-uuid")
client.servers.power_on("vm-uuid")
client.servers.reboot("vm-uuid")
client.servers.reboot("vm-uuid", force=True)   # force reboot
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

### Elastic IP

```python
# Allocate
eip = client.eips.allocate(az_id="az-uuid", bandwidth_mb=100)
eip_id = eip["id"]

# Bind to a VM
task_id = client.eips.bind(eip_id, server_id="vm-uuid")
client.tasks.wait(task_id)

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
