"""
Asenkron task yönetimi.

SCP'de VM oluşturma, silme, güç işlemleri gibi uzun süren
işlemler asenkron çalışır. API bir task_id döner; task durumu
ayrı bir endpoint ile sorgulanır.

Task status değerleri:
    waiting   → Kuyrukta (-2)
    doing     → Çalışıyor (0-99)
    finish    → Tamamlandı (100)
    failure   → Başarısız (-1)
    canceling → İptal ediliyor
    canceled  → İptal edildi
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from sangfor_scp.base import BaseResource
from sangfor_scp.exceptions import SCPTaskError, SCPTimeoutError

if TYPE_CHECKING:
    pass


class TasksResource(BaseResource):
    """
    GET /janus/20180725/tasks/{task_id}

    Kullanım:
        task = client.tasks.get("task-uuid")
        result = client.tasks.wait("task-uuid", timeout=300)
    """

    _BASE = "/janus/20180725/tasks"

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def get(self, task_id: str) -> dict:
        """
        Tek bir task'ın anlık durumunu döndürür.

        Returns:
            {
                "task_id": str,
                "status":  "finish" | "failure" | "doing" | "waiting" | ...,
                "progress": int,    # -2=waiting, -1=failure, 0-99=doing, 100=finish
                "action":  str,
                "object_type": str,
                "entities": {...},
                ...
            }
        """
        return self._get(f"{self._BASE}/{task_id}")

    def wait(
        self,
        task_id: str,
        timeout: int = 300,
        poll_interval: int = 3,
        progress_callback=None,
    ) -> dict:
        """
        Task tamamlanana kadar bekler (polling).

        Args:
            task_id:           İzlenecek task ID
            timeout:           Maksimum bekleme süresi (saniye, varsayılan 300)
            poll_interval:     Sorgular arası bekleme (saniye, varsayılan 3)
            progress_callback: Her poll'da çağrılacak fonksiyon f(task_data)

        Returns:
            status=="finish" olduğunda task dict'i döner.

        Raises:
            SCPTaskError:    Task başarısız sonuçlandı (status="failure")
            SCPTimeoutError: timeout süresi aşıldı
        """
        deadline = time.monotonic() + timeout
        last_data: Optional[dict] = None

        while time.monotonic() < deadline:
            task_data = self.get(task_id)
            last_data = task_data
            status = task_data.get("status", "")
            progress = task_data.get("progress", 0)

            if progress_callback is not None:
                try:
                    progress_callback(task_data)
                except Exception:
                    pass

            if status == "finish" or progress == 100:
                return task_data

            if status in ("failure",):
                description = task_data.get("description", "Task failed")
                raise SCPTaskError(
                    message=f"Task {task_id} failed: {description}",
                    task_id=task_id,
                    task_data=task_data,
                )

            if status in ("canceled", "canceling"):
                raise SCPTaskError(
                    message=f"Task {task_id} was canceled.",
                    task_id=task_id,
                    task_data=task_data,
                )

            time.sleep(poll_interval)

        raise SCPTimeoutError(
            message=(
                f"Task {task_id} did not complete within {timeout} seconds. "
                f"Last status: {last_data.get('status') if last_data else 'unknown'}"
            ),
            task_id=task_id,
            timeout=timeout,
        )

    def is_done(self, task_id: str) -> bool:
        """Task tamamlanmış mı? (finish veya failure)"""
        task = self.get(task_id)
        return task.get("status") in ("finish", "failure", "canceled")
