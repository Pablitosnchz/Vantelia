# -*- coding: utf-8 -*-
"""Avisar al negocio cuando una clienta necesita a una persona.

POR QUE EXISTE
--------------
El asistente ya sabe callarse cuando alguien pide hablar con una persona
(`inbox.claim`), pero **nadie avisaba al negocio**. La conversacion se quedaba
esperando en el panel a que alguien lo mirara, y la clienta esperando delante del
movil. Estaba escrito como pendiente en el propio repo:

    "PENDIENTE: no hay aviso al negocio cuando entra un mensaje (ni email ni
     push); hoy hay que estar mirando el panel."

Con un salon que mira el panel a ratos se nota poco. Con un hotel que no lo mira
nunca, es la diferencia entre un asistente y un contestador.

COMO
----
Un email al negocio, con lo que la clienta acaba de escribir y el enlace a la
conversacion. Se manda por el canal de envio del propio cliente
(`emailing._send_client_email`), asi que sale desde su remitente si lo tiene
configurado.

Apagable por tenant (`config['avisos']['pedir_persona'] = false`) y con freno de
repeticion: como mucho uno por conversacion cada media hora, para que veinte
mensajes seguidos no sean veinte correos.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from backend import appstate, clients, emailing, settings, textnorm

# Un aviso por conversacion cada media hora. En memoria a proposito: si el
# proceso se reinicia, como mucho se manda un aviso de mas, que es el lado
# correcto por el que equivocarse.
_ESPERA_ENTRE_AVISOS = 30 * 60


def _ya_avisado(clave: str) -> bool:
    enviados = getattr(appstate, "AVISOS_ENVIADOS", None)
    if enviados is None:
        enviados = {}
        appstate.AVISOS_ENVIADOS = enviados
    ahora = time.time()
    for vieja, cuando in list(enviados.items()):
        if ahora - cuando > _ESPERA_ENTRE_AVISOS:
            enviados.pop(vieja, None)
    if ahora - enviados.get(clave, 0) < _ESPERA_ENTRE_AVISOS:
        return True
    enviados[clave] = ahora
    return False


def esta_activado(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> bool:
    """Encendido salvo que el negocio lo apague. Enterarse es lo de serie."""
    try:
        config = config or clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001 - sin config, mejor avisar que callar
        return True
    seccion = config.get("avisos")
    if not isinstance(seccion, dict) or "pedir_persona" not in seccion:
        return True
    return bool(seccion.get("pedir_persona"))


def _correo_del_negocio(cliente_id: str, config: Optional[Dict[str, Any]] = None) -> str:
    """A donde se avisa: el email de contacto del negocio, o el del dueño."""
    try:
        config = config or clients._get_client_config(cliente_id)
    except Exception:  # noqa: BLE001
        config = {}
    correo = str((config.get("contacto") or {}).get("email") or "").strip()
    if correo:
        return correo
    try:
        from backend import db

        with db._get_db_connection() as conexion:
            fila = conexion.execute(
                "SELECT u.email FROM users u JOIN clientes c ON c.owner_user_id = u.id"
                " WHERE c.cliente_id = ?",
                (cliente_id,),
            ).fetchone()
        return str(fila["email"]).strip() if fila else ""
    except Exception:  # noqa: BLE001 - un aviso no puede romper la conversacion
        return ""


def pide_una_persona(
    cliente_id: str, *, session_id: str, de_quien: str, mensaje: str,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Avisa al negocio de que alguien espera a que le conteste una persona.

    Devuelve True si se mando. Nunca lanza: quedarse sin avisar es malo, pero
    romper la conversacion de la clienta por eso seria peor.
    """
    try:
        if not esta_activado(cliente_id, config):
            return False
        if _ya_avisado("%s|%s" % (cliente_id, session_id)):
            return False
        correo = _correo_del_negocio(cliente_id, config)
        if not correo:
            settings.logger.warning(
                "[avisos] %s no tiene email donde avisar de que piden una persona", cliente_id)
            return False
        config = config or clients._get_client_config(cliente_id)
        negocio = str(config.get("empresa") or config.get("nombre") or cliente_id)
        dicho = textnorm._sanitize_text(mensaje or "")[:400]
        enlace = "%s/app" % str(settings.APP_BASE_URL or "").rstrip("/")
        asunto = "Una clienta pide hablar con vosotras"
        cuerpo = (
            "Hola,\n\n"
            "Alguien acaba de pedir hablar con una persona por WhatsApp, y el "
            "asistente ya se ha callado en esa conversacion.\n\n"
            "  Telefono: %s\n"
            "  Ha escrito: %s\n\n"
            "Podeis contestarle desde el panel, en Chats > Conversaciones:\n%s\n\n"
            "-- %s" % (de_quien or "(sin numero)", dicho or "(sin texto)", enlace, negocio)
        )
        html = (
            "<p>Alguien acaba de pedir <strong>hablar con una persona</strong> por "
            "WhatsApp, y el asistente ya se ha callado en esa conversacion.</p>"
            "<p><strong>Telefono:</strong> %s<br><strong>Ha escrito:</strong> %s</p>"
            "<p><a href=\"%s\">Contestarle desde el panel</a></p>"
            % (textnorm._sanitize_text(de_quien or ""), dicho, enlace)
        )
        emailing._send_client_email(cliente_id, correo, asunto, cuerpo, html)
        return True
    except Exception as exc:  # noqa: BLE001 - el aviso nunca tumba la conversacion
        settings.logger.warning("[avisos] no se pudo avisar a %s: %s", cliente_id, exc)
        return False
