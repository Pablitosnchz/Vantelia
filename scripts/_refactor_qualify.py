"""Herramienta interna del refactor F3 — se elimina al cerrar la fase.

Reescribe referencias a simbolos movidos a backend/<mod>.py por acceso
cualificado: `simbolo` -> `mod.simbolo`. Trabaja sobre tokens (no toca
strings ni comentarios), con soporte best-effort para f-strings.

Uso:
    python scripts/_refactor_qualify.py <archivo.py> mapa.json [--write]
    python scripts/_refactor_qualify.py --selftest

`mapa.json`: {"_utc_now": "timeutils", "DB_PATH": "settings", ...}

Reglas:
- No reescribe atributos (`obj.simbolo`), nombres de def/class, kwargs
  (`f(simbolo=...)`) ni nombres dentro de sentencias import.
- Dentro de f-strings reescribe solo dentro de campos `{...}` no anidados.
- Si encuentra `global SIMBOLO` o `del SIMBOLO` para un simbolo mapeado,
  ABORTA con error: esos sitios se tratan a mano.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tokenize
from typing import Dict, List, Tuple


def _rewrite_fstring(tok_string: str, mapping: Dict[str, str]) -> str:
    """Reescribe nombres mapeados dentro de campos {..} de un f-string."""

    def repl_field(match: re.Match) -> str:
        inner = match.group(1)
        for name, mod in mapping.items():
            inner = re.sub(rf"(?<![\w.]){re.escape(name)}\b", f"{mod}.{name}", inner)
        return "{" + inner + "}"

    # Campos simples sin llaves anidadas; '{{' literal queda intacto.
    return re.sub(r"\{([^{}\n]+)\}", repl_field, tok_string)


def qualify_source(source: str, mapping: Dict[str, str]) -> Tuple[str, int]:
    """Devuelve (codigo_reescrito, num_reemplazos)."""
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    out: List[tokenize.TokenInfo] = []
    count = 0
    # Estado para saltar lineas logicas de import
    in_import = False
    prev_sig = None  # token significativo anterior (NAME/OP), ignora NL/comentarios

    for i, tok in enumerate(tokens):
        ttype, tstring, start, end, line = tok

        if ttype == tokenize.NAME and tstring in ("import", "from"):
            in_import = True
        if ttype == tokenize.NEWLINE:
            in_import = False

        if ttype == tokenize.NAME and tstring in mapping and not in_import:
            # global/del sobre simbolo mapeado: tratar a mano
            if prev_sig is not None and prev_sig.type == tokenize.NAME and prev_sig.string in ("global", "nonlocal", "del"):
                raise SystemExit(
                    f"ERROR: '{prev_sig.string} {tstring}' en linea {start[0]} requiere tratamiento manual"
                )
            skip = False
            # Atributo: precedido por '.'
            if prev_sig is not None and prev_sig.type == tokenize.OP and prev_sig.string == ".":
                skip = True
            # Nombre de def/class
            if prev_sig is not None and prev_sig.type == tokenize.NAME and prev_sig.string in ("def", "class"):
                skip = True
            # kwarg o parametro con default: NAME '=' tras '(' o ','
            if not skip:
                nxt = next((t for t in tokens[i + 1:] if t.type not in (tokenize.NL, tokenize.COMMENT)), None)
                if (
                    nxt is not None
                    and nxt.type == tokenize.OP
                    and nxt.string == "="
                    and prev_sig is not None
                    and prev_sig.type == tokenize.OP
                    and prev_sig.string in ("(", ",")
                ):
                    skip = True
            if not skip:
                tok = tokenize.TokenInfo(ttype, f"{mapping[tstring]}.{tstring}", start, end, line)
                count += 1
        elif ttype == tokenize.STRING and re.match(r"^[a-zA-Z]*[fF]", tstring):
            new_string = _rewrite_fstring(tstring, mapping)
            if new_string != tstring:
                count += 1
                tok = tokenize.TokenInfo(ttype, new_string, start, end, line)

        if ttype not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
            prev_sig = tok
        out.append(tok)

    return tokenize.untokenize(out), count


def _selftest() -> None:
    mapping = {"_utc_now": "timeutils", "DB_PATH": "settings", "CONFIG_CLIENTES": "state"}
    src = (
        "x = _utc_now()\n"
        "y = obj._utc_now\n"
        "def _utc_now():\n"
        "    return 1\n"
        "f(_utc_now=3)\n"
        "g(a, _utc_now())\n"
        "s = '_utc_now()'\n"
        "t = f\"db en {DB_PATH} a las {_utc_now()}\"\n"
        "from x import DB_PATH\n"
        "import DB_PATH\n"
        "cfg = CONFIG_CLIENTES[k]\n"
    )
    result, n = qualify_source(src, mapping)
    assert "x = timeutils._utc_now()" in result, result
    assert "obj._utc_now" in result and "obj.timeutils." not in result, result
    assert "def _utc_now()" in result, result
    assert "f(_utc_now=3)" in result, result
    assert "g(a, timeutils._utc_now())" in result, result
    assert "'_utc_now()'" in result, result
    assert "settings.DB_PATH} a las {timeutils._utc_now()" in result, result
    assert "from x import DB_PATH" in result, result
    multi, _ = qualify_source("from x import (" + chr(10) + "    DB_PATH," + chr(10) + "    _utc_now," + chr(10) + ")" + chr(10), mapping)
    assert "settings." not in multi and "timeutils." not in multi, multi
    assert "cfg = state.CONFIG_CLIENTES[k]" in result, result
    try:
        qualify_source("global DB_PATH\n", mapping)
        raise AssertionError("global no detectado")
    except SystemExit:
        pass
    try:
        qualify_source("del CONFIG_CLIENTES\n", mapping)
        raise AssertionError("del no detectado")
    except SystemExit:
        pass
    print(f"selftest OK ({n} reemplazos en muestra)")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        _selftest()
        return
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    path, map_path = sys.argv[1], sys.argv[2]
    write = "--write" in sys.argv[3:]
    mapping = json.loads(open(map_path, encoding="utf-8").read())
    source = open(path, encoding="utf-8").read()
    result, count = qualify_source(source, mapping)
    if write:
        open(path, "w", encoding="utf-8", newline="").write(result)
        print(f"{path}: {count} reemplazos escritos")
    else:
        print(f"{path}: {count} reemplazos (dry-run; usa --write)")


if __name__ == "__main__":
    main()
