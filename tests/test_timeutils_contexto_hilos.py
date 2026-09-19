"""Contrato de contexto de _to_thread con su código real y sin cargar settings."""
import asyncio
import importlib.util
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def timeutils_aislado(monkeypatch):
    backend_sintetico = ModuleType("backend")
    backend_sintetico.settings = SimpleNamespace(PORTAL_SESSION_HOURS=1)
    monkeypatch.setitem(sys.modules, "backend", backend_sintetico)
    ruta = Path(__file__).resolve().parents[1] / "backend" / "timeutils.py"
    spec = importlib.util.spec_from_file_location("timeutils_contexto_prueba", str(ruta))
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_propaga_contexto_argumentos_y_resultado(timeutils_aislado):
    contexto = ContextVar("contexto_argumentos", default="sin-contexto")
    resultado = object()

    def trabajador(posicional, *, nombrado):
        return contexto.get(), posicional, nombrado, threading.get_ident()

    async def escenario():
        contexto.set("llamador")
        recibido = await timeutils_aislado._to_thread(trabajador, 7, nombrado=resultado)
        assert recibido[:3] == ("llamador", 7, resultado)
        assert recibido[3] != threading.get_ident()

    asyncio.run(escenario())


def test_dos_tareas_concurrentes_reciben_sus_contextos(timeutils_aislado):
    contexto = ContextVar("contexto_concurrente", default="raiz")
    barrera = threading.Barrier(2, timeout=10)

    def trabajador():
        barrera.wait()
        return contexto.get()

    async def tarea(valor):
        contexto.set(valor)
        recibido = await timeutils_aislado._to_thread(trabajador)
        return recibido, contexto.get()

    async def escenario(ejecutor):
        asyncio.get_running_loop().set_default_executor(ejecutor)
        recibidos = await asyncio.gather(tarea("primera"), tarea("segunda"))
        assert recibidos == [("primera", "primera"), ("segunda", "segunda")]
        assert contexto.get() == "raiz"

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        asyncio.run(escenario(ejecutor))


def test_cambios_del_trabajador_no_contaminan_llamador_ni_hilo_reutilizado(timeutils_aislado):
    contexto = ContextVar("contexto_reutilizado", default="sin-contexto")

    def modificar():
        anterior = contexto.get()
        contexto.set("cambio-del-trabajador")
        return anterior, threading.get_ident()

    async def escenario(ejecutor):
        asyncio.get_running_loop().set_default_executor(ejecutor)
        contexto.set("primer-llamador")
        primero = await timeutils_aislado._to_thread(modificar)
        tras_primero = contexto.get()
        contexto.set("segundo-llamador")
        segundo = await timeutils_aislado._to_thread(lambda: (contexto.get(), threading.get_ident()))
        assert primero[1] == segundo[1]  # El mismo hilo debe quedar limpio entre llamadas.
        assert (primero[0], tras_primero, segundo[0], contexto.get()) == (
            "primer-llamador", "primer-llamador", "segundo-llamador", "segundo-llamador")

    with ThreadPoolExecutor(max_workers=1) as ejecutor:
        asyncio.run(escenario(ejecutor))


def test_propaga_la_excepcion_sin_filtrar_contexto_del_trabajador(timeutils_aislado):
    contexto = ContextVar("contexto_excepcion", default="sin-contexto")
    fallo = ValueError("fallo del trabajador")
    observado = []

    def fallar():
        observado.append(contexto.get())
        contexto.set("cambio-antes-del-error")
        raise fallo

    async def escenario(ejecutor):
        asyncio.get_running_loop().set_default_executor(ejecutor)
        contexto.set("llamador")
        with pytest.raises(ValueError) as captura:
            await timeutils_aislado._to_thread(fallar)
        siguiente = await timeutils_aislado._to_thread(contexto.get)
        assert captura.value is fallo
        assert (observado, contexto.get(), siguiente) == (["llamador"], "llamador", "llamador")

    with ThreadPoolExecutor(max_workers=1) as ejecutor:
        asyncio.run(escenario(ejecutor))
