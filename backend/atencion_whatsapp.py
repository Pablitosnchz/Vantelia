"""Frontera de ENTRADA de WhatsApp: con la atención pausada no se prepara respuesta.

Lo que NO cambia cuando la atención está pausada, porque no es atención automática:
la verificación del webhook, los estados de entrega, los ecos del equipo desde su
móvil y la respuesta 200 a Meta. Un 4xx o un 5xx haría que Meta reintentara el
mismo mensaje una y otra vez, y el negocio no tiene forma de pararlo.

Lo que sí se corta: preparar y mandar respuesta, bajar y transcribir audios, y
cualquier efecto de una cita. La entrada de la clienta se guarda igual: el equipo
tiene que poder leerla en el panel y contestar a mano cuando vuelva.

El turno se instala aquí para que las mutaciones del núcleo (crear, cancelar,
mover) pasen por la misma autoridad que el resto de este bloque. Una lectura sin
ticket sería solo una foto: la admisión vive en `atencion_operaciones`.
"""
from contextlib import contextmanager
from datetime import timedelta
import uuid

from backend import atencion, atencion_contexto, atencion_operaciones, settings, timeutils

# Un turno entrante de WhatsApp no puede quedar vivo indefinidamente: si el
# proceso muere a mitad, el ticket caduca solo y no bloquea al siguiente mensaje.
VIGENCIA_ENTRADA_SEGUNDOS = 300


def _capturar_ticket(cliente_id, clave_intento):
    ahora = timeutils._utc_now()
    return atencion_operaciones.crear_ticket_atencion(
        cliente_id, clave_intento, event_at=ahora.isoformat(),
        expires_at=(ahora + timedelta(seconds=VIGENCIA_ENTRADA_SEGUNDOS)).isoformat())


def puede_atender(cliente_id):
    """Foto barata para no gastar antes de saber si se puede atender.

    No autoriza nada: solo evita bajar un audio o llamar al modelo cuando ya se
    sabe que no se va a contestar. Quien decide de verdad es `turno_entrada`, que
    registra el ticket en la misma transacción. Si no se puede saber, se responde
    que NO: un error de lectura nunca es permiso para atender.
    """
    if not cliente_id:
        return True          # el número de demo resuelve su negocio más abajo
    try:
        return atencion.leer_atencion(cliente_id)["estado"] == "activa"
    except atencion.AtencionNoDisponible:
        settings.logger.error("atencion_whatsapp_estado_no_verificable")
        return False


@contextmanager
def turno_entrada(cliente_id):
    """Instala el turno del canal, o corta con `AtencionDetenida` si no atiende."""
    clave_intento = uuid.uuid4().hex
    try:
        ticket = _capturar_ticket(cliente_id, clave_intento)
        estado = atencion_operaciones.comprobar_ticket_atencion(cliente_id, ticket["ticket_id"])
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada) as exc:
        raise atencion_contexto.AtencionDetenida("atencion_no_verificable") from exc
    if not estado["puede_preparar"]:
        raise atencion_contexto.AtencionDetenida(estado["motivo_actual"] or "atencion_pausada")
    with atencion_contexto.turno_atencion(cliente_id, ticket["ticket_id"], clave_intento):
        yield ticket["ticket_id"]
