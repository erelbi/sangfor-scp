"""
Bildirimsel (Terraform tarzı) VM kurulumu.

Makinenin tüm özellikleri tek bir spec ile verilir; isimler ID'lere
çözülür, ön kontroller yapılır, VM oluşturulup çalışır duruma getirilir.

    spec = {
        "name": "web-01",
        "resource_pool": "POOL-A",                 # ad veya ID
        "image": "ubuntu-2404-template",                      # ad veya ID
        "storage_tag": "High Performance Storage",   # ad veya ID (varsayılan: ilk tag)
        "cores": 2, "sockets": 1,
        "memory_gb": 4,                              # veya memory_mb
        "disks": [{"size_gb": 150}, {"size_gb": 50}],  # ilki sistem diski
        "networks": [{
            "switch": "edge-switch-1", "vlan": "vlan100",   # klasik ağ
            "ip": "192.168.100.50", "netmask": "255.255.255.0",
            "gateway": "192.168.100.1", "dns": ["8.8.8.8"],
        }],
        "hostname": "web-01",
        "password": "...",                           # otomatik RSA şifrelenir
        "description": "",
        "power_on": True,
        # isteğe bağlı donanım ayarları (SCP 6.8.80+, 20210725 API):
        "bios": "SEABIOS",                           # SEABIOS | UEFI
        "graphic_type": "qxl",                       # qxl | std | vmware | cirrus
        "derive_mode": "full",                       # full (tam kopya) | fast (bağlı klon)
    }

    prov = client.provisioner
    plan = prov.plan(spec)      # hiçbir şey değiştirmez
    print(plan.summary())
    vm = prov.apply(spec)       # oluştur → bekle → çalıştır
    prov.destroy(spec)          # sil

VM şablonundan klonlama: "image" yerine "source_vm": "<şablon VM adı/ID>"
verilir; VM klonlanır (clone_type: full|fast|link), kapalıyken CPU/RAM
düzenlenir, açılır ve parola vmtools ile ayarlanır. Disk/BIOS kaynak VM'den gelir.

VPC ortamında NIC: {"vpc": "vpc-adı", "subnet": "subnet-adı", "ip": "..."}.
Hiç NIC istenmiyorsa "networks": [].

Not: hostname / password / IP enjeksiyonu için imajın aCloud şablonu olması
ve içinde vmtools kurulu olması gerekir. ISO imajdan oluşturulan VM işletim
sistemi kurulumunu konsoldan bekler.
"""
from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from sangfor_scp.exceptions import SCPError, SCPTimeoutError

if TYPE_CHECKING:
    from sangfor_scp.client import SCPClient


class SpecError(SCPError):
    """Spec geçersiz veya ortamla uyuşmuyor (plan aşamasında yakalanır)."""

    def __init__(self, message: str):
        super().__init__(message=message)


@dataclass
class Plan:
    """plan() sonucu: ne yapılacağı ve oluşturma isteğinin gövdesi."""

    action: str                       # "create" | "no-op" | "drift"
    name: str
    body: Dict[str, Any] = field(default_factory=dict)
    existing: Optional[Dict[str, Any]] = None
    diff: Dict[str, Any] = field(default_factory=dict)
    resolved: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    mode: str = "image"               # "image" (imajdan oluştur) | "clone" (VM şablonundan klonla)
    post: Dict[str, Any] = field(default_factory=dict)   # klon sonrası: cores, sockets, memory_mb

    def summary(self) -> str:
        lines = [f"{self.name}: {self.action}"]
        for key, value in self.resolved.items():
            lines.append(f"  {key:<14} {value}")
        if self.body:
            b = {**self.body, **self.post}
            lines.append(f"  {'cpu':<14} {b['cores']} core / {b['sockets']} socket")
            lines.append(f"  {'memory':<14} {b['memory_mb']} MB")
            for d in b.get("disks", []):
                lines.append(f"  {'disk ' + d['id']:<14} {d['size_mb'] // 1024} GB ({d['type']})")
            if not b.get("networks"):
                lines.append(f"  {'nic':<14} (yok)")
            lines.append(f"  {'power_on':<14} {bool(b.get('_power_on', b.get('power_on')))}")
        for key, (want, have) in self.diff.items():
            lines.append(f"  ~ {key}: {have} → {want} (otomatik güncellenmez)")
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return "\n".join(lines)


