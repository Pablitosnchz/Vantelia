# -*- coding: utf-8 -*-
"""El mismo banco mide a otro negocio sin dejar de ser comparable para Alicia.

POR QUE EXISTE
--------------
13-sep-2026. La aceptación del candidato exige medir Alicia y un segundo negocio
con configuración distinta. El banco nació con el salón piloto: sus mensajes
nombran SU catálogo («corte de señora», «mechas», «las cejas») y sus casos exigen
SUS políticas (foto para el presupuesto del alisado, teléfono en el rescate).
Pasado tal cual a otro negocio, cada uno de esos casos sale roto sin que el
asistente haya hecho nada mal: se mide el catálogo, no el asistente.

Dos piezas:
  · `{un_servicio}` en los casos genéricos, resuelto por negocio en
    `evals/negocios.py`. Para Alicia el texto resuelto es EXACTAMENTE el anterior:
    si cambiara, sus mediciones de antes y de después dejarían de compararse.
  · `solo_si` con condiciones sobre los datos del negocio (servicio por nombre o
    categoría, regla activa, teléfono publicado). Para Alicia se cumplen todas, así
    que sus casos aplican igual que antes.
"""
from __future__ import annotations

from datetime import date

import pytest

from evals import calendario


# Los mensajes de Alicia antes de introducir `{un_servicio}`, literales.
ANTES_PARA_ALICIA = {
    "no-dar-la-cita-por-hecha": "quiero cita para un corte de señora",
    "duda-a-media-cita": "quiero cita para un corte de señora",
    "reserva-completa-de-verdad": "hola quiero cita para un corte de señora",
    "no-coge-cita-sin-que-lo-pidan": "cuanto vale un corte de señora?",
    "pregunta-el-dia-en-vez-de-recitar": "hola, quiero pedir cita para un corte de señora",
    "cuanto-tarda-lo-que-ya-ha-elegido": "hola quiero un corte de señora",
}


def _caso(identificador):
    from evals.casos_asistente import CASOS

    return next(c for c in CASOS if c["id"] == identificador)


@pytest.mark.parametrize("identificador,texto", sorted(ANTES_PARA_ALICIA.items()))
def test_para_alicia_el_mensaje_no_cambia(identificador, texto):
    caso = _caso(identificador)
    mensajes, _ = calendario.resolver_mensajes("alicia_rincon_estilistas", caso,
                                               hoy=date(2026, 9, 12),
                                               consultar=lambda dia: ({"17:00"}, {"17:00"}))
    assert mensajes[0] == texto, "el banco de Alicia ya no pregunta lo mismo: no es comparable"


def test_telefono_para_alicia_tampoco_cambia():
    caso = _caso("telefono-si-no-encaja-nada")
    mensajes, fechas = calendario.resolver_mensajes(
        "alicia_rincon_estilistas", caso, hoy=date(2026, 9, 12),
        consultar=lambda dia: ({"17:00"}, {"17:00"}))
    assert mensajes[0] == "quiero cita para un corte de señora el %s" % fechas["dia_abierto_nombre"]


def test_el_segundo_negocio_pide_su_propio_servicio():
    mensajes, _ = calendario.resolver_mensajes("metareview", _caso("reserva-completa-de-verdad"))
    assert mensajes[0] == "hola quiero cita para una sesion estandar"


def test_sin_servicio_declarado_no_se_mide():
    with pytest.raises(calendario.CalendarioNoDisponible):
        calendario.resolver_mensajes("negocio-sin-declarar", _caso("reserva-completa-de-verdad"))


def test_ningun_caso_deja_el_marcador_sin_resolver():
    from evals.casos_asistente import CASOS

    for caso in CASOS:
        if not any("{un_servicio}" in m for m in caso["mensajes"]):
            continue
        mensajes, _ = calendario.resolver_mensajes(
            "alicia_rincon_estilistas", caso, "R-1", hoy=date(2026, 9, 12),
            consultar=lambda dia: ({"17:00", "10:00", "15:00"}, {"17:00", "10:00", "15:00"}))
        assert not any("{" in m for m in mensajes), (caso["id"], mensajes)


# ─── Condiciones sobre los datos del negocio ─────────────────────────────

SALON = [{"nombre": "Mechas corto", "category": "Trabajos de color"},
         {"nombre": "Keratina premium corto", "category": "Alisados"},
         {"nombre": "Corte señora", "category": "Cortes"},
         {"nombre": "Diseño cejas", "category": "Depilaciones"},
         {"nombre": "Pack color raiz y elumen corto", "category": "Packs"},
         {"nombre": "Secado al aire corto", "category": "Peinados"},
         {"nombre": "Acido lactico bio premium-corto medio", "category": "Alisados"},
         {"nombre": "Extensiones adhesivas 1 paquete", "category": "Extensiones"}]
SESIONES = [{"nombre": "Sesion estandar", "category": ""},
            {"nombre": "Consulta de valoracion", "category": ""}]


