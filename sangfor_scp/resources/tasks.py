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

Kapsanan endpoint'ler:
  - GET /janus/20180725/tasks/{task_id} → Tek task durumu
  - GET /janus/20180725/tasks           → Task (operasyon) geçmişi, sayfalı
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional

import requests

from sangfor_scp.base import PaginatedResource
from sangfor_scp.exceptions import SCPServerError, SCPTaskError, SCPTimeoutError

if TYPE_CHECKING:
    pass


_TIME_FMT = "%Y-%m-%d %H:%M:%S"


class TasksResource(PaginatedResource):
    """
    Task durumu ve operasyon geçmişi.

    Kullanım:
        task = client.tasks.get("task-uuid")
        result = client.tasks.wait("task-uuid", timeout=300)

        # Son 30 günün başarısız task'ları (tüm kullanıcılar)
        for t in client.tasks.list_failed(days=30):
            print(t["begin_time"], t["action"], t["description"])

        # Bir VM'in geçmişi
        client.tasks.list(object_id="vm-uuid")
    """

    _BASE = "/janus/20180725/tasks"

    # ------------------------------------------------------------------ #
    # Liste                                                               #
    # ------------------------------------------------------------------ #

    def _list_page(
        self,
        page_num: int,
        page_size: int,
        **filters: Any,
    ) -> Dict[str, Any]:
        """
        Filtreler:
            status:      waiting | doing | finish | failure | canceling | canceled
            object_id:   İşlem yapılan nesne ID
            object_type: Nesne tipi
            az_id, project_id, user_id, user_ip
            begin_time / end_time: "YYYY-MM-DD HH:MM:SS"
        """
        params = {
            "page_num": page_num,
            "page_size": page_size,
            **{k: v for k, v in filters.items() if v is not None},
        }
        return self._get(self._BASE, params=params)

    def list(self, **filters: Any) -> List[Dict[str, Any]]:
        """Filtreye uyan tüm task'ları liste olarak döndürür (yeniden eskiye)."""
        return list(self.list_all(**filters))

    def list_since(self, days: float = 30, **filters: Any) -> Iterator[Dict[str, Any]]:
        """Son N gündeki task'ları iterate eder."""
        now = datetime.now()
        filters.setdefault("begin_time", (now - timedelta(days=days)).strftime(_TIME_FMT))
        filters.setdefault("end_time", now.strftime(_TIME_FMT))
        return self.list_all(**filters)

    def list_failed(self, days: float = 30, **filters: Any) -> List[Dict[str, Any]]:
        """Son N gündeki başarısız (status=failure) task'lar."""
        return list(self.list_since(days, status="failure", **filters))

    # ------------------------------------------------------------------ #
    # Tek task                                                            #
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
            try:
                task_data = self.get(task_id)
            except (requests.ConnectionError, requests.Timeout, SCPServerError):
                # Geçici ağ/sunucu hatası — task sunucuda sürüyor, tekrar dene
                time.sleep(poll_interval)
                continue
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
