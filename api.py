"""Entrypoint de compatibilidad de Vantelia (`uvicorn api:app`).

El monolito historico vive ahora en backend/ (dominios) y backend/routers/
(endpoints). Este modulo:

1. Purga backend.* si api se reimporta con otro entorno (las fixtures de tests
   hacen sys.modules.pop("api") + import con env aislado).
2. Importa backend.main, que inicializa el runtime, crea `app` y registra
   todos los endpoints en el orden historico.
3. Actua como proxy del namespace plano historico: `api.simbolo` lee EN VIVO
   del modulo home; `monkeypatch.setattr(api, ...)` parchea el modulo home
   (todos los llamadores ven el parche); `dir(api)` expone todo
   (scripts/qa_e2e.py itera dir(api) para anular _send_whatsapp*).
"""
from __future__ import annotations

import sys as _sys

for _stale in [_m for _m in list(_sys.modules) if _m == "backend" or _m.startswith("backend.")]:
    del _sys.modules[_stale]

import os
import types as _types
from typing import Any, Dict

import api_models as _api_models
import onboarding_utils as _onboarding_utils

from backend import (
    agenda as _b_agenda,
    analytics as _b_analytics,
    appstate as _b_appstate,
    billing as _b_billing,
    booking as _b_booking,
    channel_requests as _b_channel_requests,
    chat as _b_chat,
    clients as _b_clients,
    commerce as _b_commerce,
    crm as _b_crm,
    db as _b_db,
    demo_agenda as _b_demo_agenda,
    emailing as _b_emailing,
    growth as _b_growth,
    instagram as _b_instagram,
    main as _b_main,
    messaging as _b_messaging,
    onboarding as _b_onboarding,
    outreach as _b_outreach,
    portal as _b_portal,
    rag as _b_rag,
    security as _b_security,
    settings as _b_settings,
    stripe_gateway as _b_stripe_gateway,
    textnorm as _b_textnorm,
    tiktok as _b_tiktok,
    timeutils as _b_timeutils,
    voice as _b_voice,
    wa_capture as _b_wa_capture,
    whatsapp as _b_whatsapp,
)
from backend.main import app  # noqa: F401  (contrato: uvicorn api:app)
from backend.routers import (
    public_base as _rt_public_base,
    auth_oauth as _rt_auth_oauth,
    onboarding_web as _rt_onboarding_web,
    portal_app as _rt_portal_app,
    billing_web as _rt_billing_web,
    portal_users as _rt_portal_users,
    ui_pages as _rt_ui_pages,
    public_misc as _rt_public_misc,
    admin_core as _rt_admin_core,
    public_booking as _rt_public_booking,
    whatsapp_webhooks as _rt_whatsapp_webhooks,
    admin_ops as _rt_admin_ops,
    admin_growth as _rt_admin_growth,
    admin_outreach as _rt_admin_outreach,
    tracking as _rt_tracking,
    admin_captacion as _rt_admin_captacion,
    voice_web as _rt_voice_web,
    portal_commerce as _rt_portal_commerce,
)

# Modulos home, de mas especifico a mas generico (el primero que define un
# nombre gana en el mapa de exportacion).
_HOME_MODULES: tuple = (
    _b_appstate,
    _rt_public_base, _rt_auth_oauth, _rt_onboarding_web, _rt_portal_app,
    _rt_billing_web, _rt_portal_users, _rt_ui_pages, _rt_public_misc,
    _rt_admin_core, _rt_public_booking, _rt_whatsapp_webhooks, _rt_admin_ops,
    _rt_admin_growth, _rt_admin_outreach, _rt_tracking, _rt_admin_captacion,
    _rt_voice_web, _rt_portal_commerce,
    _b_main, _b_voice, _b_wa_capture, _b_instagram, _b_tiktok, _b_outreach, _b_growth, _b_billing,
    _b_portal, _b_onboarding, _b_whatsapp, _b_chat, _b_booking, _b_demo_agenda, _b_agenda, _b_rag,
    _b_channel_requests, _b_commerce, _b_analytics,
    _b_crm, _b_security, _b_emailing, _b_messaging, _b_stripe_gateway, _b_clients, _b_db,
    _b_timeutils, _b_textnorm, _b_settings, _onboarding_utils, _api_models,
)

_SENTINEL = object()
_EXPORT_MAP: Dict[str, Any] = {}
for _home_mod in _HOME_MODULES:
    _is_router = _home_mod.__name__.startswith("backend.routers")
    for _exported, _val in vars(_home_mod).items():
        # Los alias de submodulos backend (chat, db, agenda...) no son simbolos
        # exportables. Modulos de terceros como `stripe` SI se exportan (los
        # tests los parchean con fakes via este proxy).
        if _exported.startswith("__"):
            continue
        if isinstance(_val, _types.ModuleType) and _val.__name__.startswith("backend"):
            continue
        # Los routers hacen `from api_models import *`: esas copias no son
        # suyas (el home real de un modelo es api_models, y el de una
        # constante compartida, settings).
        if _is_router and getattr(_api_models, _exported, _SENTINEL) is _val:
            continue
        _EXPORT_MAP.setdefault(_exported, _home_mod)


class _ApiCompatModule(_types.ModuleType):
    def __getattr__(self, name: str):
        home = _EXPORT_MAP.get(name)
        if home is None:
            raise AttributeError(f"module 'api' has no attribute {name!r}")
        return getattr(home, name)

    def __setattr__(self, name: str, value: Any) -> None:
        home = _EXPORT_MAP.get(name)
        if home is not None:
            setattr(home, name, value)
            if name in self.__dict__:
                super().__setattr__(name, value)
            return
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        if name in self.__dict__:
            super().__delattr__(name)
            return
        home = _EXPORT_MAP.get(name)
        if home is not None:
            delattr(home, name)
            return
        super().__delattr__(name)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(_EXPORT_MAP))


_sys.modules[__name__].__class__ = _ApiCompatModule


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
