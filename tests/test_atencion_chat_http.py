"""La respuesta HTTP se registra al emitir, no al preparar un borrador."""
import asyncio
import json
from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_atencion_persistida import autoridad_atencion  # noqa: F401
from test_atencion_operaciones import operaciones_atencion  # noqa: F401


async def _peticion_chat_asgi(app, *, session_id="chat_http_prueba", mensaje="hola", send_hook=None,
                            origin="http://testserver", cliente_id="demo"):
    body = json.dumps({"cliente_id": cliente_id, "mensaje": mensaje, "session_id": session_id}).encode("utf-8")
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/chat", "raw_path": b"/chat", "query_string": b"",
        "root_path": "", "headers": [(b"host", b"testserver"), (b"origin", origin.encode()),
            (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 1000), "server": ("testserver", 80)}
    entregado = False
    enviados = []
    async def recibir():
        nonlocal entregado
        if not entregado:
            entregado = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()
    async def enviar(mensaje_asgi):
        if send_hook is not None:
            await send_hook(mensaje_asgi)
        enviados.append(mensaje_asgi)
    await app(scope, recibir, enviar)
    codigo = next(m["status"] for m in enviados if m["type"] == "http.response.start")
    contenido = b"".join(m.get("body", b"") for m in enviados if m["type"] == "http.response.body")
    return codigo, json.loads(contenido), enviados


def _filas_chat_prueba(db, role):
    with closing(db._get_db_connection()) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM chat_messages WHERE cliente_id='demo' AND role=?", (role,))]


def test_pausa_antes_de_cuota_y_proceso_incluso_parcheado(api_module, operaciones_atencion, monkeypatch):
    from backend import chat, db
    from api_models import RespuestaChat

    a = operaciones_atencion
    a.autoridad.cambiar_atencion("demo", "pausada", version_esperada=0, motivo="temporada", actor="sistema")
    llamadas = []
    monkeypatch.setattr(db, "db_check_self_serve_quota", lambda *a: llamadas.append("cuota"))
    async def procesar(**kwargs):
        llamadas.append("proceso")
        return RespuestaChat(respuesta="Borrador", mostrar_formulario=False, session_id=kwargs["session_id"])
    monkeypatch.setattr(chat, "_process_chat_message", procesar)
    codigo, cuerpo, _ = asyncio.run(_peticion_chat_asgi(api_module.app))
    assert codigo == 409 and cuerpo["detail"]["code"] == "ATTENTION_STOPPED"
    assert llamadas == []
    assert len(_filas_chat_prueba(db, "user")) == 1
    assert _filas_chat_prueba(db, "assistant") == []


def test_pausa_al_devolver_borrador_impide_salida_http(api_module, operaciones_atencion, monkeypatch):
    from backend import chat
    from api_models import RespuestaChat

    a = operaciones_atencion
    async def procesar(**kwargs):
        a.autoridad.cambiar_atencion("demo", "pausada", version_esperada=0, motivo="temporada", actor="sistema")
        return RespuestaChat(respuesta="Borrador privado", mostrar_formulario=False, session_id=kwargs["session_id"])
    monkeypatch.setattr(chat, "_process_chat_message", procesar)
    codigo, cuerpo, enviados = asyncio.run(_peticion_chat_asgi(api_module.app))
    assert codigo == 409 and cuerpo["detail"]["code"] == "ATTENTION_STOPPED"
    assert b"Borrador privado" not in b"".join(m.get("body", b"") for m in enviados)


def test_historial_y_uso_solo_despues_del_ultimo_cuerpo_emitido(api_module, operaciones_atencion, monkeypatch):
    from backend import db, textnorm

    llamadas = []
    monkeypatch.setattr(db, "db_check_self_serve_quota", lambda *a: {"plan": "business"})
    monkeypatch.setattr(db, "db_increment_message_usage", lambda *a, **k: llamadas.append(k["kind"]))
    async def al_emitir(mensaje):
        assert _filas_chat_prueba(db, "assistant") == []
        assert llamadas == []
    codigo, cuerpo, _ = asyncio.run(_peticion_chat_asgi(api_module.app, send_hook=al_emitir))
    assert codigo == 200 and cuerpo["respuesta"]
    assert [r["content"] for r in _filas_chat_prueba(db, "assistant")] == [
        textnorm._sanitize_text(cuerpo["respuesta"], allow_multiline=True)]
    assert llamadas == ["bot_reply"]


