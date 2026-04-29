"""Sube /legal/* a Hostinger via FTP TLS, creando directorios anidados."""
from ftplib import FTP_TLS
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.ftp"

config = {}
for line in ENV.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        config[k.strip()] = v.strip()

HOST = config["FTP_HOST"]
USER = config["FTP_USER"]
PWD  = config["FTP_PASSWORD"]
PORT = int(config.get("FTP_PORT", 21))
REMOTE = config.get("REMOTE_DIR", "public_html").strip("/")

LEGAL_LOCAL = ROOT / "hostinger_site" / "legal"

ftp = FTP_TLS()
ftp.connect(HOST, PORT, timeout=30)
ftp.login(USER, PWD)
ftp.prot_p()
print(f"Conectado a {HOST} como {USER}")

ftp.cwd("/" + REMOTE)
print(f"En /{REMOTE}")


def ensure_dir(path):
    parts = path.strip("/").split("/")
    for i in range(1, len(parts) + 1):
        sub = "/".join(parts[:i])
        try:
            ftp.mkd(sub)
            print(f"  mkdir {sub}")
        except Exception as e:
            if "550" in str(e):
                pass  # exists
            else:
                raise


for slug_dir in sorted(LEGAL_LOCAL.iterdir()):
    if not slug_dir.is_dir():
        continue
    slug = slug_dir.name
    ensure_dir(f"legal/{slug}")
    src = slug_dir / "index.html"
    if not src.exists():
        continue
    remote_path = f"legal/{slug}/index.html"
    with open(src, "rb") as f:
        ftp.storbinary(f"STOR {remote_path}", f)
    print(f"  [OK] {remote_path}")

ftp.quit()
print("Hecho.")
