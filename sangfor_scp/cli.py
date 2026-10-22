"""
Komut satırı araçları.

    scp-health                       # özet rapor
    scp-health --cpu-scan --csv out/ # VM CPU tipleri dahil, CSV'ye yaz

Kimlik bilgileri ortam değişkenlerinden veya --env ile verilen dosyadan
(varsayılan: çalışma dizinindeki .env) okunur:

    SCP_HOST=https://10.x.x.x
    SCP_ACCESS_KEY=...          SCP_SECRET_KEY=...       (EC2 auth)
    SCP_USERNAME=...            SCP_PASSWORD=...         (Token auth)
    SCP_REGION=cn-south-1       (isteğe bağlı)
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


def load_env(path: str) -> None:
    """KEY=VALUE satırlarını os.environ'a ekler (var olanları ezmez)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def client_from_env():
    from sangfor_scp import SCPClient

    host = os.environ.get("SCP_HOST")
    if not host:
        sys.exit("SCP_HOST tanımlı değil (ortam değişkeni veya .env)")
    common = {"host": host, "region": os.environ.get("SCP_REGION", "cn-south-1")}
    if os.environ.get("SCP_ACCESS_KEY") and os.environ.get("SCP_SECRET_KEY"):
        return SCPClient(
            access_key=os.environ["SCP_ACCESS_KEY"],
            secret_key=os.environ["SCP_SECRET_KEY"],
            **common,
        )
    if os.environ.get("SCP_USERNAME") and os.environ.get("SCP_PASSWORD"):
        return SCPClient(
            username=os.environ["SCP_USERNAME"],
            password=os.environ["SCP_PASSWORD"],
            host=host,
        )
    sys.exit("SCP_ACCESS_KEY/SCP_SECRET_KEY veya SCP_USERNAME/SCP_PASSWORD gerekli")


def _safe_console() -> None:
    """Türkçe çıktı UTF-8 olmayan konsolda (ör. Windows cp1252'ye yönlendirme) çökmesin."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def health_main(argv: Optional[List[str]] = None) -> int:
    from sangfor_scp.health import collect, render_text, write_csv, write_json

    _safe_console()

    parser = argparse.ArgumentParser(
        prog="scp-health",
        description="SCP platform sağlık raporu (sadece okuma yapar).",
    )
    parser.add_argument("--days", type=int, default=30, help="task geçmişi gün sayısı (varsayılan 30)")
    parser.add_argument("--cpu-scan", action="store_true",
                        help="her HCI VM'in CPU tipini çek (VM başına 1 istek, yavaş)")
    parser.add_argument("--workers", type=int, default=4, help="--cpu-scan paralel istek sayısı (varsayılan 4)")
    parser.add_argument("--max-rps", type=float, default=8.0,
                        help="saniyedeki en fazla istek (API sınırı 10/sn, varsayılan 8)")
    parser.add_argument("--top", type=int, default=15, help="bölüm başına gösterilecek satır")
    parser.add_argument("--csv", metavar="DIZIN", help="CSV dosyalarını bu dizine yaz")
    parser.add_argument("--json", metavar="DOSYA", help="ham raporu JSON olarak yaz")
    parser.add_argument("--env", default=".env", help="kimlik bilgisi dosyası (varsayılan ./.env)")
    parser.add_argument("-q", "--quiet", action="store_true", help="ilerleme mesajlarını gizle")
    args = parser.parse_args(argv)

    load_env(args.env)
    client = client_from_env()

    def progress(msg: str) -> None:
        if not args.quiet:
            print(f"… {msg}", file=sys.stderr, flush=True)

    report = collect(
        client,
        days=args.days,
        cpu_scan=args.cpu_scan,
        workers=args.workers,
        max_rps=args.max_rps,
        progress=progress,
    )
    print(render_text(report, top=args.top))

    if args.csv:
        for path in write_csv(report, args.csv):
            print(f"yazıldı: {path}", file=sys.stderr)
    if args.json:
        write_json(report, args.json)
        print(f"yazıldı: {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(health_main())