def test_fallo_asgi_no_cuenta_borrador_como_respuesta(api_module, operaciones_atencion, monkeypatch):
    from backend import db

    llamadas = []
    monkeypatch.setattr(db, "db_check_self_serve_quota", lambda *a: {"plan": "business"})
    monkeypatch.setattr(db, "db_increment_message_usage", lambda *a, **k: llamadas.append(k["kind"]))
    async def caer(mensaje):
        if mensaje["type"] == "http.response.body":
            raise RuntimeError("cuerpo no emitido")
    with pytest.raises(Exception):
        asyncio.run(_peticion_chat_asgi(api_module.app, send_hook=caer))
    assert _filas_chat_prueba(db, "assistant") == []
    assert llamadas == []
    envios = operaciones_atencion.op.consultar_envios_atencion("demo")
    assert len(envios) == 1 and envios[0]["estado"] == "desconocido"


@pytest.mark.parametrize("momento", ["antes", "emision"])
def test_error_autoridad_es_503_sin_respuesta_ni_cuota(api_module, operaciones_atencion, monkeypatch, momento):
    from backend import chat, db
    from api_models import RespuestaChat

    a = operaciones_atencion
    def fallar(*args, **kwargs):
        raise a.autoridad.AtencionNoDisponible("fallo de prueba")
    async def procesar(**kwargs):
        monkeypatch.setattr(a.autoridad, "_leer_atencion_en_transaccion", fallar)
        return RespuestaChat(respuesta="No visible", mostrar_formulario=False, session_id=kwargs["session_id"])
    llamadas = []
    monkeypatch.setattr(db, "db_check_self_serve_quota", lambda *a: {"plan": "business"})
    monkeypatch.setattr(db, "db_increment_message_usage", lambda *a, **k: llamadas.append(1))
    if momento == "antes":
        monkeypatch.setattr(a.autoridad, "_leer_atencion_en_transaccion", fallar)
    else:
        monkeypatch.setattr(chat, "_process_chat_message", procesar)
    codigo, cuerpo, _ = asyncio.run(_peticion_chat_asgi(api_module.app))
    assert codigo == 503 and cuerpo["detail"]["code"] == "ATTENTION_UNAVAILABLE"
    assert llamadas == [] and _filas_chat_prueba(db, "assistant") == []
    assert len(_filas_chat_prueba(db, "user")) == 1


@pytest.mark.parametrize("cambio", ["vence", "pausa_reactiva"])
def test_ticket_viejo_no_emite_aunque_autoridad_este_activa(api_module, operaciones_atencion, monkeypatch, cambio):
    from backend import chat
    from api_models import RespuestaChat

    a = operaciones_atencion
    async def procesar(**kwargs):
        if cambio == "vence":
            a.reloj["ahora"] += timedelta(seconds=121)
        else:
            for version, estado in enumerate(("pausada", "activa")):
                a.autoridad.cambiar_atencion("demo", estado, version_esperada=version, motivo="temporada", actor="sistema")
        return RespuestaChat(respuesta="Viejo", mostrar_formulario=False, session_id=kwargs["session_id"])
    monkeypatch.setattr(chat, "_process_chat_message", procesar)
    codigo, cuerpo, _ = asyncio.run(_peticion_chat_asgi(api_module.app))
    assert codigo == 409 and cuerpo["detail"]["code"] == "ATTENTION_STOPPED"
    assert a.op.consultar_envios_atencion("demo")[0]["estado"] == "suprimido"


def test_admision_visible_antes_de_start_y_ganador_emite_tras_pausa(api_module, operaciones_atencion):
    a = operaciones_atencion
    async def al_emitir(mensaje):
        if mensaje["type"] == "http.response.start":
            assert a.op.consultar_envios_atencion("demo")[0]["estado"] == "en_transito"
            a.autoridad.cambiar_atencion("demo", "pausada", version_esperada=0, motivo="temporada", actor="sistema")
    codigo, cuerpo, _ = asyncio.run(_peticion_chat_asgi(api_module.app, send_hook=al_emitir))
    assert codigo == 200 and cuerpo["respuesta"]
    assert a.op.consultar_envios_atencion("demo")[0]["estado"] == "aceptado"
    assert len(_filas_chat_prueba(a.db, "assistant")) == 1


def test_origin_invalido_conserva_prioridad_sobre_autoridad(api_module, operaciones_atencion, monkeypatch):
    def prohibido(*args, **kwargs):
        pytest.fail("El origen inválido se rechaza antes de consultar atención")
    monkeypatch.setattr(operaciones_atencion.autoridad, "_leer_atencion_en_transaccion", prohibido)
    codigo, _, _ = asyncio.run(_peticion_chat_asgi(api_module.app, origin="https://ajeno.invalid"))
    assert codigo == 403


