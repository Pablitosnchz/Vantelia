"""Frontera de VOZ: con la atención pausada la IA no habla, ni entrando ni saliendo.

Dónde se traza la raya. Una pausa no deja mudo al negocio: el equipo sigue
entrando al panel, contestando a mano y mandando un email o un recordatorio
cuando lo decide. Lo que no ocurre es que la IA sostenga una conversación en su
nombre. Una llamada es exactamente eso, la lleve quien la haya arrancado, así
que aquí no hay excepción humana: el botón «Llamar para confirmar» del panel
recibe el mismo no que el worker de recordatorios, y con su motivo.

Qué cubre este corte, todo comprobable sin proveedor:

- teléfono entrante (`/voice/{cliente_id}`): se contesta con la locución de no
  disponible y no se conecta el Stream;
- el puente (`/voice/stream/{cliente_id}`): se revalida al conectar, porque la
  pausa puede caer entre el TwiML y el WebSocket, y se cierra sin abrir sesión
  con OpenAI -que es lo que se cobra-;
- voz del widget: no se acuña sesión ni se ejecuta ninguna tool real;
- llamadas salientes (`voice._voice_place_outbound_call`): no se colocan.

Lo que NO se toca: el status callback de Twilio (es un acuse de una llamada que
ya existió) y el registro de la transcripción al colgar (`/voice/widget/.../log`),
que solo deja constancia de lo que pasó y tiene que seguir apareciendo en
Conversaciones.

Sin verificación no se atiende, igual que en el resto del bloque.
"""
from contextlib import contextmanager

from backend import atencion_canal

# Presupuesto del adaptador de voz. No se deduce de la duración máxima de la
# llamada ni de la caducidad del secreto efímero de Realtime: son otras cosas.
VIGENCIA_LLAMADA_SEGUNDOS = 300

MOTIVO_PARA_EL_CLIENTE = (
    "Ahora mismo no podemos atenderte por voz. Escribenos y te contestamos."
)

MOTIVO_PARA_EL_PANEL = (
    "La atención automática está en pausa: la IA no llama mientras lo esté."
)


def puede_atender(cliente_id):
    return atencion_canal.puede_atender(cliente_id, "voz")


@contextmanager
def turno_llamada(cliente_id):
    """Turno para una tool de voz: lo que cree o cambie pasa por la autoridad."""
    with atencion_canal.turno(cliente_id, "voz", VIGENCIA_LLAMADA_SEGUNDOS) as ticket_id:
        yield ticket_id
