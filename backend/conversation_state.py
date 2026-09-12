"""Snapshots de conversación; comparar versión evita escrituras perdidas.

No interpreta mensajes ni ejecuta reservas. El propietario de Estado serializa
sus hechos y decide sus transiciones. SQLite coordina también procesos distintos.
"""
import json
from contextlib import closing

from backend import db


class ConversationStateConflict(RuntimeError):
    """Otro turno cambió el estado; el llamador debe recargar antes de continuar."""


def read_conversation_state(cliente_id, canal, identidad):
    with closing(db._get_db_connection()) as conn:
        row = conn.execute(
            "SELECT revision, formato, expires_at, payload_json FROM conversation_states"
            " WHERE cliente_id=? AND canal=? AND identidad=?",
            (cliente_id, canal, identidad)).fetchone()
    return dict(row) if row is not None else None


def write_conversation_state(cliente_id, canal, identidad, *, revision, payload, expires_at):
    contenido = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    if len(contenido) > 65536:
        raise ValueError("El estado de conversación supera el límite")
    with closing(db._get_db_connection()) as conn, conn:
        if revision == 0:
            result = conn.execute(
                "INSERT OR IGNORE INTO conversation_states"
                " (cliente_id,canal,identidad,revision,formato,expires_at,payload_json)"
                " VALUES (?,?,?,1,1,?,?)", (cliente_id, canal, identidad, expires_at, contenido))
        else:
            result = conn.execute(
                "UPDATE conversation_states SET revision=revision+1,formato=1,expires_at=?,payload_json=?"
                " WHERE cliente_id=? AND canal=? AND identidad=? AND revision=? AND formato=1",
                (expires_at, contenido, cliente_id, canal, identidad, revision))
        if result.rowcount != 1:
            raise ConversationStateConflict("El estado cambió en otro turno")
    return revision + 1


def forget_conversation_state(cliente_id, canal, identidad, *, now):
    # Una lápida conserva la versión: borrar permitiría que un escritor antiguo
    # insertase otra vez una propuesta que la clienta acaba de descartar.
    with closing(db._get_db_connection()) as conn, conn:
        conn.execute(
            "INSERT INTO conversation_states"
            " (cliente_id,canal,identidad,revision,formato,expires_at,payload_json) VALUES (?,?,?,1,1,?,'{}')"
            " ON CONFLICT(cliente_id,canal,identidad) DO UPDATE SET"
            " revision=conversation_states.revision+1,formato=1,expires_at=excluded.expires_at,payload_json='{}'",
            (cliente_id, canal, identidad, now))


def purge_conversation_states(*, before, limit=200):
    """Limpieza acotada; el llamador deja margen mayor que la vida de un escritor."""
    with closing(db._get_db_connection()) as conn, conn:
        result = conn.execute(
            "DELETE FROM conversation_states WHERE rowid IN"
            " (SELECT rowid FROM conversation_states WHERE expires_at < ? ORDER BY expires_at LIMIT ?)",
            (before, min(max(int(limit), 1), 200)))
    return result.rowcount
