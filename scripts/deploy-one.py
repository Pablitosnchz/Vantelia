"""Sube un solo fichero local a Hostinger via FTP TLS.
Uso: python scripts/deploy-one.py <ruta_relativa_dentro_de_hostinger_site>
"""
from ftplib import FTP_TLS
from pathlib import Path
import sys

if len(sys.argv) < 2:
    print("Uso: python scripts/deploy-one.py <ruta_relativa>", file=sys.stderr)
    sys.exit(1)

REL = sys.argv[1].replace("\\", "/")
ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env.ftp"
LOCAL = ROOT / "hostinger_site" / REL

if not LOCAL.exists():
    print(f"No existe: {LOCAL}", file=sys.stderr)
    sys.exit(1)

config = {}
for line in ENV.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        config[k.strip()] = v.strip()

ftp = FTP_TLS()
ftp.connect(config["FTP_HOST"], int(config.get("FTP_PORT", 21)), timeout=30)
ftp.login(config["FTP_USER"], config["FTP_PASSWORD"])
ftp.prot_p()
ftp.cwd("/" + config.get("REMOTE_DIR", "public_html").strip("/"))

# ensure parent dirs
parts = REL.split("/")[:-1]
for i in range(1, len(parts) + 1):
    sub = "/".join(parts[:i])
    try: ftp.mkd(sub)
    except Exception: pass

with open(LOCAL, "rb") as f:
    ftp.storbinary(f"STOR {REL}", f)
print(f"[OK] {REL}")
ftp.quit()
