"""
sangfor_scp — Sangfor Cloud Platform (SCP) Python API Kütüphanesi

Hızlı başlangıç:

    from sangfor_scp import SCPClient

    # EC2 Auth (önerilen)
    client = SCPClient(
        host="10.x.x.x",
        access_key="YOUR_AK",
        secret_key="YOUR_SK",
        region="cn-south-1",
        verify_ssl=False,
    )

    # Token Auth
    client = SCPClient(
        host="10.x.x.x",
        username="admin",
        password="your_password",
        verify_ssl=False,
    )

    # VM listesi
    for vm in client.servers.list_all():
        print(vm["id"], vm["name"])

    # VM oluştur ve bekle
    result = client.servers.create(
        az_id="...", image_id="...", storage_tag_id="...",
        cores=2, memory_mb=2048, name="test-vm",
        networks=[{"vif_id": "net0", "vpc_id": "...", "subnet_id": "..."}],
    )
    client.tasks.wait(result["task_id"], timeout=300)
"""

from sangfor_scp.client import SCPClient
from sangfor_scp.exceptions import (
    SCPError,
    SCPAuthError,
    SCPForbiddenError,
    SCPNotFoundError,
    SCPConflictError,
    SCPRateLimitError,
    SCPBadRequestError,
    SCPServerError,
    SCPTaskError,
    SCPTimeoutError,
)

__version__ = "0.1.4"
__author__ = "Sangfor SCP API Library"

__all__ = [
    "SCPClient",
    # Exceptions
    "SCPError",
    "SCPAuthError",
    "SCPForbiddenError",
    "SCPNotFoundError",
    "SCPConflictError",
    "SCPRateLimitError",
    "SCPBadRequestError",
    "SCPServerError",
    "SCPTaskError",
    "SCPTimeoutError",
]
