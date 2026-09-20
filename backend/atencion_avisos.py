"""Frontera del worker de avisos: recordatorios, llamadas de confirmación y reseñas.

Estos no los pide nadie: salen solos cada pocos minutos. Con la atención pausada
no salen, y la supresión es TERMINAL para ese aviso: no se marca entrega, no se
anota fallo de proveedor y no se abre el siguiente canal de respaldo. Marcarlo
sería peor que no mandarlo -la cita se quedaría sin recordatorio para siempre,
también después de reactivar-; anotar un fallo sería mentir sobre el proveedor,
que ni se ha llegado a tocar.

Se pregunta una vez POR AVISO, no una por pasada: entre el primero y el último
de una tanda hay red de por medio, y una pausa que cae en ese hueco tiene que
frenar lo que aún no ha salido. La foto es una lectura de SQLite; el coste es
irrelevante al lado de un envío.

Lo que el equipo manda a mano desde el panel (reenviar la confirmación, pedir la
reseña) no pasa por aquí: eso es una persona decidiendo, no atención automática.
La llamada de confirmación sí se frena aunque la pida el panel, porque la
sostiene la IA; el porqué está en `atencion_voz`.

Aquí se FRENA el aviso; todavía no se le instala turno. Instalarlo metería cada
fragmento en el diario de envíos, y ese diario aún identifica un envío por canal
y número de fragmento: dos avisos distintos de la misma cita colisionarían. La
identidad por aviso (negocio, cita, generación y tipo) es el corte siguiente, y
hasta que exista no se conecta este capturador a la admisión de salidas.
"""
from backend import atencion_canal, settings


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
