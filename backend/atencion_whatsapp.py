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

La pregunta a la autoridad es la común (`atencion_canal`); lo propio de este
canal es su vigencia y qué se conserva pese a la pausa.
"""
from contextlib import contextmanager

from backend import atencion_canal

# 300 s: presupuesto de este adaptador. No se deduce de las 24 h de respuesta
# libre de Meta, ni de los 120 min del estado conversacional, ni de las 6 h del
# token de Flow: resuelven problemas distintos.
VIGENCIA_ENTRADA_SEGUNDOS = 300


def puede_atender(cliente_id):
    return atencion_canal.puede_atender(cliente_id, "whatsapp")


@contextmanager
def turno_entrada(cliente_id):
    with atencion_canal.turno(cliente_id, "whatsapp", VIGENCIA_ENTRADA_SEGUNDOS) as ticket_id:
        yield ticket_id
