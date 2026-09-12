"""Caducidad, corrupción y escrituras antiguas fallan sin recuperar permisos."""
import pytest


@pytest.fixture
def conversacion(api_module):
    from backend import reserva
    estado = reserva.cargar("snapshot-prueba", "web:sesion")
    estado.intencion = "reservar"
    reserva.guardar("snapshot-prueba", "web:sesion", estado)
    yield estado
    reserva.olvidar("snapshot-prueba", "web:sesion")


def test_olvidar_impide_resucitar_una_version_antigua(conversacion):
    from backend import reserva, conversation_state
    reserva.olvidar("snapshot-prueba", "web:sesion")
    conversacion.servicio = "Servicio obsoleto"
    with pytest.raises(conversation_state.ConversationStateConflict):
        reserva.guardar("snapshot-prueba", "web:sesion", conversacion)
    assert reserva.cargar("snapshot-prueba", "web:sesion").servicio == ""


@pytest.mark.parametrize("cambio", ["caducidad", "corrupto", "formato", "tipo"])
def test_snapshot_no_valido_no_recupera_aceptacion(conversacion, cambio):
    from backend import reserva, db
    p = reserva.preparar_propuesta_servicio(conversacion, servicio_id="diag", nombre="Diagnóstico",
        origen="regla:prueba", revision_config="v1")
    reserva.marcar_propuesta_ofrecida(conversacion, p.id, "acuse")
    reserva.responder_propuesta_servicio(conversacion, p.id, "acepta", revision_config="v1")
    reserva.guardar("snapshot-prueba", "web:sesion", conversacion)
    columna, valor = {"caducidad": ("expires_at", 0), "corrupto": ("payload_json", "{"),
                     "formato": ("formato", 999), "tipo": ("payload_json", '{"hecho":"si"}') }[cambio]
    with db._get_db_connection() as conn:
        conn.execute("UPDATE conversation_states SET " + columna + "=? WHERE cliente_id=?",
                     (valor, "snapshot-prueba"))
        conn.commit()
    recuperado = reserva.cargar("snapshot-prueba", "web:sesion")
    assert recuperado.propuesta_servicio is None
    assert not recuperado.hecho
    if cambio == "formato":
        from backend import conversation_state
        with pytest.raises(conversation_state.ConversationStateConflict):
            reserva.guardar("snapshot-prueba", "web:sesion", recuperado)


def test_escritor_caducado_no_resucita_tras_limpieza(conversacion, monkeypatch):
    from backend import reserva, conversation_state
    ahora = conversacion.tocado + reserva.CADUCA_EN * 3
    conversation_state.purge_conversation_states(before=ahora - reserva.CADUCA_EN)
    monkeypatch.setattr(reserva.time, "time", lambda: ahora)
    with pytest.raises(conversation_state.ConversationStateConflict):
        reserva.guardar("snapshot-prueba", "web:sesion", conversacion)


def test_borrar_tenant_limpia_sus_snapshots_y_respeta_al_otro(api_module):
    from backend import reserva, clients, conversation_state
    for tenant in ("snapshot_borrar", "snapshot_conservar"):
        estado = reserva.cargar(tenant, "web:misma")
        estado.servicio = "Servicio de " + tenant
        reserva.guardar(tenant, "web:misma", estado)
    try:
        clients._purge_client_data("snapshot_borrar")
        assert conversation_state.read_conversation_state("snapshot_borrar", "web", "misma") is None
        assert reserva.cargar("snapshot_conservar", "web:misma").servicio == "Servicio de snapshot_conservar"
    finally:
        reserva.olvidar("snapshot_conservar", "web:misma")