def test_rag_por_turno_no_reinyecta_borrador_suprimido(api_module, operaciones_atencion, monkeypatch):
    from backend import chat, rag

    a = operaciones_atencion
    motores = []
    compartido = SimpleNamespace(engine=SimpleNamespace(chat=lambda *a: pytest.fail("No usar memoria compartida")),
        message_count=0, last_seen=0)
    monkeypatch.setattr(rag, "_get_or_create_session", lambda *a: compartido)
    monkeypatch.setattr(chat, "decision_del_negocio", lambda *a, **k: None)
    class Motor:
        def __init__(self, historial):
            self.historial = [(m.role.value, m.content) for m in historial]
        def chat(self, mensaje):
            texto = "borrador suprimido" if len(motores) == 1 else "respuesta emitida"
            self.historial.extend([("user", mensaje), ("assistant", texto)])
            if len(motores) == 1:
                a.autoridad.cambiar_atencion("demo", "pausada", version_esperada=0, motivo="temporada", actor="sistema")
            return SimpleNamespace(response=texto)
    def fabricar(**kwargs):
        motor = Motor(kwargs["chat_history"])
        motores.append(motor)
        return motor
    monkeypatch.setattr(rag, "cargar_indice", lambda *a: SimpleNamespace(as_chat_engine=fabricar))
    primero = asyncio.run(_peticion_chat_asgi(api_module.app, mensaje="consulta documental especial"))
    assert primero[0] == 409
    a.autoridad.cambiar_atencion("demo", "activa", version_esperada=1, motivo="temporada", actor="sistema")
    a.reloj["ahora"] += timedelta(microseconds=1)
    segundo = asyncio.run(_peticion_chat_asgi(api_module.app, mensaje="otra consulta documental especial"))
    assert segundo[0] == 200
    assert all("borrador suprimido" not in texto for _, texto in motores[1].historial)
    assert [(r["role"], r["content"]) for r in _filas_chat_prueba(a.db, "assistant")] == [
        ("assistant", "respuesta emitida")]


def test_dos_requests_misma_sesion_no_comparten_borrador_y_libera_lock(api_module, operaciones_atencion, monkeypatch):
    from backend import atencion_chat, chat
    from api_models import RespuestaChat

    procesados = []
    async def procesar(**kwargs):
        procesados.append(kwargs["message"])
        return RespuestaChat(respuesta=kwargs["message"], mostrar_formulario=False, session_id=kwargs["session_id"])
    monkeypatch.setattr(chat, "_process_chat_message", procesar)
    async def carrera():
        dentro, seguir = asyncio.Event(), asyncio.Event()
        async def bloquear(mensaje):
            if mensaje["type"] == "http.response.start":
                dentro.set()
                await seguir.wait()
        primera = asyncio.create_task(_peticion_chat_asgi(api_module.app, mensaje="primera", send_hook=bloquear))
        await asyncio.wait_for(dentro.wait(), timeout=5)
        segunda = asyncio.create_task(_peticion_chat_asgi(api_module.app, mensaje="segunda"))
        await asyncio.sleep(0.05)
        assert procesados == ["primera"]
        seguir.set()
        return await asyncio.gather(primera, segunda)
    resultados = asyncio.run(carrera())
    assert [r[0] for r in resultados] == [200, 200]
    assert [r["content"] for r in _filas_chat_prueba(operaciones_atencion.db, "assistant")] == ["primera", "segunda"]
    assert atencion_chat._CHAT_HTTP_LOCKS == {}


def test_request_esperando_no_rejuvenece_tras_pausa_y_reactivacion(api_module, operaciones_atencion, monkeypatch):
    from backend import atencion_chat, chat
    from api_models import RespuestaChat

    a = operaciones_atencion
    procesados = []
    async def procesar(**kwargs):
        procesados.append(kwargs["message"])
        return RespuestaChat(respuesta=kwargs["message"], mostrar_formulario=False, session_id=kwargs["session_id"])
    monkeypatch.setattr(chat, "_process_chat_message", procesar)
    async def carrera():
        dentro, seguir = asyncio.Event(), asyncio.Event()
        async def bloquear(mensaje):
            if mensaje["type"] == "http.response.start":
                dentro.set()
                await seguir.wait()
        primera = asyncio.create_task(_peticion_chat_asgi(api_module.app, mensaje="primera", send_hook=bloquear))
        await asyncio.wait_for(dentro.wait(), timeout=5)
        segunda = asyncio.create_task(_peticion_chat_asgi(api_module.app, mensaje="segunda"))
        # Esperar un hecho observable: la petición ya espera el lock de sesión.
        for _ in range(200):
            if any(entrada[1] == 2 for entrada in atencion_chat._CHAT_HTTP_LOCKS.values()):
                break
            await asyncio.sleep(0.005)
        assert any(entrada[1] == 2 for entrada in atencion_chat._CHAT_HTTP_LOCKS.values())
        for version, estado in enumerate(("pausada", "activa")):
            a.autoridad.cambiar_atencion("demo", estado, version_esperada=version,
                motivo="temporada", actor="sistema")
        a.reloj["ahora"] += timedelta(seconds=1)
        seguir.set()
        return await asyncio.gather(primera, segunda)
    resultados = asyncio.run(carrera())
    assert [r[0] for r in resultados] == [200, 409]
    assert resultados[1][1]["detail"]["code"] == "ATTENTION_STOPPED"
    assert procesados == ["primera"]
    assert [r["content"] for r in _filas_chat_prueba(a.db, "user")] == ["primera", "segunda"]
    assert [r["content"] for r in _filas_chat_prueba(a.db, "assistant")] == ["primera"]
    assert atencion_chat._CHAT_HTTP_LOCKS == {}


