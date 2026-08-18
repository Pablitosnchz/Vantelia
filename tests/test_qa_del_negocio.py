"""Lo que el negocio escribe a mano manda sobre lo que deduzcamos nosotros.

Un salon entrego un formulario con sus preguntas y sus respuestas literales. Al
cargarlas y probarlas fallaron tres de seis:

* "¿Cual es vuestro horario?" devolvia los HUECOS LIBRES de hoy, porque la
  deteccion de disponibilidad corria antes que las Q&A del negocio.
* "¿Cerrais por vacaciones?" contestaba leyendo los bloqueos de la agenda.
* "¿Me dais presupuesto para unas mechas?" se lo inventaba la IA, aunque la
  respuesta estaba escrita con la etiqueta "presupuesto": las etiquetas que pide
  el panel no se usaban en ninguna parte.
"""
from __future__ import annotations

import inspect
import json
import uuid

from test_booking_exhaustive import api_module  # noqa: F401


def _guardar_qa(api_module, pregunta, respuesta, etiquetas=()):
    from backend import db, timeutils

    ahora = timeutils._utc_now_iso()
    ident = "qa_" + uuid.uuid4().hex[:10]
    with db._get_db_connection() as connection:
        connection.execute(
            "INSERT INTO kb_qa (id, cliente_id, question, answer, tags_json, created_at, updated_at)"
            " VALUES (?, 'demo', ?, ?, ?, ?, ?)",
            (ident, pregunta, respuesta, json.dumps(list(etiquetas)), ahora, ahora),
        )
        connection.commit()
    return ident


def _borrar_qa(api_module, ident):
    from backend import db

    with db._get_db_connection() as connection:
        connection.execute("DELETE FROM kb_qa WHERE id=?", (ident,))
        connection.commit()


def test_la_pregunta_escrita_se_responde_tal_cual(api_module):
    from backend import rag

    ident = _guardar_qa(api_module, "¿Cuál es vuestro horario?", "Lunes cerrado, martes de 10 a 18:30.")
    try:
        assert rag._match_qa_answer("demo", "cual es vuestro horario?") == "Lunes cerrado, martes de 10 a 18:30."
    finally:
        _borrar_qa(api_module, ident)


def test_las_etiquetas_del_panel_sirven_para_algo(api_module):
    """El panel las pide ("precios, envios"): no pueden ser decorativas."""
    from backend import rag

    ident = _guardar_qa(
        api_module,
        "¿Cuánto me costaría un cambio de color, unas mechas o un balayage?",
        "Necesitamos verte en persona para darte un presupuesto.",
        ["presupuesto", "cuanto cuesta mechas"],
    )
    try:
        respuesta = rag._match_qa_answer("demo", "me podeis dar presupuesto para unas mechas?")
        assert respuesta == "Necesitamos verte en persona para darte un presupuesto."
    finally:
        _borrar_qa(api_module, ident)


def test_una_etiqueta_corta_no_secuestra_la_conversacion(api_module):
    """"cita" aparece en media conversacion: por eso se exigen 5 caracteres."""
    from backend import rag

    ident = _guardar_qa(api_module, "¿Cómo pido cita?", "Desde la web.", ["cita"])
    try:
        assert rag._match_qa_answer("demo", "quiero cancelar mi cita de mañana") is None
    finally:
        _borrar_qa(api_module, ident)


def test_la_etiqueta_casa_por_palabra_completa(api_module):
    from backend import rag

    ident = _guardar_qa(api_module, "¿Hacéis extensiones?", "Si, con cabello natural.", ["extensiones"])
    try:
        assert rag._match_qa_answer("demo", "hola, hacéis extensiones de pelo?") is not None
        # No debe casar dentro de otra palabra.
        assert rag._match_qa_answer("demo", "hola buenas") is None
    finally:
        _borrar_qa(api_module, ident)


def test_las_qa_se_evaluan_antes_que_la_disponibilidad(api_module):
    """Si el salon ha escrito su horario, preguntarlo no puede dar los huecos de hoy."""
    from backend import chat

    fuente = inspect.getsource(chat._process_chat_message)
    posicion_qa = fuente.index("_match_qa_answer")
    posicion_disponibilidad = fuente.index("_message_requests_availability")
    assert posicion_qa < posicion_disponibilidad


def test_las_reglas_por_palabra_clave_siguen_mandando(api_module):
    """Son configuracion explicita igual que las Q&A, y estaban antes por eso."""
    from backend import chat

    fuente = inspect.getsource(chat._process_chat_message)
    assert fuente.index("keywords.match_reply") < fuente.index("_match_qa_answer")


def test_el_marcador_interno_no_cuenta_como_etiqueta(api_module):
    from backend import rag

    class _Fila(dict):
        def __getitem__(self, k):
            return self.get(k, "")

    assert rag._qa_row_tags(_Fila(tags_json='["_starter", "precios"]')) == ["precios"]
    assert rag._qa_row_tags(_Fila(tags_json="no es json")) == []
    assert rag._qa_row_tags(_Fila(tags_json="")) == []
