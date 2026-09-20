"""La pausa vista desde el panel: lo que el negocio elige y lo que se le cuenta.

La autoridad (`atencion`) solo entiende códigos técnicos y versiones. Aquí vive
lo que ve una persona: la lista cerrada de motivos, qué se para exactamente y
qué sigue igual. Esa lista no es decorado — es la promesa que hacemos al pulsar
el interruptor, y tiene que corresponderse con las fronteras que hay puestas en
el código, no con las que nos gustaría tener.

Dos cosas que este módulo NO hace, a propósito:

- No toca el plan ni los cobros. Pausar la atención y suspender la cuota son
  decisiones distintas y se reconcilian por separado; si se juntaran aquí, una
  pausa de dos semanas por obras cancelaría una suscripción.
- No programa pausas futuras. La transición es inmediata, como la autoridad.
"""
from backend import atencion


# Lista cerrada: la autoridad exige un código técnico y rechaza texto libre,
# entre otras cosas para que un motivo no acabe llevando el nombre de nadie.
MOTIVOS = (
    ("cierre_temporada", "Cerramos por temporada"),
    ("vacaciones", "Vacaciones"),
    ("obras", "Obras o reforma"),
    ("aforo_completo", "Agenda llena, no queremos más citas"),
    ("incidencia_tecnica", "Incidencia técnica"),
    ("decision_del_negocio", "Otro motivo"),
)
MOTIVO_POR_DEFECTO = "decision_del_negocio"

# Cada línea se corresponde con una frontera que existe en el código:
# atencion_chat, atencion_whatsapp, atencion_voz y atencion_avisos.
SE_PARA = (
    "Las respuestas automáticas del chat de tu web.",
    "Las respuestas automáticas por WhatsApp. Lo que te escriban se sigue"
    " guardando y lo ves en Conversaciones.",
    "El asistente de voz: no coge el teléfono ni llama para confirmar citas.",
    "Los recordatorios de cita, las peticiones de reseña y los avisos de"
    " caducidad de bonos y tarjetas.",
    "Los mensajes para reenganchar a clientes que hace tiempo que no vienen.",
)

SIGUE_IGUAL = (
    "Tú y tu equipo entráis al panel y contestáis a mano, como siempre.",
    "Lo que conteste tu equipo desde la app de WhatsApp del móvil.",
    "Tus citas, tu catálogo y tus cobros: no se borra ni se cancela nada.",
    "Las tarjetas regalo ya pagadas se envían igual.",
)

NOTA_FACTURACION = (
    "Pausar no cambia tu plan ni tus cobros. Si quieres cambiar la cuota,"
    " se gestiona aparte."
)


def motivo_valido(motivo):
    claves = [clave for clave, _ in MOTIVOS]
    return motivo if motivo in claves else MOTIVO_POR_DEFECTO


def estado_para_el_panel(cliente_id, *, puede_cambiarlo):
    """Foto del estado más lo que hay que contarle a quien la lee."""
    estado = atencion.leer_atencion(cliente_id)
    return {
        "estado": estado["estado"],
        "version": estado["version"],
        "desde": estado["fecha_efectiva"],
        "motivo": estado["motivo"],
        "puede_cambiarlo": bool(puede_cambiarlo),
        "motivos": [{"clave": clave, "etiqueta": etiqueta} for clave, etiqueta in MOTIVOS],
        "se_para": list(SE_PARA),
        "sigue_igual": list(SIGUE_IGUAL),
        "nota_facturacion": NOTA_FACTURACION,
    }
