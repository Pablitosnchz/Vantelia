"""Respuestas automaticas por palabra clave (opt-in por tenant).

Caso de uso: negocios que NO quieren un asistente conversacional para ciertas
preguntas, sino una regla literal y previsible: "si el mensaje contiene 'spa' o
'masaje', responde exactamente este texto". Origen: hotel Cap Rocat (ago 2026).

Es una capa DETERMINISTA que se evalua ANTES del RAG/IA en los canales de texto
(chat web y WhatsApp). Si ninguna regla activa casa, el pipeline sigue igual que
siempre. Apagado por defecto (`config['keyword_rules']['enabled']`), asi que un
tenant sin la seccion no cambia de comportamiento ni hace consultas extra.

La voz NO usa estas reglas: en una llamada el modelo habla, no hay texto que
casar palabra por palabra.

EL IDIOMA DEL HUESPED (sep 2026, peticion de Cap Rocat tras probar la demo): la
respuesta sale en el idioma en que escribe quien pregunta. El negocio puede
escribir cada respuesta en espanol y en ingles (`reply_en`), y esas salen TAL
CUAL. Para cualquier otro idioma (en Mallorca, sobre todo aleman) se traduce su
texto con el modelo. Si la traduccion falla, sale la version inglesa si la hay
y, si no, la de siempre: nunca se queda nadie sin respuesta. El idioma se decide
sin modelo (`idioma_de`), por las palabras que lo delatan; lo dudoso («spa?»)
es espanol, que es la lengua del negocio.
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

from backend import clients, db, settings, textnorm, timeutils

CONFIG_SECTION = "keyword_rules"

MAX_RULES_PER_CLIENT = 100
MAX_KEYWORDS_PER_RULE = 40
MAX_KEYWORD_LEN = 60
MAX_REPLY_LEN = 2000
MAX_LABEL_LEN = 80

MATCH_MODES = ("any", "all")

# Longitud minima para aceptar coincidencia por prefijo ("masaje" casa con
# "masajes"). Por debajo exigimos token exacto: "spa" no debe casar "spandex".
_PREFIX_MIN_LEN = 4

_PUNCT_RE = re.compile(r"[¿?¡!.,;:\"'`()\[\]{}\-_/\\|@#*+=<>~]+")


def _normalize(text: str) -> str:
    """minusculas, sin acentos y sin puntuacion, para casar de forma estable."""
    t = textnorm._strip_accents(str(text or "").lower())
    t = _PUNCT_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def rules_enabled(cliente_id: str) -> bool:
    """True si el tenant tiene activadas las reglas por palabra clave."""
    try:
        config = clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001 - cliente inexistente o config a medias
        return False
    section = config.get(CONFIG_SECTION) or {}
    if not isinstance(section, dict):
        return False
    return bool(section.get("enabled"))


def _sanitize_keywords(raw: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in raw or []:
        kw = _normalize(textnorm._sanitize_text(str(item or "")))[:MAX_KEYWORD_LEN]
        if not kw or kw in seen:
            continue
        seen.add(kw)
        out.append(kw)
        if len(out) >= MAX_KEYWORDS_PER_RULE:
            break
    return out


def _sanitize_match_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in MATCH_MODES else "any"


def _keyword_in_message(keyword: str, norm_message: str, message_tokens: List[str]) -> bool:
    if not keyword:
        return False
    if " " in keyword:
        # Frase: exige la secuencia completa con limites de palabra.
        return f" {keyword} " in f" {norm_message} "
    for token in message_tokens:
        if token == keyword:
            return True
        # Plural / derivados: "masaje" casa "masajes", pero "spa" no casa "spandex".
        if len(keyword) >= _PREFIX_MIN_LEN and token.startswith(keyword):
            return True
    return False


def rule_matches(rule: Dict[str, Any], message: str) -> bool:
    keywords = rule.get("keywords") or []
    if not keywords:
        return False
    norm_message = _normalize(message)
    if not norm_message:
        return False
    tokens = norm_message.split()
    hits = [_keyword_in_message(kw, norm_message, tokens) for kw in keywords]
    if _sanitize_match_mode(rule.get("match_mode")) == "all":
        return all(hits)
    return any(hits)


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        keywords = json.loads(row["keywords_json"] or "[]")
    except Exception:  # noqa: BLE001
        keywords = []
    return {
        "id": row["id"],
        "label": row["label"] or "",
        "keywords": [str(k) for k in keywords if isinstance(k, str)],
        "reply": row["reply"] or "",
        "reply_en": (row["reply_en"] if "reply_en" in row.keys() else "") or "",
        "match_mode": _sanitize_match_mode(row["match_mode"]),
        "active": bool(row["active"]),
        "position": int(row["position"] or 0),
        "hits": int(row["hits"] or 0),
        "last_hit_at": row["last_hit_at"] or "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
    }


def list_rules(cliente_id: str, include_inactive: bool = True) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM keyword_rules WHERE cliente_id = ?"
    if not include_inactive:
        sql += " AND active = 1"
    sql += " ORDER BY position ASC, created_at ASC"
    with db._get_db_connection() as connection:
        rows = connection.execute(sql, (cliente_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_rule(cliente_id: str, rule_id: str) -> Optional[Dict[str, Any]]:
    with db._get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM keyword_rules WHERE id = ? AND cliente_id = ?",
            (rule_id, cliente_id),
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_rule(
    cliente_id: str,
    *,
    label: str = "",
    keywords: Any = None,
    reply: str = "",
    reply_en: str = "",
    match_mode: Any = "any",
    active: bool = True,
    position: Optional[int] = None,
    created_by_user_id: str = "",
) -> Dict[str, Any]:
    clean_keywords = _sanitize_keywords(keywords)
    clean_reply = textnorm._sanitize_text(reply, allow_multiline=True)[:MAX_REPLY_LEN].strip()
    clean_reply_en = textnorm._sanitize_text(reply_en or "", allow_multiline=True)[:MAX_REPLY_LEN].strip()
    if not clean_keywords:
        raise ValueError("Indica al menos una palabra clave.")
    if not clean_reply:
        raise ValueError("La respuesta automatica no puede estar vacia.")
    now_iso = timeutils._utc_now_iso()
    rule_id = "kwr_" + secrets.token_hex(10)
    with db._get_db_connection() as connection:
        total = connection.execute(
            "SELECT COUNT(*) AS n FROM keyword_rules WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()["n"]
        if total >= MAX_RULES_PER_CLIENT:
            raise ValueError(f"Maximo {MAX_RULES_PER_CLIENT} reglas por negocio.")
        if position is None:
            row = connection.execute(
                "SELECT COALESCE(MAX(position), -1) AS p FROM keyword_rules WHERE cliente_id = ?",
                (cliente_id,),
            ).fetchone()
            position = int(row["p"]) + 1
        connection.execute(
            """
            INSERT INTO keyword_rules (id, cliente_id, label, keywords_json, reply, reply_en,
                                       match_mode, active, position, hits, last_hit_at,
                                       created_at, updated_at, created_by_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?, ?)
            """,
            (
                rule_id,
                cliente_id,
                textnorm._sanitize_text(label)[:MAX_LABEL_LEN],
                json.dumps(clean_keywords, ensure_ascii=False),
                clean_reply,
                clean_reply_en,
                _sanitize_match_mode(match_mode),
                1 if active else 0,
                int(position),
                now_iso,
                now_iso,
                created_by_user_id or "",
            ),
        )
        connection.commit()
    return get_rule(cliente_id, rule_id) or {}


def update_rule(cliente_id: str, rule_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    current = get_rule(cliente_id, rule_id)
    if not current:
        return None
    fields: List[str] = []
    values: List[Any] = []
    if "label" in patch:
        fields.append("label = ?")
        values.append(textnorm._sanitize_text(str(patch.get("label") or ""))[:MAX_LABEL_LEN])
    if "keywords" in patch:
        clean = _sanitize_keywords(patch.get("keywords"))
        if not clean:
            raise ValueError("Indica al menos una palabra clave.")
        fields.append("keywords_json = ?")
        values.append(json.dumps(clean, ensure_ascii=False))
    if "reply" in patch:
        clean_reply = textnorm._sanitize_text(
            str(patch.get("reply") or ""), allow_multiline=True
        )[:MAX_REPLY_LEN].strip()
        if not clean_reply:
            raise ValueError("La respuesta automatica no puede estar vacia.")
        fields.append("reply = ?")
        values.append(clean_reply)
    if "reply_en" in patch:
        # Puede quedarse vacia: entonces el ingles se traduce de la respuesta de siempre.
        fields.append("reply_en = ?")
        values.append(textnorm._sanitize_text(
            str(patch.get("reply_en") or ""), allow_multiline=True)[:MAX_REPLY_LEN].strip())
    if "match_mode" in patch:
        fields.append("match_mode = ?")
        values.append(_sanitize_match_mode(patch.get("match_mode")))
    if "active" in patch:
        fields.append("active = ?")
        values.append(1 if patch.get("active") else 0)
    if "position" in patch:
        try:
            fields.append("position = ?")
            values.append(int(patch.get("position") or 0))
        except (TypeError, ValueError):
            fields.pop()
    if not fields:
        return current
    fields.append("updated_at = ?")
    values.append(timeutils._utc_now_iso())
    values.extend([rule_id, cliente_id])
    with db._get_db_connection() as connection:
        connection.execute(
            f"UPDATE keyword_rules SET {', '.join(fields)} WHERE id = ? AND cliente_id = ?",
            tuple(values),
        )
        connection.commit()
    return get_rule(cliente_id, rule_id)


def delete_rule(cliente_id: str, rule_id: str) -> bool:
    with db._get_db_connection() as connection:
        cur = connection.execute(
            "DELETE FROM keyword_rules WHERE id = ? AND cliente_id = ?",
            (rule_id, cliente_id),
        )
        connection.commit()
        return cur.rowcount > 0


def _register_hit(rule_id: str) -> None:
    try:
        with db._get_db_connection() as connection:
            connection.execute(
                "UPDATE keyword_rules SET hits = hits + 1, last_hit_at = ? WHERE id = ?",
                (timeutils._utc_now_iso(), rule_id),
            )
            connection.commit()
    except Exception as exc:  # noqa: BLE001 - el contador nunca debe romper la respuesta
        settings.logger.debug("No se pudo contar el uso de la regla %s: %s", rule_id, exc)


def match_reply(cliente_id: str, message: str) -> Optional[Dict[str, Any]]:
    """Devuelve la primera regla activa (por orden) que casa con `message`.

    None si el tenant no tiene la funcion activada o no casa ninguna regla: en
    ese caso el canal sigue con su pipeline normal (menu, RAG, IA...).
    """
    if not rules_enabled(cliente_id):
        return None
    message = str(message or "").strip()
    if not message:
        return None
    try:
        rules = list_rules(cliente_id, include_inactive=False)
    except Exception as exc:  # noqa: BLE001
        settings.logger.warning("No se pudieron leer las reglas de %s: %s", cliente_id, exc)
        return None
    for rule in rules:
        if rule_matches(rule, message):
            _register_hit(rule["id"])
            idioma = idioma_de(message)
            rule = dict(rule)
            rule["idioma"] = idioma or "es"
            # `reply` es lo que mandan los canales: aqui ya va en el idioma de quien pregunta.
            rule["reply"] = respuesta_en_su_idioma(rule, idioma)
            return rule
    return None


# ─── El idioma de quien pregunta ────────────────────────────────────────────
#
# Palabras que delatan cada idioma, ya normalizadas (sin tildes ni mayusculas). Solo las que
# NO se confunden con las de otro: «la» o «de» estan en media Europa y no cuentan.
_PALABRAS_DE = {
    "es": {"hola", "que", "quiero", "quisiera", "tienen", "teneis", "tiene", "hay", "donde",
           "cuando", "cuanto", "cuesta", "reservar", "gracias", "buenos", "buenas", "tardes",
           "noches", "puedo", "podria", "habitacion", "habitaciones", "los", "las", "una", "del",
           "por", "para", "como", "esta", "estan", "hacer", "mesa", "cena", "cenar", "llegar"},
    "en": {"the", "you", "your", "have", "has", "do", "does", "is", "are", "there", "can",
           "could", "would", "please", "hello", "hi", "what", "where", "when", "how", "much",
           "book", "booking", "room", "rooms", "thanks", "thank", "any", "we", "our", "my",
           "with", "and", "for", "get", "want", "like", "dinner", "table", "which"},
    "de": {"der", "die", "das", "und", "ich", "sie", "haben", "ist", "ein", "eine", "wir",
           "bitte", "danke", "hallo", "guten", "wie", "wo", "wann", "zimmer", "buchen", "gibt",
           "moechte", "mochte", "konnen", "koennen", "einen", "fur", "fuer", "nicht"},
    "fr": {"le", "les", "et", "je", "vous", "avez", "est", "nous", "bonjour", "merci",
           "comment", "quand", "chambre", "reserver", "pour", "avec", "une", "des", "est-ce"},
    "it": {"il", "gli", "io", "avete", "ciao", "grazie", "buongiorno", "vorrei", "camera",
           "prenotare", "che", "sono", "della", "posso", "quanto"},
    "nl": {"het", "een", "ik", "jullie", "hebben", "heeft", "hallo", "dank", "bedankt", "kamer",
           "boeken", "waar", "wanneer", "hoe", "kan", "graag", "niet", "wij"},
}
# Como se le dice al modelo a que idioma traducir.
_NOMBRE_DEL_IDIOMA = {"de": "German", "fr": "French", "it": "Italian", "nl": "Dutch",
                      "en": "English"}
# Traducciones ya hechas: la misma respuesta al mismo idioma no se paga dos veces.
_TRADUCCIONES: Dict[tuple, str] = {}


def idioma_de(message: str) -> str:
    """«es», «en», «de», «fr», «it», «nl» o «» si no hay con que decidirlo.

    Sin modelo y siempre igual: cuenta las palabras que delatan cada idioma y gana el que
    mas tenga, si gana solo. Lo dudoso («spa?», un empate) vuelve vacio y se contesta en
    espanol, que es la lengua del negocio.
    """
    palabras = _normalize(message).split()
    cuenta = {idioma: sum(1 for p in palabras if p in lista) for idioma, lista in _PALABRAS_DE.items()}
    mejor = max(cuenta.values()) if cuenta else 0
    if mejor <= 0:
        return ""
    ganadores = [idioma for idioma, n in cuenta.items() if n == mejor]
    return ganadores[0] if len(ganadores) == 1 else ""


def respuesta_en_su_idioma(rule: Dict[str, Any], idioma: str) -> str:
    """La respuesta de la regla en el idioma de quien pregunta.

    Espanol o dudoso: la de siempre. Ingles: la que escribio el negocio en ingles o, si no
    la hay, la de siempre traducida. Otro idioma: se traduce la inglesa (si la hay, que ya
    esta pensada para huespedes de fuera) o la de siempre. Si traducir falla, la inglesa y,
    si no, la de siempre: nunca se queda nadie sin respuesta.
    """
    espanol = str(rule.get("reply") or "")
    ingles = str(rule.get("reply_en") or "").strip()
    if not idioma or idioma == "es":
        return espanol
    if idioma == "en" and ingles:
        return ingles
    traducida = _traducir(ingles or espanol, idioma)
    return traducida or ingles or espanol


def _traducir(texto: str, idioma: str) -> str:
    """Traduce una respuesta del negocio. «» si no se puede: quien llama tiene plan B."""
    destino = _NOMBRE_DEL_IDIOMA.get(idioma)
    if not destino or not texto.strip() or not settings.OPENAI_API_KEY:
        return ""
    clave = (idioma, texto)
    if clave in _TRADUCCIONES:
        return _TRADUCCIONES[clave]
    try:
        from openai import OpenAI as OpenAISdkClient

        cliente = OpenAISdkClient(api_key=settings.OPENAI_API_KEY, timeout=8.0)
        respuesta = cliente.chat.completions.create(
            model=settings.DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": (
                    "Translate this reply from a hotel to %s. Keep phone numbers, emails, web "
                    "addresses and proper names exactly as they are. Keep the same polite tone. "
                    "Answer only with the translation." % destino)},
                {"role": "user", "content": texto[:MAX_REPLY_LEN]},
            ],
            temperature=0,
            max_tokens=700,
        )
        from backend import trazas

        trazas.anotar_llamada(settings.DEFAULT_CHAT_MODEL, respuesta)
        traducida = (respuesta.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 - sin traduccion se responde igual
        settings.logger.warning("No se pudo traducir la respuesta a %s: %s", idioma, exc)
        return ""
    if traducida:
        _TRADUCCIONES[clave] = traducida
    return traducida
