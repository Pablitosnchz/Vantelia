"""One-off: marca un cliente como demo_claimable=true en el config.json indicado.

Uso (en el VPS): python3 _set_demo_claimable.py /srv/vantelia/config.json mgclinic
Hace backup con timestamp, valida el JSON antes de reemplazar y es idempotente.
"""
import json
import os
import shutil
import sys
from datetime import datetime


def main() -> int:
    if len(sys.argv) != 3:
        print("uso: _set_demo_claimable.py <config.json> <cliente_id>", file=sys.stderr)
        return 2
    path, cid = sys.argv[1], sys.argv[2]
    if not os.path.exists(path):
        print(f"ERROR: no existe {path}", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if cid not in cfg:
        print(f"ERROR: '{cid}' no esta en config; claves: {list(cfg.keys())}", file=sys.stderr)
        return 3
    bak = f"{path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(path, bak)
    already = bool(cfg[cid].get("demo_claimable"))
    cfg[cid]["demo_claimable"] = True
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    with open(tmp, encoding="utf-8") as f:
        json.load(f)  # valida
    os.replace(tmp, path)
    print(f"OK demo_claimable=true en '{cid}' (antes={already}) | backup: {bak}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
