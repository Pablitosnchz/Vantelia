import json
import sys
import asyncio
import inspect

import pytest

from evals import calendario
from scripts import evaluar_asistente as banco

_EJECUTAR_CASO_REAL = banco._ejecutar_caso


@pytest.fixture
def runner(monkeypatch):
    for nombre in ("_preparar_copia", "_comprobar_aislamiento"):
        monkeypatch.setattr(banco, nombre, lambda *a: None)
    monkeypatch.setattr(banco, "_quien_contesta", lambda *a: "agente simulado")
    monkeypatch.setattr(banco, "_ficha_del_negocio", lambda *a: "estilo=conversacional")
    monkeypatch.setattr(banco, "_instalar_captura", lambda: [])
    casos = [{"id": n, "gravedad": "critico", "mensajes": ["el {dia_abierto}"]}
             for n in ("primero", "recuperado", "roto", "sin_fecha", "ajeno")]
    monkeypatch.setattr(banco, "_cargar_casos", lambda: casos)
    monkeypatch.setattr(banco, "_aplica_a_este_negocio", lambda cid, c: c["id"] != "ajeno")
    def resolver(cid, caso):
        if caso["id"] == "sin_fecha":
            raise calendario.CalendarioNoDisponible("sin huecos")
        return ["el 2026-09-17"], {"dia_abierto": "2026-09-17"}
    monkeypatch.setattr(calendario, "resolver_mensajes", resolver)
    llamadas = []
    def ejecutar(cid, caso, dichos, indice):
        intento = 1 + sum(c == caso["id"] for c in llamadas)
        llamadas.append(caso["id"])
        ok = caso["id"] == "primero" or (caso["id"] == "recuperado" and intento == 2)
        return ok, ["respuesta %s %s " % (caso["id"], intento) + "x" * 300], "" if ok else "sin cita"
    monkeypatch.setattr(banco, "_ejecutar_caso", ejecutar)
    return llamadas


def test_json_conserva_ambos_intentos_y_denominadores(runner, monkeypatch, tmp_path):
    destino = tmp_path / "informe.json"
    monkeypatch.setattr(sys, "argv", ["banco", "--cliente", "salon_sintetico", "--db-copia", "falsa",
                                      "--guardar", str(destino)])
    assert banco.main() == 1
    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert datos["cliente"] == "salon_sintetico"
    assert len(datos["sha"]) == 40
    assert datos["configuracion"] == "estilo=conversacional"
    assert datos["inicio_utc"] and datos["fin_utc"]
    assert datos["estado"] == "terminado"
    assert datos["contadores"] == {
        "previstos": 5, "medidos": 3, "no_medidos": 1, "no_aplican": 1,
        "primer_intento_medido": 3, "primer_intento_fallido": 2,
        "ok_primer_intento": 1, "ok_tras_reintento": 1, "reintentos": 2,
        "reintentos_no_medidos": 0,
        "fallos": {"critico": 1, "importante": 0, "deseable": 0},
    }
    por_id = {c["id"]: c for c in datos["casos"]}
    assert [c["estado"] for c in datos["casos"]] == ["ok", "ok", "fallo", "no_medido", "no_aplica"]
    recuperado = por_id["recuperado"]
    assert recuperado["fechas"] == {"dia_abierto": "2026-09-17"}
    assert recuperado["mensajes"] == ["el 2026-09-17"]
    assert [i["ok"] for i in recuperado["intentos"]] == [False, True]
    assert recuperado["intentos"][0]["motivo"] == "sin cita"
    assert recuperado["intentos"][0]["respuestas"] == ["respuesta recuperado 1 " + "x" * 300]
    assert por_id["sin_fecha"]["motivo"] == "sin huecos"
    assert por_id["sin_fecha"]["intentos"] == por_id["ajeno"]["intentos"] == []
    assert runner == ["primero", "recuperado", "recuperado", "roto", "roto"]


def test_sin_guardar_conserva_salida_y_reintentos(runner, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["banco", "--db-copia", "falsa"])
    assert banco.main() == 1
    salida = capsys.readouterr().out
    assert "2 de 3 medidos; 1 no medidos; 1 no aplican; 5 previstos" in salida
    assert "(al segundo intento)" in salida
    assert runner == ["primero", "recuperado", "recuperado", "roto", "roto"]


