"""Kurulu paketin duman testi (build.sh test tarafından container içinde çalıştırılır)."""
import shutil
import subprocess

import sangfor_scp
from sangfor_scp.auth.token import encrypt_password

print("import ok", sangfor_scp.__version__)

try:
    from Crypto.PublicKey import RSA
except ImportError:
    from Cryptodome.PublicKey import RSA

modulus = format(RSA.generate(1024).n, "x")
print("rsa ok", len(encrypt_password("Test-123!", modulus)) == 256)

assert shutil.which("scp-health"), "scp-health komutu yok"
out = subprocess.run(["scp-health", "--help"], capture_output=True, text=True, check=True).stdout
print("cli ok", out.splitlines()[0])
