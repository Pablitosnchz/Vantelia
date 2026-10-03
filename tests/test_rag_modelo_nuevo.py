"""El RAG tiene que aceptar el CHAT_MODEL de produccion aunque llama-index no lo conozca.

3-oct-2026: con `CHAT_MODEL=gpt-4.1-mini` (desde el 25-sep), lo que un huesped de Cap
Rocat escribia sin casar con ninguna regla acababa en "ahora mismo no he podido procesar
tu mensaje": la version fijada de llama-index-llms-openai (0.1.31) rechaza los nombres de
modelo que no estan en su lista. No hace falta llamar a OpenAI para verlo: revienta al
pedir los datos del modelo (`metadata`), que es lo primero que hace el motor de consultas.
"""
from __future__ import annotations

import pytest
from llama_index.llms.openai import OpenAI
from llama_index.llms.openai import utils as openai_utils

from backend import rag


@pytest.fixture
def lista_original(monkeypatch):
    monkeypatch.setattr(openai_utils, "ALL_AVAILABLE_MODELS", dict(openai_utils.ALL_AVAILABLE_MODELS))
    monkeypatch.setattr(openai_utils, "CHAT_MODELS", dict(openai_utils.CHAT_MODELS))


def test_el_modelo_de_produccion_funciona_en_el_rag(lista_original):
    rag._registrar_modelo_en_llama_index("gpt-4.1-mini")

    datos = OpenAI(model="gpt-4.1-mini", api_key="sk-test").metadata

    assert datos.context_window == 1047576
    assert datos.is_chat_model is True


def test_sin_registrar_llama_index_lo_rechaza(lista_original):
    """El fallo de produccion, tal cual: si este test deja de fallar es que la libreria
    ya conoce el modelo y el registro sobra."""
    openai_utils.ALL_AVAILABLE_MODELS.pop("gpt-4.1-mini", None)
    with pytest.raises(ValueError, match="Unknown model"):
        OpenAI(model="gpt-4.1-mini", api_key="sk-test").metadata


def test_un_modelo_que_ya_conoce_no_se_toca(lista_original):
    antes = openai_utils.ALL_AVAILABLE_MODELS["gpt-4o-mini"]
    rag._registrar_modelo_en_llama_index("gpt-4o-mini")
    assert openai_utils.ALL_AVAILABLE_MODELS["gpt-4o-mini"] == antes


def test_un_modelo_desconocido_cualquiera_se_registra_con_contexto_prudente(lista_original):
    rag._registrar_modelo_en_llama_index("gpt-9-nano")
    assert OpenAI(model="gpt-9-nano", api_key="sk-test").metadata.context_window == 128000