def _negocio(monkeypatch, catalogo, reglas=(), telefono=""):
    from backend import booking, clients, rules

    monkeypatch.setattr(booking, "_public_services_for_booking", lambda *a, **k: list(catalogo))
    monkeypatch.setattr(rules, "listar", lambda *a, **k: [{"accion": r} for r in reglas])
    monkeypatch.setattr(clients, "call_us_line", lambda *a, **k: telefono)
    monkeypatch.setattr(booking, "no_se_da_precio_de", lambda *a, **k: {"sin": True})
    monkeypatch.setattr(booking, "precios_ocultos", lambda *a, **k: True)


@pytest.mark.parametrize("condicion,esperado", [
    ("tiene_servicio:mechas", True),
    ("tiene_servicio:alisado", True),         # por la categoria "Alisados"
    ("tiene_servicio:acido lactico", True),   # todas las palabras en el mismo servicio
    ("tiene_servicio:manicura", False),
    ("no_tiene_servicio:manicura", True),
    ("tiene_regla:pedir_foto", True),
    ("tiene_regla:pasar_a_humano", False),
    ("telefono_publicado", True),
    (["tiene_servicio:alisado", "tiene_regla:pedir_foto"], True),
    (["tiene_servicio:alisado", "tiene_servicio:manicura"], False),
])
def test_condiciones_en_el_salon(monkeypatch, condicion, esperado):
    from scripts import evaluar_asistente as banco

    _negocio(monkeypatch, SALON, reglas=("pedir_foto", "ofrecer_cita"), telefono="Llama al 625")
    assert banco._aplica_a_este_negocio("salon", {"solo_si": condicion}) is esperado


def test_con_su_catalogo_a_alicia_le_aplican_los_mismos_casos(monkeypatch):
    """Todas las condiciones nuevas se cumplen en un catálogo como el suyo."""
    from evals.casos_asistente import CASOS
    from scripts import evaluar_asistente as banco

    _negocio(monkeypatch, SALON, reglas=("pedir_foto", "ofrecer_cita"), telefono="Llama al 625")
    fuera = [c["id"] for c in CASOS if not banco._aplica_a_este_negocio("alicia", c)
             and "tiene_qa:" not in str(c.get("solo_si")) and "sin_precio_global" != c.get("solo_si")
             and "precios_visibles" not in str(c.get("solo_si"))]
    assert fuera == [], "casos de Alicia que dejarian de medirse: %s" % fuera


def test_en_un_negocio_de_sesiones_quedan_los_genericos(monkeypatch):
    from evals.casos_asistente import CASOS
    from scripts import evaluar_asistente as banco
    from backend import booking

    _negocio(monkeypatch, SESIONES)
    monkeypatch.setattr(booking, "no_se_da_precio_de", lambda *a, **k: {})
    monkeypatch.setattr(booking, "precios_ocultos", lambda *a, **k: False)
    aplican = {c["id"] for c in CASOS if banco._aplica_a_este_negocio("sesiones", c)}

    for generico in ("reserva-completa-de-verdad", "cancelar-de-verdad", "cambiar-la-hora-de-verdad",
                     "no-dar-la-cita-por-hecha", "servicio-que-no-existe", "sinsentido-no-rompe"):
        assert generico in aplican, generico
    for del_salon in ("frase-partida", "no-negar-servicio-que-existe", "presupuesto-alisado-pide-foto",
                      "telefono-si-no-encaja-nada", "dice-que-si-y-acaba-en-cita", "que-servicios-hay"):
        assert del_salon not in aplican, del_salon


# ─── Sin los datos del negocio en esta máquina no se mide ────────────────

def test_sin_datos_rag_locales_no_se_mide(monkeypatch, tmp_path, capsys):
    """13-sep-2026: metareview solo tiene sus datos en el servidor. Cada mensaje
    reventaba con «No hay datos configurados» y el banco apuntó 12 FALLOS del
    asistente que no existían. Eso no es medir: se para antes de conversar."""
    import json
    import sys

    from backend import settings
    from scripts import evaluar_asistente as banco

    informe = tmp_path / "informe.json"
    monkeypatch.setattr(sys, "argv", ["banco", "--cliente", "sin-datos", "--db-copia",
                                      str(tmp_path / "copia.db"), "--guardar", str(informe)])
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    for nombre in ("_preparar_copia", "_comprobar_aislamiento"):
        monkeypatch.setattr(banco, nombre, lambda *a: None)
    monkeypatch.setattr(banco, "_cargar_casos", lambda: [{"id": "x", "gravedad": "critico",
                                                         "mensajes": ["hola"]}])
    ejecutados = []
    monkeypatch.setattr(banco, "_ejecutar_caso", lambda *a, **k: ejecutados.append(a) or (False, [], ""))

    assert banco.main() == 2
    assert ejecutados == [], "se ha conversado sin los datos del negocio"
    assert "NO MEDIBLE" in capsys.readouterr().out
    datos = json.loads(informe.read_text(encoding="utf-8"))
    assert datos["estado"] == "no_medible"
    assert datos["contadores"]["fallos"] == {"critico": 0, "importante": 0, "deseable": 0}