def test_captura_corta_webhook_de_preparacion_y_avisos_reales(api_module, monkeypatch):
    from backend import booking, emailing, messaging

    salidas = []
    async def salida_async(*args, **kwargs):
        salidas.append("webhook_o_sms")
        return True, "salida"
    def salida_email(*args, **kwargs):
        salidas.append("email")
        return True
    # Restaurar tambien las funciones que el arnes sustituye directamente.
    for nombre in ("_send_whatsapp_text", "_send_whatsapp_list", "_send_whatsapp_buttons",
                   "_send_whatsapp_cta_url", "_send_whatsapp_payload"):
        monkeypatch.setattr(messaging, nombre, getattr(messaging, nombre))
    monkeypatch.setattr(booking, "_send_booking_to_webhook", salida_async)
    monkeypatch.setattr(messaging, "_send_client_sms", salida_async)
    monkeypatch.setattr(emailing, "_send_client_email", salida_email)
    banco._instalar_captura()
    fila = banco._preparar_cita("demo", "34600987001")
    assert fila is not None
    # La preparacion usa send_confirmation=False, pero el nucleo llama webhook.
    assert not salidas
    fila["email"] = "sintetica@example.invalid"
    enviado = booking._send_booking_email(fila, "confirmed")
    assert not inspect.isawaitable(enviado)
    assert enviado is True
    assert asyncio.run(booking._send_booking_sms_reminder(fila, "confirmed")) is True
    assert not salidas


def test_excepcion_conserva_respuestas_ya_emitidas(api_module, monkeypatch):
    from backend import whatsapp

    dichos = ["respuesta de otro caso"]
    async def mensaje(**kwargs):
        dichos.append("mensaje completo antes del error")
        raise ValueError("error sintetico")
    monkeypatch.setattr(whatsapp, "_handle_whatsapp_message", mensaje)
    monkeypatch.setattr(whatsapp, "_wa_clear_flow", lambda *a: None)
    monkeypatch.setattr(banco, "_citas_del_telefono", lambda *a: [])
    ok, respuestas, motivo = banco._ejecutar_caso("demo", {"mensajes": ["hola"]}, dichos, 0)
    assert not ok
    assert respuestas == ["mensaje completo antes del error"]
    assert "error sintetico" in motivo


def test_sin_cita_previa_no_mide_ni_reintenta(runner, api_module, monkeypatch, tmp_path):
    from backend import whatsapp

    destino = tmp_path / "sin_previa.json"
    monkeypatch.setattr(sys, "argv", ["banco", "--db-copia", "falsa", "--guardar", str(destino)])
    monkeypatch.setattr(banco, "_cargar_casos", lambda: [
        {"id": "cancelar", "gravedad": "critico", "con_cita": True,
         "mensajes": ["cancela {codigo}"]}])
    preparaciones = []
    def preparar(*args):
        preparaciones.append(args)
        return None
    monkeypatch.setattr(banco, "_preparar_cita", preparar)
    monkeypatch.setattr(banco, "_ejecutar_caso", _EJECUTAR_CASO_REAL)
    monkeypatch.setattr(whatsapp, "_wa_clear_flow", lambda *a: None)
    async def no_debe_hablar(**kwargs):
        pytest.fail("sin precondicion no debe hablar con el asistente")
    monkeypatch.setattr(whatsapp, "_handle_whatsapp_message", no_debe_hablar)
    assert banco.main() == 1
    datos = json.loads(destino.read_text(encoding="utf-8"))
    caso = datos["casos"][0]
    assert caso["estado"] == "no_medido"
    assert caso["intentos"] == []
    assert "cita previa" in caso["motivo"]
    assert len(preparaciones) == 1
    assert datos["contadores"]["medidos"] == 0
    assert datos["contadores"]["no_medidos"] == 1
    assert datos["contadores"]["reintentos"] == 0
    assert datos["contadores"]["fallos"]["critico"] == 0


def test_destino_invalido_falla_antes_de_copiar_bd(runner, monkeypatch, tmp_path):
    destino = tmp_path / "no_existe" / "informe.json"
    monkeypatch.setattr(sys, "argv", ["banco", "--db-copia", "falsa", "--guardar", str(destino)])
    def no_copiar(*args):
        pytest.fail("debe validar destino antes de preparar la base de datos")
    monkeypatch.setattr(banco, "_preparar_copia", no_copiar)
    with pytest.raises(SystemExit) as error:
        banco.main()
    assert error.value.code == 2
    assert runner == []


def test_interrupcion_conserva_caso_terminado(runner, monkeypatch, tmp_path):
    destino = tmp_path / "parcial.json"
    monkeypatch.setattr(sys, "argv", ["banco", "--db-copia", "falsa", "--guardar", str(destino)])
    ejecutar = banco._ejecutar_caso
    def interrumpir(cid, caso, dichos, indice):
        if caso["id"] == "recuperado":
            raise KeyboardInterrupt()
        return ejecutar(cid, caso, dichos, indice)
    monkeypatch.setattr(banco, "_ejecutar_caso", interrumpir)
    with pytest.raises(KeyboardInterrupt):
        banco.main()
    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert datos["estado"] == "en_curso"
    assert datos["fin_utc"] is None
    assert len(datos["casos"]) == 1
    assert datos["casos"][0]["id"] == "primero"
    assert datos["casos"][0]["intentos"][0]["ok"]
    assert datos["contadores"]["previstos"] == 5
    assert datos["contadores"]["medidos"] == 1


