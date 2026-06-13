"""Recorrido real de navegador por las pantallas principales del portal cliente."""
from __future__ import annotations

import importlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[1]
CID = "qa_browser"
EMAIL = "owner.browser@example.com"
PASSWORD = "browser-pass-123"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_server(base_url: str) -> None:
    for _ in range(100):
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("El servidor temporal no arranco a tiempo.")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vantelia-browser-qa-") as raw_runtime:
        runtime = Path(raw_runtime)
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        data_dir = runtime / "data"
        storage_dir = runtime / "storage"
        config_path = runtime / "config.json"
        (data_dir / CID).mkdir(parents=True)
        storage_dir.mkdir()
        (data_dir / CID / "info.txt").write_text(
            "SERVICIOS Y PRECIOS:\nPREGUNTAS FRECUENTES:\n", encoding="utf-8"
        )
        config_path.write_text(
            json.dumps(
                {
                    CID: {
                        "nombre": "Cliente Browser QA",
                        "allowed_origins": [base_url],
                        "plan": "business",
                        "subscription": {"plan": "business", "status": "active"},
                        "booking": {
                            "enabled": True,
                            "timezone": "Europe/Madrid",
                            "slot_minutes": 15,
                            "day_start": "09:00",
                            "day_end": "18:00",
                            "closed_weekdays": [6],
                            "provider": "internal",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "VANTELIA_DATA_DIR": str(data_dir),
                "VANTELIA_STORAGE_DIR": str(storage_dir),
                "VANTELIA_CONFIG_PATH": str(config_path),
                "OPENAI_API_KEY": "",
                "APP_BASE_URL": base_url,
                "PORTAL_ADMIN_EMAIL": "admin.browser@example.com",
                "PORTAL_ADMIN_PASSWORD": "admin-browser-pass-123",
                "PORTAL_COOKIE_DOMAIN": "",
                "REMINDER_RUN_INTERVAL_MINUTES": "0",
                "WHATSAPP_ACCESS_TOKEN": "",
                "SMTP_HOST": "",
            }
        )
        os.environ.update(env)
        sys.path.insert(0, str(REPO_ROOT))
        sys.modules.pop("api", None)
        api = importlib.import_module("api")
        api._create_user(
            email=EMAIL,
            password=PASSWORD,
            role="client",
            display_name="Owner Browser QA",
            cliente_id=CID,
            portal_role="owner",
        )
        from api_models import PortalLocationPayload
        from backend import agenda

        agenda._create_portal_location(
            CID, PortalLocationPayload(name="Centro Browser B", address="Calle QA 2")
        )

        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            _wait_server(base_url)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                console_errors = []
                service_responses = []
                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on(
                    "response",
                    lambda response: service_responses.append((response.request.method, response.status, response.url))
                    if "/auth/services" in response.url
                    else None,
                )

                page.goto(f"{base_url}/acceso")
                page.locator("#email").fill(EMAIL)
                page.locator("#password").fill(PASSWORD)
                page.locator("#loginBtn").click()
                page.wait_for_url("**/app")

                page.locator('.nav-item[data-tab="servicios"]').click()
                page.locator("#servicioNewBtn").click()
                page.locator("#svcNombre").fill("Servicio Browser Retencion")
                page.locator("#svcDuracion").fill("45")
                page.locator("#svcPrecio").fill("75")
                page.locator("#svcPaymentMode").select_option("payment_required")
                page.locator("#svcPaymentType").select_option("preauth")
                page.locator("#svcSaveBtn").click()
                try:
                    page.wait_for_function(
                        "() => !document.getElementById('serviceDrawer').classList.contains('open')"
                    )
                    page.locator("#serviciosList .panel-card", has_text="Servicio Browser Retencion").wait_for()
                except Exception as exc:
                    toast = page.locator("#toast").text_content()
                    raise AssertionError(
                        f"No se pudo guardar el servicio. Toast={toast!r}; responses={service_responses}"
                    ) from exc

                page.locator("#serviciosList .panel-card", has_text="Servicio Browser Retencion").get_by_text(
                    "Editar", exact=True
                ).click()
                page.locator("#svcLocationsWrap").wait_for(state="visible")
                assert page.locator("#svcLocationsList [data-loc]").count() == 2
                assert page.locator("#svcPaymentType").input_value() == "preauth"
                page.locator("#serviceClose").click()

                page.locator('.nav-item[data-tab="ventas"]').click()
                page.get_by_role("heading", name="Ventas", exact=True).wait_for()
                page.locator('.nav-item[data-tab="informes"]').click()
                page.get_by_role("heading", name="Informes", exact=True).wait_for()
                browser.close()

                if console_errors:
                    raise AssertionError(f"Errores de consola: {console_errors}")
            print("PASS: login, nuevo servicio, Retencion, editar, centros, Ventas e Informes")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