class Provisioner:
    """Spec tabanlı VM kurulumu. client.provisioner üzerinden kullanılır."""

    def __init__(self, client: "SCPClient"):
        self._client = client

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def plan(self, spec: Dict[str, Any]) -> Plan:
        """Spec'i çözer ve doğrular. Ortamda hiçbir değişiklik yapmaz."""
        name = self._require(spec, "name")
        az = self._resolve_pool(self._require(spec, "resource_pool"))
        az_id = az["id"]

        existing = self._find_vm(name, az_id)
        if existing:
            plan = Plan(action="no-op", name=name, existing=existing,
                        resolved={"resource_pool": f"{az.get('name')} ({az_id})",
                                  "vm": existing["id"]})
            plan.diff = self._diff(spec, existing)
            if plan.diff:
                plan.action = "drift"
            return plan

        if spec.get("source_vm"):
            return self._plan_clone(spec, name, az)

        image = self._resolve_image(self._require(spec, "image"), az_id)
        tag = self._resolve_storage_tag(spec.get("storage_tag"), az_id)
        cores = int(spec.get("cores", 1))
        sockets = int(spec.get("sockets", 1))
        if cores < sockets:
            raise SpecError("cores, sockets değerinden küçük olamaz (cores toplam çekirdek sayısıdır)")

        plan = Plan(action="create", name=name, resolved={
            "resource_pool": f"{az.get('name')} ({az_id})",
            "image": f"{image.get('name')} ({image['id']}, {image.get('disk_format')})",
            "storage_tag": f"{tag.get('name')} ({tag['id']})",
        })

        if image.get("disk_format") == "ISO":
            plan.warnings.append("ISO imaj: işletim sistemi kurulumu konsoldan yapılmalı; "
                                 "hostname/password/IP enjekte edilmez")

        networks = self._build_networks(spec.get("networks", []), az_id, plan)

        body: Dict[str, Any] = {
            "az_id": az_id,
            "image_id": image["id"],
            "storage_tag_id": tag["id"],
            "name": name,
            "description": spec.get("description", ""),
            "cores": cores,
            "sockets": sockets,
            "memory_mb": self._memory_mb(spec),
            "disks": self._build_disks(spec.get("disks"), image),
            "networks": networks,
            "power_on": 1 if spec.get("power_on", True) else 0,
            "location": {"id": spec.get("location", "cluster")},
            "count": 1,
        }
        for key in ("hostname", "project_id", "user_id", "group_id", "lifespan", "dh_id"):
            if spec.get(key):
                body[key] = spec[key]
        advance = self._advance_param(spec, image)
        if advance:
            body["advance_param"] = advance
        if spec.get("derive_mode"):
            if spec["derive_mode"] not in ("full", "fast"):
                raise SpecError("derive_mode: full veya fast olmalı")
            body["derive_mode"] = spec["derive_mode"]
        if any(spec.get(k) for k in ("bios", "graphic_type", "derive_mode")):
            body["api_version"] = "20210725"
        if spec.get("bios"):
            plan.resolved["bios"] = advance["bios"]["bios_type"]
        if spec.get("graphic_type"):
            plan.resolved["graphic_type"] = spec["graphic_type"]
        if spec.get("derive_mode"):
            plan.resolved["derive_mode"] = spec["derive_mode"]
        if spec.get("password"):
            self._check_password(spec["password"])
            body["password"] = self._encrypt(spec["password"])
        plan.body = body
        return plan

    def _plan_clone(self, spec: Dict[str, Any], name: str, az: Dict[str, Any]) -> Plan:
        """source_vm (VM şablonu) klonlama planı."""
        az_id = az["id"]
        ref = spec["source_vm"]
        source = self._client.servers.find_by_name(ref, az_id=az_id)
        if source is None:
            try:
                source = self._client.servers.get(ref)
            except SCPError:
                source = None
        if not source or source.get("az_id") not in (None, az_id):
            raise SpecError(f"kaynak VM bu resource pool'da bulunamadı: '{ref}'")

        cores = int(spec.get("cores", source.get("cores") or 1))
        sockets = int(spec.get("sockets", source.get("sockets") or 1))
        if cores < sockets:
            raise SpecError("cores, sockets değerinden küçük olamaz (cores toplam çekirdek sayısıdır)")
        memory_mb = self._memory_mb(spec) if (spec.get("memory_mb") or spec.get("memory_gb")) \
            else int(source.get("memory_mb") or 1024)

        clone_type = spec.get("clone_type", "full")
        if clone_type not in ("full", "fast", "link"):
            raise SpecError("clone_type: full, fast veya link olmalı")

        plan = Plan(action="create", name=name, mode="clone", resolved={
            "resource_pool": f"{az.get('name')} ({az_id})",
            "source_vm": f"{source.get('name')} ({source['id']})",
            "clone_type": clone_type,
        })
        body: Dict[str, Any] = {
            "server_id": source["id"],
            "name": name,
            "description": spec.get("description", ""),
            "power_on": False,          # önce CPU/RAM düzenlenir, sonra açılır
            "clone_type": clone_type,
            "networks": self._build_networks(spec.get("networks", []), az_id, plan),
        }
        if spec.get("storage_tag"):
            tag = self._resolve_storage_tag(spec["storage_tag"], az_id)
            body["storage_tag_id"] = tag["id"]
            plan.resolved["storage_tag"] = f"{tag.get('name')} ({tag['id']})"
        plan.body = body
        plan.post = {"cores": cores, "sockets": sockets, "memory_mb": memory_mb,
                     "_power_on": bool(spec.get("power_on", True)),
                     "_source": {k: source.get(k) for k in ("cores", "sockets", "memory_mb")}}

        if spec.get("password"):
            self._check_password(spec["password"])
        for key in ("disks", "hostname", "bios", "graphic_type", "derive_mode"):
            if spec.get(key):
                plan.warnings.append(f"klon modunda '{key}' uygulanmaz (kaynak VM'den gelir)")
        return plan

    def apply(
        self,
        spec: Dict[str, Any],
        timeout: int = 1800,
        on_event: Optional[Callable[[str], None]] = None,
        plan: Optional[Plan] = None,
        wait_for_ip: bool = True,
    ) -> Dict[str, Any]:
        """
        Spec'teki VM'i oluşturur ve hazır olana kadar bekler.
        VM zaten varsa yeniden oluşturmaz, mevcut VM'i döndürür.

        Args:
            plan:        Önceden hesaplanmış plan (verilmezse plan() çağrılır)
            wait_for_ip: VM açıldıktan sonra vmtools'un spec'teki IP'leri
                         raporlamasını bekle (işletim sistemi hazır sinyali)

        Returns:
            servers.get() çıktısı
        """
        log = on_event or (lambda msg: None)
        if plan is None:
            plan = self.plan(spec)
            log(plan.summary())
        deadline = time.monotonic() + timeout
        if plan.action != "create":
            # Yarıda kalmış bir apply'ı tamamla (Terraform gibi yakınsa)
            return self._converge(plan.existing["id"], spec, deadline, log)

        if plan.mode == "clone":
            result = self._client.servers.clone_v2(**plan.body)
        else:
            result = self._client.servers.create(**self._create_kwargs(plan.body))
        vm_id = (result.get("uuids") or [result.get("uuid")])[0]
        task_id = result.get("task_id")
        log(f"{'klonlanıyor' if plan.mode == 'clone' else 'oluşturuluyor'}: vm={vm_id} task={task_id}")

        if task_id:
            self._client.tasks.wait(
                task_id,
                timeout=max(1, int(deadline - time.monotonic())),
                progress_callback=lambda t: log(f"  task {t.get('status')} %{t.get('progress')}"),
            )
        if not vm_id:
            found = self._find_vm(plan.name, self._resolve_pool(spec["resource_pool"])["id"])
            vm_id = found and found["id"]
            if not vm_id:
                raise SCPError(message=f"oluşturulan VM bulunamadı: {plan.name}")

        if plan.mode == "clone":
            self._apply_post_clone(vm_id, plan, deadline, log)

        vm = self._converge(vm_id, spec, deadline, log, wait_for_ip)

        if plan.mode == "clone" and spec.get("password"):
            log("parola ayarlanıyor (vmtools)")
            pw_task = self._client.servers.set_password(vm_id, spec["password"])
            if pw_task:
                self._client.tasks.wait(pw_task, timeout=max(1, int(deadline - time.monotonic())))
        return vm

    def _apply_post_clone(self, vm_id: str, plan: Plan, deadline: float, log: Callable[[str], None]) -> None:
        """Klon kapalıyken CPU/RAM'i spec'e göre düzenler."""
        source = plan.post["_source"]
        changes = {k: plan.post[k] for k in ("cores", "sockets", "memory_mb")
                   if plan.post[k] != source.get(k)}
        if not changes:
            return
        log(f"donanım düzenleniyor: {changes}")
        task_id = self._client.servers.update(vm_id, **changes)
        if task_id:
            self._client.tasks.wait(task_id, timeout=max(1, int(deadline - time.monotonic())))

    _TRANSIENT = ("creating", "cloning", "starting", "rebooting", "updating", "migrating")

    def _converge(
        self,
        vm_id: str,
        spec: Dict[str, Any],
        deadline: float,
        log: Callable[[str], None],
        wait_for_ip: bool = True,
    ) -> Dict[str, Any]:
        """VM'i spec'teki güç durumuna getirir; geçiş durumlarını bekler."""
        vm = self._client.servers.get(vm_id)
        while vm.get("status") in self._TRANSIENT:
            if time.monotonic() > deadline:
                raise SCPTimeoutError(message=f"VM {vm_id} '{vm.get('status')}' durumundan çıkmadı")
            log(f"  durum: {vm.get('status')}")
            time.sleep(10)
            vm = self._client.servers.get(vm_id)

        if spec.get("power_on", True):
            if vm.get("status") != "running":
                log("açılıyor")
                start_task = self._client.servers.start(vm_id)
                if start_task:
                    self._client.tasks.wait(start_task, timeout=max(1, int(deadline - time.monotonic())))
            self._wait_status(vm_id, "running", deadline, log)
            want_ips = [n["ip"] for n in spec.get("networks") or []
                        if n.get("ip") and n.get("connect", True)]
            if want_ips and wait_for_ip:
                self._wait_ips(vm_id, want_ips, deadline, log)

        vm = self._client.servers.get(vm_id)
        log(f"hazır: {vm.get('name')} status={vm.get('status')}")
        return vm

    def destroy(
        self,
        spec: Dict[str, Any],
        timeout: int = 900,
        on_event: Optional[Callable[[str], None]] = None,
        permanent: bool = False,
    ) -> bool:
        """
        Spec'teki VM'i (ad + resource pool ile bulup) siler. Silindiyse True.
        permanent=False → geri dönüşüm kutusu, True → kalıcı silme.
        """
        log = on_event or (lambda msg: None)
        az = self._resolve_pool(self._require(spec, "resource_pool"))
        vm = self._find_vm(self._require(spec, "name"), az["id"])
        if not vm:
            log("VM bulunamadı, silinecek bir şey yok")
            return False
        if vm.get("status") == "running":
            log("kapatılıyor")
            stop_task = self._client.servers.stop(vm["id"], force=True)
            if stop_task:
                self._client.tasks.wait(stop_task, timeout=timeout)
        log(f"siliniyor: {vm['id']}")
        task_id = self._client.servers.delete(vm["id"], permanent=permanent)
        if task_id:
            self._client.tasks.wait(task_id, timeout=timeout)
        return True

    # ------------------------------------------------------------------ #
    # Çözümleme                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _require(spec: Dict[str, Any], key: str) -> Any:
        if spec.get(key) in (None, ""):
            raise SpecError(f"spec içinde '{key}' zorunlu")
        return spec[key]

    @staticmethod
    def _match(items: List[Dict[str, Any]], ref: str, kind: str) -> Dict[str, Any]:
        hits = [i for i in items if ref in (i.get("id"), i.get("name"))]
        if not hits:
            names = ", ".join(sorted(str(i.get("name")) for i in items)[:15])
            raise SpecError(f"{kind} bulunamadı: '{ref}'. Mevcut: {names}")
        if len(hits) > 1:
            raise SpecError(f"{kind} adı birden fazla eşleşti: '{ref}' — ID kullanın")
        return hits[0]

    def _resolve_pool(self, ref: str) -> Dict[str, Any]:
        return self._match(self._client.resource_pools.list(), ref, "resource pool")

    def _resolve_image(self, ref: str, az_id: str) -> Dict[str, Any]:
        images = [i for i in self._client.images.list() if ref in (i.get("id"), i.get("name"))]
        image = self._match(images or self._client.images.list(), ref, "imaj")
        if image.get("status") != "active":
            raise SpecError(f"imaj aktif değil: {image.get('name')} status={image.get('status')}")
        azs = [a.get("id") if isinstance(a, dict) else a for a in (image.get("azs") or [])]
        if azs and az_id not in azs:
            raise SpecError(f"imaj bu resource pool'da kullanılamıyor: {image.get('name')}")
        return image

    def _resolve_storage_tag(self, ref: Optional[str], az_id: str) -> Dict[str, Any]:
        tags = self._client.resource_pools.storage_tags(az_id)
        if not tags:
            raise SpecError("resource pool'da storage tag yok")
        return self._match(tags, ref, "storage tag") if ref else tags[0]

    def _find_vm(self, name: str, az_id: str) -> Optional[Dict[str, Any]]:
        return self._client.servers.find_by_name(name, az_id=az_id)

    # ------------------------------------------------------------------ #
    # Gövde oluşturma                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _advance_param(spec: Dict[str, Any], image: Dict[str, Any]) -> Dict[str, Any]:
        """Şablonun tpl_config'i + spec'teki donanım ayarları + serbest advance_param."""
        advance: Dict[str, Any] = {}
        template = (image.get("disks") or [{}])[0].get("tpl_config") or {}
        for key in ("cpu_hotplug", "mem_hotplug"):
            if key in template:
                advance[key] = template[key]
        if spec.get("bios"):
            bios_type = str(spec["bios"]).upper()
            if bios_type not in ("SEABIOS", "UEFI"):
                raise SpecError("bios: SEABIOS veya UEFI olmalı")
            advance["bios"] = {"bios_type": bios_type, "boot_delay_seconds": 0}
        if spec.get("graphic_type"):
            advance["graphic_type"] = spec["graphic_type"]
        advance.update(spec.get("advance_param") or {})
        return advance

    @staticmethod
    def _memory_mb(spec: Dict[str, Any]) -> int:
        if spec.get("memory_mb"):
            return int(spec["memory_mb"])
        return int(float(spec.get("memory_gb", 1)) * 1024)

    @staticmethod
    def _size_mb(disk: Dict[str, Any]) -> int:
        if disk.get("size_mb"):
            return int(disk["size_mb"])
        if disk.get("size_gb"):
            return int(float(disk["size_gb"]) * 1024)
        raise SpecError("her disk için size_gb veya size_mb zorunlu")

    def _build_disks(self, disks: Optional[List[Dict[str, Any]]], image: Dict[str, Any]) -> List[Dict[str, Any]]:
        template = image.get("disks") or []
        is_template = image.get("disk_format") != "ISO" and bool(template)
        disks = list(disks or [])
        result: List[Dict[str, Any]] = []

        if is_template:
            # Şablonun sistem diski türetilir; istenen boyut şablondan küçük olamaz
            base = template[0]
            base_mb = int(base.get("size_mb", 0))
            want_mb = self._size_mb(disks[0]) if disks else base_mb
            if want_mb < base_mb:
                raise SpecError(f"sistem diski şablondan küçük olamaz: {want_mb // 1024} GB < {base_mb // 1024} GB")
            result.append({"id": base.get("id", "ide0"), "type": "derive_disk",
                           "size_mb": want_mb, "preallocate": disks[0].get("preallocate", "off") if disks else "off"})
            extra = disks[1:]
        else:
            if not disks:
                raise SpecError("ISO imaj için en az bir disk (size_gb) gerekli")
            extra = disks

        used = {d["id"] for d in result}
        slots = (f"ide{i}" for i in range(16))
        for disk in extra:
            disk_id = disk.get("id") or next(s for s in slots if s not in used)
            used.add(disk_id)
            result.append({"id": disk_id, "type": "new_disk", "size_mb": self._size_mb(disk),
                           "preallocate": disk.get("preallocate", "off")})
        return result

    def _build_networks(self, nics: List[Dict[str, Any]], az_id: str, plan: Plan) -> List[Dict[str, Any]]:
        if not nics:
            return []
        used_ips = self._used_ips(az_id)
        result = []
        for index, nic in enumerate(nics):
            vif_id = nic.get("vif_id", f"net{index}")
            ip = nic.get("ip")
            if ip:
                ipaddress.ip_address(ip)
                if ip in used_ips:
                    raise SpecError(f"IP kullanımda: {ip} → {used_ips[ip]}")

            if nic.get("vlan"):
                result.append(self._classic_nic(nic, vif_id, az_id, plan))
            elif nic.get("vpc"):
                result.append(self._vpc_nic(nic, vif_id, az_id, plan))
            else:
                raise SpecError(f"{vif_id}: 'vlan' (klasik ağ) veya 'vpc' (VPC) belirtilmeli")
        return result

    def _classic_nic(self, nic: Dict[str, Any], vif_id: str, az_id: str, plan: Plan) -> Dict[str, Any]:
        if not nic.get("ip"):
            raise SpecError(f"{vif_id}: klasik ağda 'ip' zorunlu (SCP port_id + ip_info ister)")
        switches = list(self._client.networks.list_classic_switches(az_id=az_id))
        switches = [s for s in switches if s.get("az_id") in (None, az_id)]
        if nic.get("switch"):
            switch = self._match(switches, nic["switch"], "klasik switch")
        elif len(switches) == 1:
            switch = switches[0]
        else:
            raise SpecError(f"{vif_id}: birden fazla switch var, 'switch' belirtin")
        group = self._match(switch.get("vlan_group") or [], nic["vlan"], f"VLAN ({switch.get('name')})")
        plan.resolved[f"nic {vif_id}"] = f"{switch.get('name')}/{group.get('name')} → {nic['ip']}"
        out = self._client.networks.classic_nic(
            switch_id=switch["id"], vlan_group_id=group["id"], ip_address=nic["ip"],
            netmask=nic.get("netmask"), gateway=nic.get("gateway"), dns=nic.get("dns"),
            vif_id=vif_id, model=nic.get("model", "virtio"), connect=nic.get("connect", True),
        )
        return out

    def _vpc_nic(self, nic: Dict[str, Any], vif_id: str, az_id: str, plan: Plan) -> Dict[str, Any]:
        vpc = self._match(list(self._client.networks.list_vpcs(az_id=az_id)), nic["vpc"], "VPC")
        subnet = self._match(list(self._client.networks.list_subnets(vpc_id=vpc["id"])),
                             self._require(nic, "subnet"), "subnet")
        plan.resolved[f"nic {vif_id}"] = f"{vpc.get('name')}/{subnet.get('name')} → {nic.get('ip', 'DHCP')}"
        out: Dict[str, Any] = {"vif_id": vif_id, "connect": 1 if nic.get("connect", True) else 0,
                               "vpc_id": vpc["id"], "subnet_id": subnet["id"],
                               "model": nic.get("model", "virtio")}
        if nic.get("ip"):
            out["ip_info"] = {"ip_address": nic["ip"]}
        return out

    def _used_ips(self, az_id: str) -> Dict[str, str]:
        used: Dict[str, str] = {}
        for vm in self._client.servers.list_all(az_id=az_id):
            for net in vm.get("networks") or []:
                if net.get("ip_address"):
                    used[net["ip_address"]] = vm.get("name", vm.get("id"))
            for ip in vm.get("ips") or []:
                if isinstance(ip, str):
                    used.setdefault(ip, vm.get("name", vm.get("id")))
        return used

    _PASSWORD_SPECIALS = set("()`~!@#$%^&*_-+=|{}[]:;'<>,.?/")

    @classmethod
    def _check_password(cls, password: str) -> None:
        """SCP parola politikası: büyük + küçük harf + rakam + özel karakter."""
        checks = [
            any(ch.isupper() for ch in password),
            any(ch.islower() for ch in password),
            any(ch.isdigit() for ch in password),
            any(ch in cls._PASSWORD_SPECIALS for ch in password),
        ]
        if not all(checks):
            raise SpecError("parola büyük harf, küçük harf, rakam ve özel karakter "
                            "(ör. !@#$%) içermeli — SCP politikası")

    def _encrypt(self, password: str) -> str:
        from sangfor_scp.auth.token import encrypt_password, fetch_public_key_modulus

        modulus = fetch_public_key_modulus(self._client.host, self._client.verify_ssl)
        return encrypt_password(password, modulus)

    @staticmethod
    def _create_kwargs(body: Dict[str, Any]) -> Dict[str, Any]:
        kwargs = dict(body)
        kwargs["power_on"] = bool(kwargs.pop("power_on"))
        kwargs["location"] = kwargs.pop("location")
        return kwargs

    def _diff(self, spec: Dict[str, Any], vm: Dict[str, Any]) -> Dict[str, Any]:
        diff: Dict[str, Any] = {}
        want: Dict[str, Any] = {}
        if spec.get("cores") or not spec.get("source_vm"):
            want["cores"] = int(spec.get("cores", 1))
        if spec.get("memory_mb") or spec.get("memory_gb") or not spec.get("source_vm"):
            want["memory_mb"] = self._memory_mb(spec)
        for key, value in want.items():
            if vm.get(key) not in (None, value):
                diff[key] = (value, vm.get(key))
        want_power = "running" if spec.get("power_on", True) else "stopped"
        if vm.get("status") in ("running", "stopped") and vm.get("status") != want_power:
            diff["status"] = (want_power, vm.get("status"))
        return diff

    def _wait_status(self, vm_id: str, status: str, deadline: float, log: Callable[[str], None]) -> None:
        while True:
            vm = self._get_quiet(vm_id)
            if vm.get("status") == status:
                return
            if time.monotonic() > deadline:
                raise SCPTimeoutError(message=f"VM {vm_id} '{status}' durumuna gelmedi (son: {vm.get('status')})")
            log(f"  durum: {vm.get('status')}")
            time.sleep(5)

    def _wait_ips(self, vm_id: str, ips: List[str], deadline: float, log: Callable[[str], None]) -> None:
        log(f"vmtools IP raporu bekleniyor: {', '.join(ips)}")
        while True:
            vm = self._get_quiet(vm_id)
            have = {n.get("ip_address") for n in vm.get("networks") or []}
            if set(ips) <= have:
                return
            if time.monotonic() > deadline:
                raise SCPTimeoutError(message=f"VM {vm_id} IP'leri raporlamadı: {ips} (vmtools çalışıyor mu?)")
            time.sleep(10)

    def _get_quiet(self, vm_id: str) -> Dict[str, Any]:
        """servers.get(); geçici ağ hatasında boş dict döner (polling döngüleri için)."""
        import requests

        try:
            return self._client.servers.get(vm_id)
        except (requests.ConnectionError, requests.Timeout):
            return {}
