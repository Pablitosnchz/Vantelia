"""Frontera del worker de avisos: recordatorios, llamadas de confirmación y reseñas.

Estos no los pide nadie: salen solos cada pocos minutos. Con la atención pausada
no salen, y hay DOS momentos en los que la pausa puede pillar a un aviso, con
consecuencias distintas a propósito:

- ANTES de empezarlo (`hay_atencion`): no se intenta y no se anota nada. Ni
  entrega, ni fallo de proveedor -que ni se ha tocado-, ni respaldo por otro
  canal. Si al reactivar el aviso todavía toca, sale: marcarlo habría dejado la
  cita sin recordatorio para siempre.
- DURANTE el envío (`turno_aviso`): cada fragmento se admite justo antes del
  transporte, así que una pausa que cae a mitad frena lo que aún no ha salido.
  Ese aviso queda `omitido/atencion_suprimida` en `notice_deliveries` y es
  terminal: ya se había empezado a preparar para una clienta concreta, y
  reanudarlo después podría mandar la mitad que faltaba fuera de contexto.

Se pregunta por AVISO, no una vez por pasada: entre el primero y el último de
una tanda hay red de por medio.

El turno es de CADA aviso, no del bucle ni de la llamada de confirmación que va
detrás: la identidad del aviso (negocio, cita, generación y tipo) es la que
evita que dos pasadas, o dos workers, manden el mismo recordatorio con tickets
distintos. Sin esa identidad dos avisos de la misma cita colisionaban en el
diario por canal y número de fragmento; por eso este capturador no se conectó
hasta tenerla.

Solo los recordatorios de cita van con turno. Reseñas, rebooking y avisos de
caducidad siguen solo con la puerta previa: no tienen todavía identidad de
aviso, y su propia idempotencia (el sello de cada tabla) evita repetirlos.

Lo que el equipo manda a mano desde el panel no pasa por aquí: eso es una
persona decidiendo, no atención automática. La llamada de confirmación sí se
frena aunque la pida el panel, porque la sostiene la IA (`atencion_voz`).
"""
from contextlib import contextmanager

from backend import atencion_canal, settings

# 15 minutos. Un ticket vencido cuenta como SUPRESIÓN, y en un aviso con turno
# una supresión es terminal: si esto fuera corto, un envío lento -email, luego
# WhatsApp, luego SMS, con timeouts de 15-25 s por operación- dejaría la cita
# sin recordatorio para siempre con la etiqueta de una pausa que nunca hubo. La
# vigencia no protege de la pausa (esa se comprueba por versión en cada
# fragmento), así que ser holgada no cuesta nada.
VIGENCIA_AVISO_SEGUNDOS = 900


def hay_atencion(cliente_id, ya_avisados=None):
    """True si este negocio admite avisos automáticos ahora mismo.

    `ya_avisados` es un conjunto opcional para no repetir la misma línea de log
    por cada cita de la misma pasada. No cachea la decisión: solo el log.
    """
    if atencion_canal.puede_atender(cliente_id, "avisos"):
        return True
    if ya_avisados is not None and cliente_id not in ya_avisados:
        ya_avisados.add(cliente_id)
        settings.logger.info("[avisos] %s en pausa: no salen avisos automaticos", cliente_id)
    return False


@contextmanager
def turno_aviso(cliente_id):
    """Turno de UN aviso: cada fragmento se admite contra la autoridad."""
    with atencion_canal.turno(cliente_id, "avisos", VIGENCIA_AVISO_SEGUNDOS) as ticket_id:
        yield ticket_id
