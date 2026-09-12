"""Plantillas de WhatsApp por negocio: alta en Meta, estado y payload de envio.

POR QUE EXISTE
--------------
Por WhatsApp solo se puede escribir texto libre DENTRO de las 24 h siguientes al
ultimo mensaje del cliente (`inbox.window_open`). Un recordatorio 24 h antes de la
cita cae casi siempre fuera de esa ventana, asi que tiene que salir como
**plantilla aprobada por Meta**.

Con Coexistence cada negocio conecta SU numero y SU cuenta (WABA), y las
plantillas viven en la WABA de cada uno: la de demo y la de cada cliente son
objetos DISTINTOS, con su propio id y su propio estado de aprobacion. Por eso la
tabla `wa_templates` lleva el `cliente_id` en la clave y por eso el alta se hace
con el token del negocio, no con el global.

REGLA
-----
Una plantilla en revision o rechazada NO puede hacer que el aviso se pierda: si no
esta aprobada, este modulo dice que no y el aviso sale por el siguiente canal
(email). Nunca en silencio.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import httpx

from backend import db, settings, textnorm, timeutils

GRAPH = "https://graph.facebook.com"

# La plantilla del recordatorio de cita. Categoria UTILITY: es transaccional (una
# cita que el cliente ya tiene), no promocion. Meta rechaza como UTILITY lo que
# suena a publicidad, asi que el texto va neutro y sin ofertas ni enlaces.
NOMBRE_RECORDATORIO = "vantelia_recordatorio_cita"
IDIOMA = "es"
CATEGORIA = "UTILITY"

# Los botones de la plantilla son QUICK_REPLY. El payload NO se fija aqui: se
# manda en cada envio (lleva el id de la cita), y llega de vuelta por el webhook
# como `type: "button"` con `button.payload`.
BOTONES = ("Confirmo", "Cancelar cita")

CUERPO = (
    "Hola {{1}}, te recordamos tu cita de {{2}} el {{3}} a las {{4}} en {{5}}. "
    "Responde Confirmo si vas a venir, o Cancelar cita si no puedes."
)

EJEMPLO = ["Ana", "Corte señora", "martes 16 de septiembre", "10:30", "Peluqueria Alicia"]

# Estados que devuelve Meta. Solo APPROVED permite enviar.
APROBADA = "APPROVED"


def componentes() -> List[Dict[str, Any]]:
    """La definicion que se le manda a Meta para crear la plantilla."""
    return [
        {
            "type": "BODY",
            "text": CUERPO,
            "example": {"body_text": [list(EJEMPLO)]},
        },
        {
            "type": "BUTTONS",
            "buttons": [{"type": "QUICK_REPLY", "text": texto} for texto in BOTONES],
        },
    ]


# --- Persistencia ----------------------------------------------------------


def _row_to_dict(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    if not row:
        return {}
    return {
        "cliente_id": row["cliente_id"],
        "name": row["name"],
        "language": row["language"],
        "status": row["status"] or "",
        "category": row["category"] or "",
        "meta_id": row["meta_id"] or "",
        "motivo_rechazo": row["motivo_rechazo"] or "",
        "last_error": row["last_error"] or "",
        "updated_at": row["updated_at"] or "",
    }


def estado(cliente_id: str, *, name: str = NOMBRE_RECORDATORIO,
           language: str = IDIOMA) -> Dict[str, Any]:
    """Lo que sabemos de la plantilla de ESTE negocio ({} si no consta)."""
    try:
        with db._get_db_connection() as connection:
            row = connection.execute(
                "SELECT * FROM wa_templates WHERE cliente_id = ? AND name = ? AND language = ?",
                (cliente_id, name, language),
            ).fetchone()
    except Exception:  # noqa: BLE001 - antes de la migracion la tabla puede no existir
        return {}
    return _row_to_dict(row)


def guardar_estado(
    cliente_id: str,
    *,
    name: str = NOMBRE_RECORDATORIO,
    language: str = IDIOMA,
    status: str = "",
    category: str = "",
    meta_id: str = "",
    motivo_rechazo: str = "",
    last_error: str = "",
) -> Dict[str, Any]:
    ahora = timeutils._utc_now_iso()
    with db._get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO wa_templates
                (cliente_id, name, language, status, category, meta_id,
                 motivo_rechazo, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cliente_id, name, language) DO UPDATE SET
                status = excluded.status,
                category = excluded.category,
                meta_id = CASE WHEN excluded.meta_id <> '' THEN excluded.meta_id ELSE wa_templates.meta_id END,
                motivo_rechazo = excluded.motivo_rechazo,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                cliente_id, name, language,
                textnorm._sanitize_text(status).upper()[:40],
                textnorm._sanitize_text(category).upper()[:40],
                textnorm._sanitize_text(meta_id)[:80],
                textnorm._sanitize_text(motivo_rechazo)[:300],
                textnorm._sanitize_text(last_error)[:300],
                ahora, ahora,
            ),
        )
        connection.commit()
    return estado(cliente_id, name=name, language=language)


def aprobada(cliente_id: str, *, name: str = NOMBRE_RECORDATORIO,
             language: str = IDIOMA) -> bool:
    """¿Se puede mandar YA esta plantilla a este negocio?"""
    return (estado(cliente_id, name=name, language=language).get("status") or "") == APROBADA


# Como se le cuenta al negocio, que ni sabe ni tiene por que saber que es una
# plantilla: lo unico que necesita saber es si sus clientas van a recibir el
# recordatorio por WhatsApp o por otro sitio.
_ETIQUETAS = {
    "APPROVED": "Aprobada por Meta: tus recordatorios ya salen por WhatsApp.",
    "PENDING": ("En revisión por Meta. Mientras tanto el aviso sale por el "
                "siguiente canal que tengas puesto."),
    "REJECTED": ("Meta la ha rechazado. Hasta que se corrija, el aviso sale por "
                 "el siguiente canal que tengas puesto."),
}


def resumen_para_el_negocio(cliente_id: str) -> Dict[str, Any]:
    """Lo que ve el negocio en Recordatorios: si puede avisar por WhatsApp o no.

    El estado de la plantilla no es un detalle tecnico: decide si sus clientas
    reciben el recordatorio o no, y si no esta aprobada el aviso se va por otro
    canal SIN que el negocio se entere. Por eso se ensena, con el motivo cuando
    Meta la rechaza -que es justo el dato con el que se arregla-.

    El texto sale de aqui, no de la interfaz: lo leen el portal de hoy y lo que
    venga despues, y tiene que decir lo mismo.
    """
    from backend import wa_onboarding

    cuenta = wa_onboarding.get_account(cliente_id) or {}
    conectado = bool(cuenta.get("waba_id") and cuenta.get("phone_number_id"))
    datos = estado(cliente_id)
    situacion = str(datos.get("status") or "").upper()
    if not conectado:
        etiqueta = "Conecta tu WhatsApp para poder avisar a tus clientas por ahí."
    elif not situacion:
        etiqueta = ("Todavía no está dada de alta. Se pide sola la primera vez "
                    "que haga falta enviar un recordatorio.")
    else:
        etiqueta = _ETIQUETAS.get(situacion, situacion)
    return {
        "conectado": conectado,
        "estado": situacion,
        "etiqueta": etiqueta,
        "motivo": str(datos.get("motivo_rechazo") or ""),
        "ultimo_error": str(datos.get("last_error") or ""),
        "actualizado": str(datos.get("updated_at") or ""),
        "puede_enviar": bool(conectado and situacion == APROBADA),
        "aviso_coste": ("Pasadas 24 h desde el último mensaje de la clienta, cada "
                        "recordatorio por WhatsApp lo cobra Meta a tu cuenta: hace "
                        "falta un método de pago en WhatsApp Manager."),
    }


# --- Graph API -------------------------------------------------------------


def _waba_y_token(cliente_id: str) -> tuple:
    """(waba_id, token) del negocio. Sin los dos no se puede tocar su plantilla.

    Import tardio de `wa_onboarding` para no acoplar el arranque: este modulo lo
    usa el worker de recordatorios, que ya importa medio backend.
    """
    from backend import wa_onboarding

    cuenta = wa_onboarding.get_account(cliente_id) or {}
    return str(cuenta.get("waba_id") or ""), wa_onboarding.account_token(cliente_id)


async def _graph_post_json(path: str, token: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """POST con cuerpo JSON.

    `wa_onboarding._graph_post` manda formulario, que no vale aqui: los
    componentes de una plantilla son una estructura anidada.
    """
    url = "%s/%s/%s" % (GRAPH, settings.WHATSAPP_API_VERSION, path)
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            url, headers={"Authorization": "Bearer %s" % token}, json=body
        )
        payload = response.json() if response.content else {}
    if response.status_code >= 300 or "error" in payload:
        raise RuntimeError(str((payload.get("error") or {}).get("message") or response.text)[:300])
    return payload


async def _buscar(waba_id: str, token: str, name: str) -> List[Dict[str, Any]]:
    from backend import wa_onboarding

    data = await wa_onboarding._graph_get(
        "%s/message_templates" % waba_id,
        {"name": name, "access_token": token},
    )
    return list(data.get("data") or [])


async def asegurar(
    cliente_id: str,
    *,
    name: str = NOMBRE_RECORDATORIO,
    language: str = IDIOMA,
) -> Dict[str, Any]:
    """Deja la plantilla dada de alta en la WABA del negocio y guarda su estado.

    Idempotente: si ya existe no la vuelve a crear, solo refresca el estado. Nunca
    lanza hacia arriba (el alta de un numero o un recordatorio no se caen porque
    Meta conteste mal): el problema queda en `last_error` y la plantilla sigue sin
    aprobar, que es lo que lee el envio.
    """
    def _con_el_fallo(exc: Exception) -> Dict[str, Any]:
        """Apunta el fallo SIN perder lo que ya se sabia de la plantilla.

        Guardar solo el error dejaba una plantilla RECHAZADA sin su motivo en
        cuanto fallaba la red una vez, y el motivo es justo lo que el negocio
        necesita leer para arreglarla.
        """
        anterior = estado(cliente_id, name=name, language=language)
        return guardar_estado(
            cliente_id, name=name, language=language,
            status=anterior.get("status", ""),
            category=anterior.get("category", ""),
            meta_id=anterior.get("meta_id", ""),
            motivo_rechazo=anterior.get("motivo_rechazo", ""),
            last_error=str(exc),
        )

    waba_id, token = _waba_y_token(cliente_id)
    if not (waba_id and token):
        return guardar_estado(
            cliente_id, name=name, language=language, status="",
            last_error="El negocio no tiene su cuenta de WhatsApp conectada.",
        )

    try:
        existentes = await _buscar(waba_id, token, name)
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[wa_plantillas] no se pudo consultar %s de %s: %s", name, cliente_id, exc)
        return _con_el_fallo(exc)

    for plantilla in existentes:
        if str(plantilla.get("language") or "") != language:
            continue
        return guardar_estado(
            cliente_id, name=name, language=language,
            status=str(plantilla.get("status") or ""),
            category=str(plantilla.get("category") or ""),
            meta_id=str(plantilla.get("id") or ""),
            motivo_rechazo=str(plantilla.get("rejected_reason") or ""),
        )

    try:
        creada = await _graph_post_json(
            "%s/message_templates" % waba_id, token,
            {
                "name": name,
                "language": language,
                "category": CATEGORIA,
                "components": componentes(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        settings.logger.error("[wa_plantillas] no se pudo crear %s en %s: %s", name, cliente_id, exc)
        return _con_el_fallo(exc)

    return guardar_estado(
        cliente_id, name=name, language=language,
        # Meta suele devolver PENDING; una plantilla recien creada nunca se puede
        # mandar todavia, asi que si no dice nada se asume que esta en revision.
        status=str(creada.get("status") or "PENDING"),
        category=str(creada.get("category") or CATEGORIA),
        meta_id=str(creada.get("id") or ""),
    )


# Cada cuanto se le pregunta a Meta. La app no esta suscrita al aviso de estado
# (`message_template_status_update`), asi que preguntar es la forma de enterarse
# de la aprobacion: cada hora mientras esta en revision, a diario una vez resuelta
# (una aprobada puede pasar a PAUSED por calidad; una rechazada se puede editar).
REFRESCO_EN_REVISION = 3600
REFRESCO_RESUELTA = 24 * 3600
_RESUELTAS = {APROBADA, "REJECTED", "DISABLED", "PAUSED"}


async def refrescar_pendientes(ahora: Any = None) -> int:
    """Alta y estado de la plantilla en cada negocio con su WhatsApp conectado.

    Lo llama el worker de recordatorios. Devuelve cuantos negocios se han
    consultado. Nunca lanza: un negocio que falla no frena a los demas.
    """
    from backend import wa_onboarding

    ahora = ahora or timeutils._utc_now()
    consultados = 0
    for cliente_id in sorted(set(wa_onboarding.phone_client_map().values())):
        actual = estado(cliente_id)
        status = (actual.get("status") or "").upper()
        cuando = timeutils._from_utc_iso(actual.get("updated_at") or "") if actual else None
        espera = REFRESCO_RESUELTA if status in _RESUELTAS else REFRESCO_EN_REVISION
        if cuando is not None and (ahora - cuando).total_seconds() < espera:
            continue
        try:
            await asegurar(cliente_id)
            consultados += 1
        except Exception as exc:  # noqa: BLE001 - asegurar no lanza, pero por si acaso
            settings.logger.warning("[wa_plantillas] no se pudo refrescar %s: %s", cliente_id, exc)
    return consultados


def actualizar_desde_webhook(cliente_id: str, value: Dict[str, Any]) -> Dict[str, Any]:
    """Aprobacion o rechazo que llega por `message_template_status_update`.

    Sin esto habria que preguntarle a Meta cada vez; con esto el portal enseña el
    estado real en cuanto cambia.
    """
    name = str(value.get("message_template_name") or "").strip()
    if not (cliente_id and name):
        return {}
    return guardar_estado(
        cliente_id,
        name=name,
        language=str(value.get("message_template_language") or IDIOMA).strip() or IDIOMA,
        status=str(value.get("event") or value.get("new_status") or "").strip(),
        meta_id=str(value.get("message_template_id") or "").strip(),
        motivo_rechazo=str(value.get("reason") or "").strip(),
    )


# --- Envio -----------------------------------------------------------------


def _parametro(texto: str) -> Dict[str, str]:
    """Un parametro de plantilla no admite saltos de linea, tabuladores ni cuatro
    espacios seguidos: Meta rechaza el envio ENTERO. Se limpia aqui, que es por
    donde salen todos."""
    limpio = textnorm._sanitize_text(str(texto or ""))
    while "    " in limpio:
        limpio = limpio.replace("    ", " ")
    return {"type": "text", "text": (limpio or "-")[:900]}


def payload_recordatorio(
    *,
    to_number: str,
    booking_id: str,
    nombre: str,
    servicio: str,
    dia: str,
    hora: str,
    negocio: str,
    name: str = NOMBRE_RECORDATORIO,
    language: str = IDIOMA,
) -> Dict[str, Any]:
    """El mensaje de plantilla listo para `messaging._send_whatsapp_payload`.

    Los payload de los botones son los MISMOS ids que los botones interactivos
    (`bkok_` / `bkcancel_`), asi que la respuesta la procesa el manejador de
    siempre y no hay dos formas de confirmar una cita.
    """
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        _parametro(nombre), _parametro(servicio),
                        _parametro(dia), _parametro(hora), _parametro(negocio),
                    ],
                },
                {
                    "type": "button", "sub_type": "quick_reply", "index": "0",
                    "parameters": [{"type": "payload", "payload": "bkok_%s" % booking_id}],
                },
                {
                    "type": "button", "sub_type": "quick_reply", "index": "1",
                    "parameters": [{"type": "payload", "payload": "bkcancel_%s" % booking_id}],
                },
            ],
        },
    }
