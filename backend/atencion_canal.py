"""Lo que comparten todas las fronteras de canal: una sola forma de pedir turno.

Cada canal decide QUE se corta y que no (WhatsApp conserva los ecos del equipo,
el teléfono cuelga con su locución, el worker de recordatorios se salta la cita);
lo que NO se reescribe por canal es la pregunta a la autoridad ni la captura del
ticket. Duplicar eso fue lo que dejó la fase 1 sin efecto durante semanas: la
autoridad existía y cada puerta seguía contestando por su cuenta.

Regla que no depende del canal: si el estado no se puede verificar, no se
atiende. Un error de lectura nunca es permiso para atender.
"""
from contextlib import contextmanager
from datetime import timedelta
import uuid

from backend import atencion, atencion_contexto, atencion_operaciones, settings, timeutils

# Un turno de canal no puede quedar vivo indefinidamente: si el proceso muere a
# mitad, el ticket caduca solo y no bloquea al siguiente evento. Cada canal fija
# el suyo por política propia; no se deduce de las ventanas del proveedor.
VIGENCIA_POR_DEFECTO_SEGUNDOS = 300


def _capturar_ticket(cliente_id, clave_intento, vigencia_segundos):
    ahora = timeutils._utc_now()
    return atencion_operaciones.crear_ticket_atencion(
        cliente_id, clave_intento, event_at=ahora.isoformat(),
        expires_at=(ahora + timedelta(seconds=vigencia_segundos)).isoformat())


def puede_atender(cliente_id, canal=""):
    """Foto barata para no gastar antes de saber si se puede atender.

    No autoriza nada: solo evita bajar un audio, abrir una llamada o llamar al
    modelo cuando ya se sabe que no se va a contestar. Quien decide de verdad es
    `turno`, que registra el ticket en la misma transacción.
    """
    if not cliente_id:
        return True          # el negocio aún no está resuelto; se decide después
    try:
        return atencion.leer_atencion(cliente_id)["estado"] == "activa"
    except atencion.AtencionNoDisponible:
        settings.logger.error("atencion_estado_no_verificable canal=%s", canal or "-")
        return False


@contextmanager
def turno(cliente_id, canal="", vigencia_segundos=VIGENCIA_POR_DEFECTO_SEGUNDOS):
    """Instala el turno del canal, o corta con `AtencionDetenida` si no atiende."""
    clave_intento = uuid.uuid4().hex
    try:
        ticket = _capturar_ticket(cliente_id, clave_intento, vigencia_segundos)
        estado = atencion_operaciones.comprobar_ticket_atencion(cliente_id, ticket["ticket_id"])
    except (atencion.AtencionNoDisponible, atencion_operaciones.AtencionOperacionNoEncontrada) as exc:
        raise atencion_contexto.AtencionDetenida("atencion_no_verificable") from exc
    if not estado["puede_preparar"]:
        raise atencion_contexto.AtencionDetenida(estado["motivo_actual"] or "atencion_pausada")
    with atencion_contexto.turno_atencion(cliente_id, ticket["ticket_id"], clave_intento):
        yield ticket["ticket_id"]
