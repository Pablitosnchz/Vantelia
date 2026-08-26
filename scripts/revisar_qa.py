# -*- coding: utf-8 -*-
"""Las respuestas del negocio, en un solo sitio: revisa que no se hayan separado.

POR QUE EXISTE
--------------
Lo que el negocio contesta vive en DOS capas, y no dicen lo mismo por si solas:

* `kb_qa` — las Q&A que edita en su panel. **Es la que GANA**: al contestar,
  `rag._match_qa_answer` se mira antes que nada.
* `data/<cliente>/info.txt` — su base documental, de la que se SIEMBRAN esas Q&A
  una sola vez (en el alta). Despues, cada una va por su lado.

Paso de verdad (26-ago-2026): se cambio el texto de la fianza en el info.txt, se
reindexo, y a la clienta le seguia saliendo el viejo, porque la Q&A del portal no
se habia tocado y es la que manda. Media hora de trabajo que no llegaba a nadie.

REGLA: si cambias una respuesta, cambiala donde se contesta (la Q&A del portal).
El info.txt es para lo que NO es una Q&A: catalogo, contexto, detalles.

USO
---
    python scripts/revisar_qa.py --cliente alicia_rincon_estilistas
    python scripts/revisar_qa.py --cliente alicia_rincon_estilistas --arreglar

Sin `--arreglar` solo informa. Con el, copia el texto del info.txt a la Q&A del
portal (que es la que se lee) para las que difieran.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _respuestas_del_info(cliente_id: str) -> dict:
    """Las parejas P:/R: del info.txt, por pregunta."""
    from backend import settings

    ruta = pathlib.Path(settings.DATA_DIR) / cliente_id / "info.txt"
    if not ruta.exists():
        return {}
    bloques, actual = {}, None
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith("P:"):
            actual = linea.strip()[2:].strip()
            bloques[actual] = []
        elif actual is not None:
            bloques[actual].append(linea)
    salida = {}
    for pregunta, lineas in bloques.items():
        texto = chr(10).join(lineas).strip()
        salida[pregunta] = texto[2:].strip() if texto.startswith("R:") else texto
    return salida


def revisar(cliente_id: str, arreglar: bool = False) -> int:
    """Devuelve cuantas respuestas difieren entre las dos capas."""
    from backend import catalog_pick, db, rag, timeutils

    def clave(texto: str) -> str:
        return catalog_pick._norm(texto)[:45]

    del_info = {clave(k): v for k, v in _respuestas_del_info(cliente_id).items()}
    diferentes = []
    for fila in rag._list_qa_rows(cliente_id):
        pregunta = str(fila["question"] if "question" in fila.keys() else "")
        actual = str(fila["answer"] if "answer" in fila.keys() else "").strip()
        nueva = del_info.get(clave(pregunta))
        if nueva and catalog_pick._norm(nueva)[:400] != catalog_pick._norm(actual)[:400]:
            diferentes.append((fila["id"], pregunta, actual, nueva))

    print("cliente: %s" % cliente_id)
    print("respuestas que NO coinciden entre el panel y el info.txt: %d" % len(diferentes))
    for _id, pregunta, actual, nueva in diferentes:
        print()
        print("  %s" % pregunta)
        print("    lo que contesta hoy : %s" % " ".join(actual.split())[:110])
        print("    lo que dice el info : %s" % " ".join(nueva.split())[:110])

    if arreglar and diferentes:
        ahora = timeutils._utc_now_iso()
        with db._get_db_connection() as conexion:
            for _id, _pregunta, _actual, nueva in diferentes:
                conexion.execute(
                    "UPDATE kb_qa SET answer = ?, updated_at = ? WHERE cliente_id = ? AND id = ?",
                    (nueva, ahora, cliente_id, _id),
                )
            conexion.commit()
        print()
        print("actualizadas en el panel: %d" % len(diferentes))
    return len(diferentes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", required=True)
    parser.add_argument("--arreglar", action="store_true",
                        help="copia el texto del info.txt a la Q&A del panel")
    args = parser.parse_args()
    revisar(args.cliente, arreglar=args.arreglar)


if __name__ == "__main__":
    main()
