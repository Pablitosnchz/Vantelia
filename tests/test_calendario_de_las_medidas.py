from datetime import date

import pytest

from evals import calendario
from test_booking_exhaustive import api_module  # noqa: F401


@pytest.mark.parametrize("hoy,esperado", [(date(2026, 9, 12), "2026-09-15"),
                                         (date(2026, 9, 15), "2026-09-16")])
def test_busca_dia_abierto_en_sabado_y_martes(hoy, esperado):
    def consultar(dia):
        horas = set() if date.fromisoformat(dia).weekday() in (6, 0) else {"15:00"}
        return horas, horas
    caso = {"mensajes": ["el {dia_abierto}", "{dia_abierto_nombre}", "{codigo}"],
            "horas_calendario": ["15:00"]}
    mensajes, datos = calendario.resolver_mensajes("salon", caso, "ABC", hoy=hoy, consultar=consultar)
    assert mensajes[0] == "el " + esperado
    assert mensajes[2] == "ABC"
    assert datos["dia_abierto"] == esperado
    assert mensajes[1] == date.fromisoformat(esperado).strftime("%d/%m/%Y")


def test_un_dia_lleno_no_es_un_dia_cerrado():
    def consultar(dia):
        return (set(), set()) if dia == "2026-09-14" else ({"15:00"}, set())
    mensajes, _ = calendario.resolver_mensajes("salon", {"mensajes": ["{dia_cerrado}"]},
        hoy=date(2026, 9, 12), consultar=consultar)
    assert mensajes == ["2026-09-14"]


def test_exige_todas_las_horas_y_no_pasa_sin_huecos():
    with pytest.raises(calendario.CalendarioNoDisponible):
        calendario.buscar_dia_con_huecos(lambda d: ["10:00"], date(2026, 9, 12),
                                        horas=["10:00", "11:00"], dias=2)


def test_manana_literal_solo_si_el_caso_lo_prueba_explicitamente():
    from evals.casos_asistente import CASOS
    from scripts.humo import CASOS as HUMOS

    for caso in CASOS + HUMOS:
        if any("manana" in m.lower().replace("ñ", "n") for m in caso["mensajes"]):
            assert caso.get("fecha_relativa_intencional"), caso["id"]


def test_no_borra_el_codigo_antes_de_preparar_la_cita():
    caso = {"mensajes": ["cancela {codigo}"]}
    mensajes, _ = calendario.resolver_mensajes("salon", caso)
    assert mensajes == caso["mensajes"]
    assert calendario.resolver_mensajes("salon", caso, "ABC")[0] == ["cancela ABC"]


def test_sin_huecos_no_inventa_dia():
    with pytest.raises(calendario.CalendarioNoDisponible):
        calendario.resolver_mensajes("salon", {"mensajes": ["{dia_abierto}"]},
            hoy=date(2026, 9, 12), consultar=lambda dia: ({"15:00"}, set()))


@pytest.mark.parametrize("dia", [12, 15])
def test_fixture_compartida_con_reloj_en_sabado_y_martes(api_module, monkeypatch, dia):
    from datetime import datetime, timezone
    from backend import agenda, timeutils
    from calendario_de_pruebas import proximo_dia_con_hueco

    ahora = datetime(2026, 9, dia, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(timeutils, "_utc_now", lambda: ahora)
    fecha = proximo_dia_con_hueco("demo")
    assert date.fromisoformat(fecha) > ahora.date()
    assert {"10:00", "11:00", "12:00"} <= set(
        agenda._build_slots_for_day("demo", fecha, duration_minutes=30))


@pytest.mark.parametrize("disponible", [True, False])
def test_runner_congela_fecha_y_no_mide_sin_calendario(monkeypatch, capsys, disponible):
    import sys
    from scripts import evaluar_asistente as banco

    caso = {"id": "prueba", "gravedad": "critico", "mensajes": ["{dia_abierto}", "{codigo}"]}
    monkeypatch.setattr(sys, "argv", ["banco", "--db-copia", "copia-simulada"])
    for nombre in ("_preparar_copia", "_comprobar_aislamiento"):
        monkeypatch.setattr(banco, nombre, lambda *a: None)
    for nombre in ("_quien_contesta", "_ficha_del_negocio"):
        monkeypatch.setattr(banco, nombre, lambda *a: "simulado")
    monkeypatch.setattr(banco, "_instalar_captura", lambda: [])
    monkeypatch.setattr(banco, "_cargar_casos", lambda: [caso])
    monkeypatch.setattr(banco, "_aplica_a_este_negocio", lambda *a: True)
    resoluciones, ejecuciones = [], []
    resolver = calendario.resolver_mensajes
    def preparar(cid, datos):
        resoluciones.append(cid)
        return resolver(cid, datos, hoy=date(2026, 9, 12),
            consultar=lambda dia: ({"15:00"}, {"15:00"} if disponible else set()))
    monkeypatch.setattr(calendario, "resolver_mensajes", preparar)
    def ejecutar(cid, datos, dichos, indice):
        ejecuciones.append(datos["mensajes"])
        return len(ejecuciones) == 2, [], "primer intento fallido"
    monkeypatch.setattr(banco, "_ejecutar_caso", ejecutar)
    assert banco.main() == (0 if disponible else 1)
    assert len(resoluciones) == 1
    if disponible:
        assert ejecuciones == [["2026-09-13", "{codigo}"]] * 2
    else:
        assert ejecuciones == []
        assert "NO MEDIDO" in capsys.readouterr().out


@pytest.mark.parametrize("hoy,objetivo", [(date(2026, 9, 12), "2026-09-23"),
                                         (date(2026, 12, 28), "2027-01-09")])
def test_fecha_del_guion_vuelve_al_dia_validado(monkeypatch, hoy, objetivo):
    from datetime import datetime
    from backend import textnorm

    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(hoy.year, hoy.month, hoy.day, 12, tzinfo=tz)

    monkeypatch.setattr(textnorm, "datetime", Reloj)
    caso = {"mensajes": ["el {dia_abierto_nombre} a las 10"], "horas_calendario": ["10:00"]}
    mensajes, datos = calendario.resolver_mensajes("salon", caso, hoy=hoy,
        consultar=lambda dia: ({"10:00"}, {"10:00"} if dia == objetivo else set()))
    assert textnorm._extract_date_from_text(mensajes[0], "Europe/Madrid") == datos["dia_abierto"]


@pytest.mark.parametrize("marcador", ["dia_abierto", "dia_cerrado"])
def test_horizonte_rechazado_es_no_medido(marcador):
    from fastapi import HTTPException

    def consultar(dia):
        if dia > "2026-09-27":
            raise HTTPException(400, "Fuera del plazo máximo de reserva")
        return {"10:00"}, set()

    with pytest.raises(calendario.CalendarioNoDisponible):
        calendario.resolver_mensajes("salon", {"mensajes": ["{" + marcador + "}"]},
            hoy=date(2026, 9, 12), consultar=consultar)