def test_fallo_real_antes_de_reintento_sin_fixture_sigue_contado(runner, api_module, monkeypatch, tmp_path):
    from backend import whatsapp

    destino = tmp_path / "mixto.json"
    monkeypatch.setattr(sys, "argv", ["banco", "--db-copia", "falsa", "--guardar", str(destino)])
    monkeypatch.setattr(banco, "_cargar_casos", lambda: [
        {"id": "cancelar", "gravedad": "critico", "con_cita": True,
         "mensajes": ["cancela {codigo}"]}])
    preparaciones = iter([{"booking_code": "SINTETICO"}, None])
    monkeypatch.setattr(banco, "_preparar_cita", lambda *a: next(preparaciones))
    monkeypatch.setattr(banco, "_ejecutar_caso", _EJECUTAR_CASO_REAL)
    monkeypatch.setattr(banco, "_citas_del_telefono", lambda *a: [])
    monkeypatch.setattr(whatsapp, "_wa_clear_flow", lambda *a: None)
    dichos = []
    monkeypatch.setattr(banco, "_instalar_captura", lambda: dichos)
    async def error_del_asistente(**kwargs):
        dichos.append("respuesta anterior al error")
        raise ValueError("fallo real de la conversacion")
    monkeypatch.setattr(whatsapp, "_handle_whatsapp_message", error_del_asistente)
    assert banco.main() == 1
    datos = json.loads(destino.read_text(encoding="utf-8"))
    caso = datos["casos"][0]
    assert caso["estado"] == "no_medido"
    assert len(caso["intentos"]) == 1
    assert caso["intentos"][0]["ok"] is False
    assert "fallo real de la conversacion" in caso["intentos"][0]["motivo"]
    assert caso["intentos"][0]["respuestas"] == ["respuesta anterior al error"]
    assert datos["contadores"]["primer_intento_medido"] == 1
    assert datos["contadores"]["primer_intento_fallido"] == 1
    assert datos["contadores"]["ok_primer_intento"] == 0
    assert datos["contadores"]["reintentos"] == 0
    assert datos["contadores"]["reintentos_no_medidos"] == 1
    assert datos["contadores"]["no_medidos"] == 1


def test_escritura_atomica_conserva_ultimo_informe(monkeypatch, tmp_path):
    destino = tmp_path / "informe.json"
    destino.write_text('{"conservado": true}', encoding="utf-8")
    def fallo_reemplazo(*args):
        raise OSError("sin permiso sintetico")
    monkeypatch.setattr(banco.os, "replace", fallo_reemplazo)
    with pytest.raises(OSError):
        banco._guardar_informe(str(destino), {"conservado": False})
    assert json.loads(destino.read_text(encoding="utf-8"))["conservado"] is True
    assert list(tmp_path.iterdir()) == [destino]


def test_interrupcion_dentro_del_reintento_conserva_primer_fallo(runner, monkeypatch, tmp_path):
    destino = tmp_path / "reintento_parcial.json"
    monkeypatch.setattr(sys, "argv", ["banco", "--db-copia", "falsa", "--guardar", str(destino)])
    monkeypatch.setattr(banco, "_cargar_casos", lambda: [
        {"id": "recuperado", "gravedad": "critico", "mensajes": ["hola"]}])
    ejecutar = banco._ejecutar_caso
    def interrumpir(cid, caso, dichos, indice):
        if indice >= 1000:
            raise KeyboardInterrupt()
        return ejecutar(cid, caso, dichos, indice)
    monkeypatch.setattr(banco, "_ejecutar_caso", interrumpir)
    with pytest.raises(KeyboardInterrupt):
        banco.main()
    datos = json.loads(destino.read_text(encoding="utf-8"))
    assert datos["estado"] == "en_curso"
    caso = datos["casos"][0]
    assert caso["estado"] == "en_curso"
    assert len(caso["intentos"]) == 1
    assert caso["intentos"][0]["ok"] is False
    assert caso["intentos"][0]["motivo"] == "sin cita"
    assert caso["intentos"][0]["respuestas"] == ["respuesta recuperado 1 " + "x" * 300]
    assert datos["contadores"]["primer_intento_medido"] == 1
    assert datos["contadores"]["primer_intento_fallido"] == 1
    assert datos["contadores"]["medidos"] == datos["contadores"]["no_medidos"] == 0
    assert datos["contadores"]["no_aplican"] == 0
    assert datos["contadores"]["fallos"]["critico"] == 0
