# -*- coding: utf-8 -*-
"""La oficina: con que esta cada agente, la bandeja, los presupuestos y los saldos de Tomas.

Lo que vigilan estos tests:
- pintar la sala NO llama al modelo (el "cafe" lo decide el codigo);
- el escaparate (para grabar la sala) no lleva ni un correo ni un telefono;
- un agente que llega a su tope deja de llamar al modelo;
- Tomas avisa si un saldo se acaba en menos de 7 dias, una vez al dia, y nunca toca nada;
- la sala y su API son solo para admin.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import captacion, envios  # noqa: F401

AHORA = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)


@pytest.fixture()
def of(captacion, envios, monkeypatch):  # noqa: F811
    from backend import oficina, settings, setter, timeutils

    monkeypatch.setenv("OUTREACH_TRACKING_SECRET", "secreto-oficina")
    monkeypatch.setattr(settings, "CONSULTA_NOTIFICATION_EMAIL", "pablo@vantelia.test")
    monkeypatch.setattr(timeutils, "_utc_now", lambda: AHORA)
    setter.asegurar_agenda()
    return oficina


class _SinModelo:
    """Si alguien llama al modelo, el test falla."""

    def __init__(self, *a, **k):
        raise AssertionError("se ha llamado al modelo")


def test_pintar_la_sala_no_llama_al_modelo(of, monkeypatch):
    import openai

    monkeypatch.setattr(openai, "OpenAI", _SinModelo)
    estado = of.estado(AHORA)
    ids = [a["id"] for a in estado["agentes"]]
    assert ids == ["sara", "cartero", "seguimiento", "marta", "buzon", "vigilante", "calidad", "tomas", "claude",
                   "astra"]
    for agente in estado["agentes"]:
        assert agente["estado"] in of.ESTADOS and agente["bocadillo"]
    marta = next(a for a in estado["agentes"] if a["id"] == "marta")
    assert marta["estado"] == "fuera" and "Apagada" in marta["bocadillo"]


def test_el_escaparate_no_ensena_datos_de_nadie(of, monkeypatch):
    from backend import setter

    setter.guardar_config(encendida=True)
    setter.entrar(origen="consulta", email="secreto@cliente.es", telefono="600123456", nombre="Ana Secreta",
                  negocio="Peluquería Secreta")
    monkeypatch.setattr(of, "_marta", lambda conn, ahora: of._estado("cafe", "Escribiendo a secreto@cliente.es "
                                                                             "al 600 123 456"))
    texto = repr(of.escaparate(AHORA))
    assert "secreto@cliente.es" not in texto and "600 123 456" not in texto and "Secreta" not in texto


def test_al_llegar_al_tope_no_llama_al_modelo(of, monkeypatch):
    from backend import setter

    class _Uso:
        prompt_tokens, completion_tokens = 2_000_000, 0

    class _Respuesta:
        usage = _Uso()

    assert of.hay_presupuesto("marta", AHORA)
    of.anotar_gasto("marta", "gpt-4.1-mini", _Respuesta(), AHORA)  # 0,80 €
    of.anotar_gasto("marta", "gpt-4.1-mini", _Respuesta(), AHORA)  # 1,60 € > 1 €
    assert not of.hay_presupuesto("marta", AHORA)
    import openai

    monkeypatch.setattr(openai, "OpenAI", _SinModelo)
    monkeypatch.setattr(setter.settings, "OPENAI_API_KEY", "sk-prueba")
    lead = {"negocio": "X"}
    assert "llamada de 15 minutos" in setter.borrador(lead, "¿cuánto cuesta?")


def test_tomas_avisa_si_un_saldo_se_acaba_y_solo_una_vez(of, envios, monkeypatch):  # noqa: F811
    for dias, valor in ((7, 30.0), (4, 20.0), (1, 10.0)):
        of._apuntar_saldo("twilio", valor, "USD", "", AHORA - timedelta(days=dias))
    monkeypatch.setattr(of, "_leer_twilio", lambda cliente: {"valor": 8.0, "unidad": "USD"})
    for nombre in ("_leer_elevenlabs", "_leer_zadarma", "_leer_brevo", "_leer_stripe"):
        monkeypatch.setattr(of, nombre, lambda cliente: {"estado": "sin_clave"})
    saldos = of.revisar_saldos(AHORA, cliente=object())
    assert saldos["twilio"]["dias"] is not None and saldos["twilio"]["dias"] < 7
    assert sum("Twilio" in a[0] for a in envios["avisos"]) == 1
    of.revisar_saldos(AHORA + timedelta(hours=6), cliente=object())
    assert sum("Twilio" in a[0] for a in envios["avisos"]) == 1, "aviso repetido el mismo dia"
    assert saldos["openai"] == {"estado": "sin_recarga"}


def test_openai_resta_el_gasto_a_la_recarga(of, monkeypatch):
    assert of.apuntar_recarga("openai", 50, AHORA - timedelta(days=3))["ok"]
    monkeypatch.setattr(of, "_gasto_openai_trazas", lambda desde: 12.5)
    leido = of._leer_openai(object(), AHORA)
    assert leido["valor"] == 37.5 and "solo el asistente" in leido["detalle"]
    assert not of.apuntar_recarga("stripe", 50)["ok"]


def test_la_firma_de_zadarma_es_la_de_su_libreria(of):
    """Calculada a mano como su libreria oficial: HMAC-SHA1 hex y luego base64."""
    import base64
    import hashlib
    import hmac

    esperado = base64.b64encode(hmac.new(b"secreto", ("/v1/info/balance/" + "" + hashlib.md5(b"").hexdigest())
                                         .encode(), hashlib.sha1).hexdigest().encode()).decode()
    assert of._firma_zadarma("/v1/info/balance/", {}, "clave", "secreto") == "clave:" + esperado


def test_la_sala_y_su_api_son_solo_para_admin(of, client):  # noqa: F811
    client.cookies.clear()
    assert client.get("/admin/oficina/estado").status_code in (401, 403)
    pagina = client.get("/oficina", follow_redirects=False)
    assert pagina.status_code in (302, 303, 307) and "/acceso" in pagina.headers["location"]
    respuesta = client.get("/admin/oficina/estado", headers={"Authorization": "Bearer test-admin-token"})
    assert respuesta.status_code == 200 and respuesta.json()["agentes"]


def test_una_propuesta_repetida_actualiza_la_misma(of):
    primera = of.proponer(agente="marta", tipo="respuesta", ref="st_x", titulo="A", borrador="uno")
    segunda = of.proponer(agente="marta", tipo="respuesta", ref="st_x", titulo="B", borrador="dos")
    assert primera == segunda and [p["borrador"] for p in of.bandeja() if p["ref"] == "st_x"] == ["dos"]
    assert of.resolver(primera, "rechazar")["ok"] and of.resolver(primera, "rechazar")["ok"] is False
