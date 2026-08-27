# -*- coding: utf-8 -*-
"""Que una cita con todos los datos llegue al resumen con botones.

Encontrado leyendo las conversaciones rotas de una tirada de 100 (catorce se
fueron sin cita). Transcripcion real:

    ELLA: Hola, kiero cortarme el pelo. Es un corte de senyora. Q hora tienen?
      IA: Para el corte de senyora tengo... 10:00, 10:15, 10:30...
    ELLA: Qero a las 10:30.
      IA: Solo me falta tu nombre.
    ELLA: Me llamo Laura.
      IA: Laura, tengo tu hora a las 10:30, pero necesito que me confirmes...
    ELLA: Confirmo.
      IA: Parece que no puedo reservar la cita en este momento.

Con el servicio, el dia, la hora y el nombre encima de la mesa.

POR QUE PASABA: por WhatsApp la cita NO la crea el modelo -la confirma ella con un
boton-, asi que el agente FRENA `crear_cita` y espera a que el canal mande el
resumen. Y `_wa_resumen_para_confirmar` sale por la puerta de atras si
`estado.intencion` no es "reservar". Nadie la habia declarado: ella no pulso
"Agendar cita", escribio en su idioma. Callejon sin salida garantizado.

Pedir cita ES declarar la intencion.
"""
from __future__ import annotations

from test_booking_exhaustive import api_module  # noqa: F401


def _estado_a_punto():
    """Lo que hay justo cuando el agente frena la creacion."""
    from backend import reserva

    estado = reserva.Estado()
    reserva.anotar_resultado(
        estado, "crear_cita",
        {"servicio": "Corte senora", "fecha": "2026-08-28", "hora": "10:30",
         "nombre": "Laura"},
        {"ok": False, "pendiente_de_confirmacion": True,
         "error": "Todavia no se puede crear: lo confirma la clienta."},
    )
    return estado


def test_pedir_cita_declara_la_intencion(api_module):  # noqa: F811
    """Sin esto, el resumen con botones no sale nunca y la cita no se cierra."""
    estado = _estado_a_punto()
    assert estado.intencion == "reservar", (
        "el resumen de WhatsApp exige intencion 'reservar'; sin ella la clienta "
        "recibe 'parece que no puedo reservar la cita' con todos sus datos dados"
    )


def test_con_todo_dado_ya_no_falta_nada(api_module):  # noqa: F811
    """La otra condicion del resumen: que no falte ningun dato."""
    from backend import reserva

    estado = _estado_a_punto()
    assert reserva.que_falta(estado) == ""
    assert estado.servicio and estado.fecha and estado.hora and estado.nombre


def test_el_resumen_de_whatsapp_sigue_exigiendo_las_dos_cosas(api_module):  # noqa: F811
    """Si algun dia se relaja esto, que se vea aqui: son las dos puertas por las
    que la cita llega al boton de confirmar."""
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_resumen_para_confirmar)
    assert 'estado.intencion != "reservar"' in fuente
    assert "que_falta" in fuente


def test_cancelar_no_se_convierte_en_reservar(api_module):  # noqa: F811
    """La intencion solo se rellena si estaba VACIA: quien viene a cancelar no
    puede acabar en el resumen de una cita nueva."""
    from backend import reserva

    estado = reserva.Estado()
    estado.intencion = "cancelar"
    reserva.anotar_resultado(
        estado, "crear_cita", {"servicio": "Corte senora"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )
    assert estado.intencion == "cancelar"


def test_quien_viene_a_reprogramar_tambien_llega_al_boton(api_module):  # noqa: F811
    """El otro callejon sin salida, tambien medido.

    Transcripcion real: la clienta pide cambiar su cita, el asistente cancela la
    vieja y prepara la nueva... y el resumen no sale, porque solo atendia a
    `intencion == "reservar"` y aqui es "reprogramar". Resultado: CERO citas. La
    vieja perdida y la nueva sin crear, despues de que ella confirmara dos veces.
    """
    from backend import reserva

    estado = reserva.Estado()
    estado.intencion = "reprogramar"
    reserva.anotar_resultado(
        estado, "crear_cita",
        {"servicio": "Corte senora", "fecha": "2026-09-08", "hora": "10:00",
         "nombre": "Laura"},
        {"ok": False, "pendiente_de_confirmacion": True},
    )
    assert estado.esperando_confirmacion is True
    assert estado.intencion == "reprogramar", "la intencion no se pisa"


def test_la_senyal_se_suelta_cuando_la_cita_ya_esta(api_module):  # noqa: F811
    """Si no se soltara, al siguiente mensaje volveria a salir el resumen y
    naceria una SEGUNDA cita: eso ya paso una vez."""
    from backend import reserva

    estado = reserva.Estado()
    estado.esperando_confirmacion = True
    reserva.empezar_otra_gestion(estado)
    assert estado.esperando_confirmacion is False


def test_el_resumen_de_whatsapp_mira_esa_senyal(api_module):  # noqa: F811
    import inspect

    from backend import whatsapp

    fuente = inspect.getsource(whatsapp._wa_resumen_para_confirmar)
    assert "esperando_confirmacion" in fuente
