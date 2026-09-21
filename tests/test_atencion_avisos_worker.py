# -*- coding: utf-8 -*-
"""El worker de recordatorios, conectado a la admisión de salidas.

POR QUE EXISTE
--------------
En la fase 3 el worker solo tenía la puerta PREVIA: preguntaba si el negocio
estaba en pausa antes de empezar cada aviso. No se le instaló turno porque el
diario de envíos identificaba un envío por canal y número de fragmento, y dos
avisos distintos de la misma cita habrían colisionado. Con la identidad por
aviso (negocio, cita, generación, tipo) ya puesta, este capturador se conecta.

Lo que gana y se comprueba aquí:

- una pausa que cae A MITAD de un aviso frena lo que aún no ha salido, y no se
  cuenta como fallo del proveedor;
- ese aviso queda terminal: reactivar no reanuda un envío a medias;
- una respuesta perdida no se repite en la pasada siguiente aunque el ticket
  sea otro, porque la identidad del aviso sobrevive al ticket;
- un envío LENTO no se confunde con una pausa: un ticket vencido cuenta como
  supresión, y la supresión con turno es terminal.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
import smtplib
import uuid

import pytest

from test_atencion_operaciones import operaciones_atencion, _crear_ticket_prueba  # noqa: F401
from test_atencion_persistida import autoridad_atencion  # noqa: F401
from test_atencion_salidas import transporte_atencion  # noqa: F401
from test_atencion_avisos_identidad import avisos_identidad  # noqa: F401


@pytest.fixture
def worker(avisos_identidad, monkeypatch):  # noqa: F811
    """Una cita a la que le toca el recordatorio de 24 h, y el worker listo."""
    from backend import booking, db, timeutils, wa_plantillas

    a = avisos_identidad
    inicio = timeutils._utc_now() + timedelta(hours=24, minutes=20)
    a.cita = "bk_worker_" + uuid.uuid4().hex[:10]
    with db._get_db_connection() as conexion:
        conexion.execute(
            "INSERT INTO bookings (id, cliente_id, nombre, email, telefono, servicio,"
            "booking_date, booking_time, status, provider_status, source, manage_token,"
            "booking_code, created_at, start_at, end_at, timezone) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a.cita, "demo", "Clienta Sintetica", "destino@example.invalid", "",
             "Consulta", inicio.date().isoformat(), inicio.strftime("%H:%M"), "confirmed",
             "internal", "test", "tok_" + uuid.uuid4().hex, "R-WORKER",
             timeutils._utc_now_iso(), inicio.isoformat(),
             (inicio + timedelta(minutes=30)).isoformat(), "Europe/Madrid"),
        )
        conexion.commit()
    monkeypatch.setattr(booking, "_booking_email_enabled", lambda *args: True)

    async def sin_refresco(*args):
        pass

    monkeypatch.setattr(wa_plantillas, "refrescar_pendientes", sin_refresco)
    a.pasada = lambda: asyncio.run(booking._run_booking_reminders())
    a.fila = lambda: booking._get_booking_row_by_id(a.cita)
    return a


def _envios(a):
    return [datos for tipo, datos in a.llamadas if tipo == "send"]


def _pausar():
    from backend import atencion

    estado = atencion.leer_atencion("demo")
    atencion.cambiar_atencion("demo", "pausada", version_esperada=estado["version"],
                              motivo="cierre_temporada", actor="sistema")


def _reactivar():
    from backend import atencion

    estado = atencion.leer_atencion("demo")
    atencion.cambiar_atencion("demo", "activa", version_esperada=estado["version"],
                              motivo="reapertura", actor="sistema")


def _pausar_al_preparar(monkeypatch):
    """La pausa cae DESPUÉS de capturar el turno y ANTES del transporte: justo
    el hueco que la puerta previa no puede ver. Se engancha en algo que solo se
    consulta DENTRO del envío; lo que el worker lee antes caeria en la puerta
    previa y no probaria nada de esto."""
    from backend import booking

    original = booking._channels_reaching_customer

    def _y_pausa(*args, **kwargs):
        _pausar()
        return original(*args, **kwargs)

    monkeypatch.setattr(booking, "_channels_reaching_customer", _y_pausa)


def _entregas(cita):
    from backend import db

    with db._get_db_connection() as conexion:
        return [dict(r) for r in conexion.execute(
            "SELECT * FROM booking_notice_deliveries WHERE booking_id = ?", (cita,))]


def test_el_worker_deja_el_recordatorio_en_el_diario_con_su_identidad(worker):
    worker.pasada()
    assert len(_envios(worker)) == 1, "el recordatorio no ha salido"
    assert worker.fila()["reminder_24h_sent_at"], "el recordatorio salio y no quedo marcado"
    avisos = [op for op in worker.op.consultar_operaciones_atencion("demo", tipo="envio")
              if op.get("clave_intento")]
    assert avisos, "el worker no ha pasado por la admision con identidad de aviso"


def test_una_pausa_a_mitad_del_aviso_lo_frena_y_no_cuenta_como_fallo(worker, monkeypatch):
    _pausar_al_preparar(monkeypatch)
    resultado = worker.pasada()

    assert _envios(worker) == [], "ha salido un email despues de pausar"
    assert resultado.failed == 0, "una pausa se ha contado como fallo del proveedor"
    assert not worker.fila()["reminder_24h_sent_at"], "la cita ha quedado marcada como avisada"
    motivos = [e["reason"] for e in _entregas(worker.cita)]
    assert "atencion_suprimida" in motivos, (
        "la supresion no ha quedado anotada en el diario de entregas: %r" % _entregas(worker.cita))


def test_un_aviso_frenado_a_mitad_no_se_reanuda_al_reactivar(worker, monkeypatch):
    """Ya se habia empezado a preparar: reanudarlo podria mandar la mitad que
    faltaba fuera de contexto. Distinto de la pausa ANTES de empezar, que no
    anota nada y deja salir el aviso si todavia toca."""
    from backend import booking

    original = booking._channels_reaching_customer
    _pausar_al_preparar(monkeypatch)
    worker.pasada()
    monkeypatch.setattr(booking, "_channels_reaching_customer", original)

    _reactivar()
    resultado = worker.pasada()
    assert _envios(worker) == [], "un aviso frenado a mitad ha salido tras reactivar"
    assert resultado.failed == 0


def test_la_respuesta_perdida_no_se_repite_en_la_pasada_siguiente(worker):
    """El SMTP entrega y la respuesta se pierde. La pasada siguiente usa OTRO
    ticket; la identidad del aviso es lo que impide mandarlo dos veces."""
    worker.enviar_error = smtplib.SMTPServerDisconnected("respuesta perdida")
    worker.pasada()
    assert len(_envios(worker)) == 1

    worker.enviar_error = None
    worker.pasada()
    assert len(_envios(worker)) == 1, (
        "la pasada siguiente ha repetido un recordatorio cuyo resultado no se sabia")


def test_un_envio_lento_no_se_confunde_con_una_pausa(worker, monkeypatch):
    """Diez minutos entre capturar el turno y llegar al transporte: la
    vigencia del aviso tiene que cubrirlo, o el recordatorio moriria con la
    etiqueta de una pausa que nunca hubo."""
    from backend import booking

    original = booking._channels_reaching_customer
    retraso = [timedelta(minutes=10)]

    def _lento(*args, **kwargs):
        # DENTRO del envio, ya con el turno capturado: si el retraso cae antes,
        # el ticket nace despues y la vigencia no se llega a poner a prueba (asi
        # paso la primera version de esta prueba, y su mutacion quedo en verde).
        # Una sola vez: cada consulta no es otro retraso.
        if retraso:
            worker.reloj["ahora"] = worker.reloj["ahora"] + retraso.pop()
        return original(*args, **kwargs)

    monkeypatch.setattr(booking, "_channels_reaching_customer", _lento)
    worker.pasada()
    assert len(_envios(worker)) == 1, "un envio lento se ha tratado como supresion"
    motivos = [e["reason"] for e in _entregas(worker.cita)]
    assert "atencion_suprimida" not in motivos, motivos
