"""Guardias del shim de compatibilidad de api.py (refactor F3).

Verifica que el proxy del modulo `api` mantiene el contrato historico mientras
el monolito se extrae a backend/: nombres usados por tests y qa_e2e siguen
existiendo, las lecturas son en vivo, y monkeypatch sobre `api` parchea el
modulo home en backend/.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

TESTS_DIR = REPO_ROOT / "tests"
QA_E2E = REPO_ROOT / "scripts" / "qa_e2e.py"


@pytest.fixture(scope="session")
def api_module(tmp_path_factory: pytest.TempPathFactory):
    runtime_dir = tmp_path_factory.mktemp("vantelia-shim")
    data_dir = runtime_dir / "data"
    storage_dir = runtime_dir / "storage"
    config_path = runtime_dir / "config.json"
    (data_dir / "demo").mkdir(parents=True)
    storage_dir.mkdir(parents=True)
    (data_dir / "demo" / "info.txt").write_text("Demo shim", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "demo": {
                    "nombre": "Demo Shim",
                    "icono": "AI",
                    "color": "#00b1d9",
                    "bienvenida": "Hola",
                    "allowed_origins": ["http://testserver"],
                    "booking": {"enabled": True, "timezone": "Europe/Madrid", "provider": "internal"},
                }
            }
        ),
        encoding="utf-8",
    )
    os.environ.update(
        {
            "VANTELIA_DATA_DIR": str(data_dir),
            "VANTELIA_STORAGE_DIR": str(storage_dir),
            "VANTELIA_CONFIG_PATH": str(config_path),
            "OPENAI_API_KEY": "",
            "ADMIN_API_TOKEN": "test-admin-token",
            "PORTAL_ADMIN_EMAIL": "admin@example.com",
            "PORTAL_ADMIN_PASSWORD": "test-password-123",
            "REMINDER_RUN_INTERVAL_MINUTES": "0",
            "OUTREACH_DB_PATH": str(storage_dir / "outreach" / "outreach.db"),
            "TK_DB_PATH": str(storage_dir / "tiktok" / "tiktok.db"),
        }
    )
    sys.modules.pop("api", None)
    return importlib.import_module("api")


def _nombres_consumidos() -> set[str]:
    """Todos los atributos de `api` que usan los tests y qa_e2e."""
    nombres: set[str] = set()
    for test_file in sorted(TESTS_DIR.glob("test_*.py")):
        src = test_file.read_text(encoding="utf-8")
        nombres.update(re.findall(r"\bapi_module\.([A-Za-z_]\w*)", src))
    nombres.update(re.findall(r"\bapi\.([A-Za-z_]\w*)", QA_E2E.read_text(encoding="utf-8")))
    return nombres


def test_nombres_usados_por_tests_existen(api_module):
    faltan = sorted(n for n in _nombres_consumidos() if not hasattr(api_module, n))
    assert not faltan, f"El shim de api ha perdido simbolos usados por tests/qa_e2e: {faltan}"


def test_export_map_lecturas_en_vivo(api_module):
    for nombre, home in api_module._EXPORT_MAP.items():
        assert getattr(api_module, nombre) is getattr(home, nombre), (
            f"api.{nombre} no coincide con {home.__name__}.{nombre} (copia desincronizada)"
        )


def test_setattr_parchea_modulo_home(api_module):
    parcheables = [
        (n, m) for n, m in api_module._EXPORT_MAP.items() if callable(getattr(m, n, None))
    ][:5]
    for nombre, home in parcheables:
        original = getattr(home, nombre)
        sentinel = object()
        try:
            setattr(api_module, nombre, sentinel)
            assert getattr(home, nombre) is sentinel, f"setattr(api, {nombre!r}) no llego al home"
            assert getattr(api_module, nombre) is sentinel, f"api.{nombre} no refleja el parche"
        finally:
            setattr(api_module, nombre, original)
        assert getattr(home, nombre) is original
        assert getattr(api_module, nombre) is original


def test_sin_colisiones_reales_entre_homes(api_module):
    """Mismas reglas de exclusion que la construccion de _EXPORT_MAP en api.py."""
    import types

    import api_models

    # Duplicados historicos conocidos (ya existian en el monolito): api.py y
    # api_models definian cada uno su _DEMO_SECTOR_DEFAULTS y DEFAULT_TIMEZONE.
    # El mapa resuelve al home historico (demo_agenda/settings) por orden.
    # OpenAI: llama-index (rag) vs cliente openai (onboarding_utils);
    # EMAIL_RE: regex propio de textnorm vs el de onboarding_utils.
    permitidas: set[str] = {"_DEMO_SECTOR_DEFAULTS", "DEFAULT_TIMEZONE", "OpenAI", "EMAIL_RE"}
    sentinel = object()
    vistos: dict[str, tuple] = {}
    conflictos = []
    for mod in api_module._HOME_MODULES:
        es_router = mod.__name__.startswith("backend.routers")
        for nombre, valor in vars(mod).items():
            if nombre.startswith("__") or nombre in permitidas:
                continue
            if isinstance(valor, types.ModuleType) and valor.__name__.startswith("backend"):
                continue
            if es_router and getattr(api_models, nombre, sentinel) is valor:
                continue
            if nombre in vistos and vistos[nombre][1] is not valor:
                conflictos.append(f"{nombre}: {vistos[nombre][0]} vs {mod.__name__}")
            else:
                vistos.setdefault(nombre, (mod.__name__, valor))
    assert not conflictos, f"Nombres con objetos DISTINTOS en varios modulos home: {conflictos}"


def test_dir_incluye_exportados(api_module):
    visibles = set(dir(api_module))
    ocultos = [n for n in api_module._EXPORT_MAP if n not in visibles]
    assert not ocultos, f"dir(api) no expone simbolos extraidos: {ocultos}"
