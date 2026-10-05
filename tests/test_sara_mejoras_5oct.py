# -*- coding: utf-8 -*-
"""Lo que salio de analizar las llamadas de Sara del 5-oct-2026 (24 llamadas, 9:32-13:18).

POR QUE EXISTE
--------------
- 7 de 12 conversaciones reales se cortaron justo tras "¿quien coge el telefono?", preguntado a
  la recepcion: ahora se le pide solo a donde mandar la demo para quien decide (los tests del
  guion estan en test_sara_centralitas.py y test_captacion_voz.py).
- "Para español, pulse 1" (Madrid Vascular): Sara colgaba en el menu. Ahora puede pulsar.
- Un ayuntamiento y un laboratorio de protesis en la lista, y sectores que eran la busqueda que
  los encontro, no lo que son ("Clinica Madrid Vascular" como clinica veterinaria).
"""
from __future__ import annotations

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import captacion  # noqa: F401
from test_lanzador_llamadas import MARTES_10_30, _prospecto, lanzador  # noqa: F401


# --- Menus de teclas ------------------------------------------------------------------

@pytest.mark.parametrize("entrada", [False, True])
def test_las_dos_saras_pueden_pulsar_una_tecla(captacion, entrada):  # noqa: F811
    config = captacion.agente_de_captacion("https://app.test", entrada=entrada)["conversation_config"]
    teclas = [t for t in config["agent"]["prompt"]["tools"] if t["name"] == "play_keypad_touch_tone"]
    assert teclas and teclas[0]["params"]["system_tool_type"] == "play_keypad_touch_tone"
    assert "una sola vez" in teclas[0]["description"]
    # Un "hola" suelto no corta a ninguna de las dos.
    assert "hola" in config["turn"]["interruption_ignore_terms"]


# --- Llamada de prueba a Pablo (5-oct, 14:10) -------------------------------------------

def test_la_apertura_va_siempre_primero_aunque_cojan_con_un_si(captacion):  # noqa: F811
    """Pablo cogio con "Si." y Sara fue directa a "Te cuento...", sin decir que es una IA (sin
    primer mensaje, el modelo tomo el "si" de coger el telefono por permiso). El Reglamento de
    IA (art. 50) exige decirlo en la primera frase: es la regla que va antes que todo."""
    guion = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]["prompt"]["prompt"]
    regla = guion.index("REGLA PRIMERA, POR ENCIMA DE TODO LO DEMAS")
    assert regla < guion.index("POR QUE LLAMAS"), "la regla va antes que el resto del guion"
    assert 'tu primera frase de la llamada es SIEMPRE la apertura, tal cual: "{{saludo}}"' in guion
    assert 'ANTES de que hayas dicho la apertura NO es permiso para nada' in guion
    assert '"¿si?"' in guion, "en España se coge el telefono con un ¿si?"
    paso_2 = guion.split("\n2. ", 1)[1].split("\n3. ", 1)[0]
    assert paso_2.startswith("LA PETICION. Si DESPUES de tu apertura te da permiso")


def test_a_un_movil_se_le_ofrece_el_sms_y_nunca_un_correo_que_no_existe(captacion):  # noqa: F811
    """En la misma prueba ofrecio "la demo al correo de Clinica Dental Pablo" a un movil sin
    correo: elegia ella entre tres frases. Ahora la frase la pone el servidor."""
    from test_captacion_voz import _Falso

    hecho = captacion.llamar("675802001", "Clínica Dental Pablo", "clinica dental", cliente=_Falso())
    variables = captacion._variables(captacion._fila(hecho["llamada"]))
    assert variables["canal_envio"] == "sms"
    assert "SMS" in variables["oferta"] and "correo" not in variables["oferta"]
    # A un fijo con correo conocido, ese correo; sin correo, se pide (nunca "el correo de X" vacio).
    assert "info arroba pelu punto es" in captacion.oferta_de_demo("email", "Pelu", "info arroba pelu punto es")
    assert "Me dices un email" in captacion.oferta_de_demo("email", "Pelu", "")


def test_el_turno_de_la_oferta_es_corto(captacion):  # noqa: F811
    """Pablo, tras la segunda prueba: "acorta la oferta". El turno (motivo + oferta) duraba
    unos 50 palabras y pasaban 20 segundos hasta que contestaba."""
    guion = captacion.agente_de_captacion("https://app.test")["conversation_config"]["agent"]["prompt"]["prompt"]
    paso_2 = guion.split("\n2. ", 1)[1].split("\n3. ", 1)[0]
    motivo = paso_2.split('casi tal cual: "', 1)[1].split("{{oferta}}", 1)[0]
    for canal in ("sms", "email", "pedir_email"):
        # El correo es un dato (cuenta como una palabra): lo que se mide es el texto fijo.
        turno = motivo + captacion.oferta_de_demo(canal, "Pelu", "CORREO")
        assert len(turno.split()) <= 40, (canal, len(turno.split()))
    assert "ayudamos a negocios como el vuestro con las llamadas" in motivo, "el motivo de la llamada sigue"


# --- A quien se llama -----------------------------------------------------------------

@pytest.mark.parametrize("negocio,sector,esperado", [
    ("Clínica Madrid Vascular", "clinica veterinaria", "clinica"),   # la busqueda la puso de veterinaria
    ("DST Clinic", "clinica dental", "clinica dental"),              # "clinic" a secas no tapa lo concreto
    ("Kenika Thai Massage", "centro de masajes", "centro de masajes"),
    ("Clínica Dental Reyes 9", "clinica estetica", "clinica dental"),
    ("Purificación Caballero", "peluqueria", "peluqueria"),          # sin pistas en el nombre: la captacion
    ("Fisio Henares", "clinica veterinaria", "fisioterapia"),
])
def test_el_sector_sale_del_nombre_si_lo_dice(lanzador, negocio, sector, esperado):  # noqa: F811
    assert lanzador.sector_real(negocio, sector) == esperado


@pytest.mark.parametrize("negocio,sector", [
    ("Centro de tratamiento de adicciones", "clinica veterinaria"),   # un ayuntamiento, 5-oct
    ("Laboratorio Prótesis Dentales Béticos SL", "clinica estetica"),  # no da citas, 5-oct
    ("Farmacia Central", "clinica"),
    ("Depósito Dental Madrid", "clinica dental"),
])
def test_lo_que_no_da_citas_no_se_llama_aunque_el_sector_diga_otra_cosa(lanzador, negocio, sector):  # noqa: F811
    assert lanzador.da_citas(negocio, sector) is False


def test_la_lista_de_llamadas_sale_limpia_y_con_el_sector_corregido(lanzador):  # noqa: F811
    _prospecto(lanzador, "lab@x.es", "954281145", negocio="Laboratorio Prótesis Dentales Béticos SL",
               sector="clinica estetica")
    _prospecto(lanzador, "plan@x.es", "916349465", negocio="Centro de tratamiento de adicciones",
               sector="clinica veterinaria")
    _prospecto(lanzador, "vascular@x.es", "910004960", negocio="Clínica Madrid Vascular",
               sector="clinica veterinaria")
    elegidos = lanzador.candidatos(MARTES_10_30)
    assert [c["negocio"] for c in elegidos] == ["Clínica Madrid Vascular"]
    assert elegidos[0]["sector"] == "clinica", "Sara no la trata de veterinaria"
