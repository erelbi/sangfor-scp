"""
Terraform tarzı VM kurulumu: spec dosyası → çalışan VM.

Kimlik bilgileri proje kökündeki .env dosyasından okunur
(bkz. examples/vm_create_test.py).

Kullanım:
    python examples/provision.py plan    examples/specs/web-01.yaml
    python examples/provision.py apply   examples/specs/web-01.yaml   # onay ister
    python examples/provision.py apply   examples/specs/web-01.yaml -y
    python examples/provision.py destroy examples/specs/web-01.yaml   # onay ister

Spec alanları için bkz. sangfor_scp/provision.py.
Parola spec'e yazılmak istenmezse SCP_VM_PASSWORD ortam değişkeni kullanılır.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sangfor_scp import SCPError  # noqa: E402
from vm_create_test import make_client  # noqa: E402


def load_spec(path: str) -> dict:
    text = Path(path).read_text()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            sys.exit("YAML spec için: pip install pyyaml (veya JSON kullanın)")
        spec = yaml.safe_load(text)
    else:
        spec = json.loads(text)
    if not spec.get("password") and os.environ.get("SCP_VM_PASSWORD"):
        spec["password"] = os.environ["SCP_VM_PASSWORD"]
    return spec


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{question} [yes/no]: ").strip().lower() == "yes"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["plan", "apply", "destroy"])
    parser.add_argument("spec", help="YAML veya JSON spec dosyası")
    parser.add_argument("-y", "--yes", action="store_true", help="Onay sorma")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--permanent", action="store_true",
                        help="destroy: geri dönüşüm kutusuna değil, kalıcı sil")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    client = make_client()
    prov = client.provisioner

    try:
        if args.command == "plan":
            print(prov.plan(spec).summary())

        elif args.command == "apply":
            plan = prov.plan(spec)
            print(plan.summary())
            if plan.action == "create" and not confirm("\nBu VM oluşturulsun mu?", args.yes):
                print("İptal edildi.")
                return
            vm = prov.apply(spec, timeout=args.timeout, on_event=print, plan=plan)
            ips = [n.get("ip_address") for n in vm.get("networks") or [] if n.get("ip_address")]
            print(f"\n[OK] {vm.get('name')} ({vm.get('id')}) status={vm.get('status')} ip={ips}")

        elif args.command == "destroy":
            if not confirm(f"'{spec.get('name')}' silinsin mi (diskleriyle birlikte)?", args.yes):
                print("İptal edildi.")
                return
            deleted = prov.destroy(spec, timeout=args.timeout, on_event=print, permanent=args.permanent)
            print("[OK] silindi" if deleted else "Silinecek VM yok.")

    except SCPError as exc:
        sys.exit(f"[HATA] {exc}")


if __name__ == "__main__":
    main()