def test_sesion_de_otro_tenant_no_recibe_historial_del_chat(api_module, operaciones_atencion, monkeypatch):
    from backend import chat, rag
    from api_models import RespuestaChat

    a = operaciones_atencion
    peticion = SimpleNamespace(headers={})
    rag._ensure_chat_session_record("sesion_ajena", "negocio_es", peticion)
    rag._record_chat_message(session_id="sesion_ajena", cliente_id="negocio_es", role="user", content="original")
    async def procesar(**kwargs):
        return RespuestaChat(respuesta="Respuesta del otro tenant", mostrar_formulario=False, session_id=kwargs["session_id"])
    monkeypatch.setattr(chat, "_process_chat_message", procesar)
    codigo, _, _ = asyncio.run(_peticion_chat_asgi(api_module.app, session_id="sesion_ajena"))
    assert codigo == 403
    with closing(a.db._get_db_connection()) as conn:
        sesion = conn.execute("SELECT cliente_id,message_count FROM chat_sessions WHERE id='sesion_ajena'").fetchone()
        mensajes = [tuple(r) for r in conn.execute(
            "SELECT cliente_id,role,content FROM chat_messages WHERE session_id='sesion_ajena'")]
    assert tuple(sesion) == ("negocio_es", 1)
    assert mensajes == [("negocio_es", "user", "original")]


def test_entrada_http_conserva_intencion_comercial_existente(api_module, operaciones_atencion):
    from backend import chat

    mensaje = "quiero reservar una cita"
    assert chat._detect_commercial_intent(mensaje) == "booking"
    codigo, _, _ = asyncio.run(_peticion_chat_asgi(api_module.app, mensaje=mensaje))
    assert codigo == 200
    filas = _filas_chat_prueba(operaciones_atencion.db, "user")
    assert len(filas) == 1 and filas[0]["intent"] == "booking"


@pytest.mark.parametrize("momento", ["antes", "despues"])
def test_asiento_ausente_no_finge_permiso_ni_borra_emision(api_module, operaciones_atencion, monkeypatch, momento):
    from backend import atencion_contexto, chat, db
    from api_models import RespuestaChat

    a = operaciones_atencion
    usos = []
    monkeypatch.setattr(db, "db_check_self_serve_quota", lambda *args: {"plan": "business"})
    monkeypatch.setattr(db, "db_increment_message_usage", lambda *args, **kwargs: usos.append(kwargs["kind"]))
    async def procesar(**kwargs):
        if momento == "antes":
            turno = atencion_contexto.contexto_atencion_actual()
            with closing(db._get_db_connection()) as conn, conn:
                conn.execute("DELETE FROM client_attention_tickets WHERE ticket_id=?", (turno.ticket_id,))
        return RespuestaChat(respuesta="Emitida solo si ganó", mostrar_formulario=False, session_id=kwargs["session_id"])
    async def perder_asiento(mensaje):
        if momento == "despues" and mensaje["type"] == "http.response.body" and not mensaje.get("more_body", False):
            with closing(db._get_db_connection()) as conn, conn:
                conn.execute("DELETE FROM client_attention_operations")
    monkeypatch.setattr(chat, "_process_chat_message", procesar)
    codigo, cuerpo, _ = asyncio.run(_peticion_chat_asgi(api_module.app, send_hook=perder_asiento))
    if momento == "antes":
        assert codigo == 503 and cuerpo["detail"]["code"] == "ATTENTION_UNAVAILABLE"
        assert usos == [] and _filas_chat_prueba(a.db, "assistant") == []
    else:
        assert codigo == 200 and usos == ["bot_reply"]
        assert [r["content"] for r in _filas_chat_prueba(a.db, "assistant")] == ["Emitida solo si ganó"]
