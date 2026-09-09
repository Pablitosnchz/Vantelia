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
    # OJO Windows: el temporal se borra A MANO y sin quejarse. Con
    # TemporaryDirectory, uvicorn suelta el SQLite mas tarde que el borrado y el
    # script acababa en error DESPUES de haber dicho PASS.
    raw_runtime = tempfile.mkdtemp(prefix="vantelia-browser-qa-")
    try:
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
                "WEBHOOK_DEFAULT": "",
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

        # Catalogo y una cita para probar la agenda: escribir el servicio (en vez de
        # buscarlo en un desplegable de 186) y estirar la cita arrastrando su borde.
        import asyncio
        import datetime as _dt

        from backend import booking as _booking, db as _db

        with _db._get_db_connection() as _cx:
            _cols = [r[1] for r in _cx.execute("PRAGMA table_info(services)")]
            _campo = "name" if "name" in _cols else "nombre"
            for _slug, _nombre, _dur, _precio in (
                ("mechas_balayage_corto", "Mechas o balayage-corto", 120, 8500),
                ("mechas_balayage_largo", "Mechas o balayage-largo", 240, 13500),
                ("corte_senora", "Corte senora", 20, 1800),
            ):
                _cx.execute(
                    "INSERT OR REPLACE INTO services (cliente_id, slug, %s, duration_minutes,"
                    " price_cents, is_active, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,1,datetime('now'),datetime('now'))" % _campo,
                    (CID, _slug, _nombre, _dur, _precio),
                )
            _cx.commit()

        # El tenant cierra los domingos: la cita se pone en el primer dia que abre,
        # y el navegador avanza los dias que hagan falta.
        # Manyana, no hoy: si el QA corre pasadas las 10:00 la cita seria pasada y
        # el nucleo la rechaza (bien rechazada).
        _hoy = _dt.date.today()
        _dias = 1
        while (_hoy + _dt.timedelta(days=_dias)).weekday() == 6:
            _dias += 1
        _fecha_cita = (_hoy + _dt.timedelta(days=_dias)).isoformat()
        dias_hasta_la_cita = _dias
        _emp = agenda._resolve_employee_for_booking(CID, "", require_active=False)
        _cita = asyncio.new_event_loop().run_until_complete(
            _booking._create_booking_core(
                CID, employee_row=_emp, nombre="Clienta Arrastre", email="",
                telefono="600000222", servicio="Corte senora", booking_date=_fecha_cita,
                booking_time="10:00", notas="", source="portal_manual",
                send_confirmation=False,
            )
        )
        assert agenda._booking_row_duration_min(_cita, CID) == 20

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
                # Una EXCEPCION de JS no siempre llega como console.error, y es peor:
                # corta el render a medias. El 9-sep-2026 un "slotMin is not defined"
                # dejo la vista Dia SIN CITAS pintadas y este QA lo daba por bueno.
                page.on("pageerror", lambda err: console_errors.append("pageerror: %s" % err))
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
                page.get_by_role("heading", name="Resumen operativo", exact=True).wait_for()
                assert page.locator('.nav-item[data-tab="overview"]').count() == 0
                assert page.locator('.nav-item[data-tab="informes"]').count() == 1
                assert page.get_by_role("heading", name="Accesos rápidos", exact=True).count() == 0
                assert page.get_by_role("heading", name="Probar asistente", exact=True).count() == 0

                page.locator('.nav-item[data-tab="servicios"]').click()
                page.locator("#page-servicios.active").wait_for()
                page.locator("#servicioNewBtn").click()
                page.locator("#svcNombre").fill("Servicio Browser Retencion")
                page.locator("#svcDuracion").fill("45")
                page.locator("#svcPrecio").fill("75")
                # El cobro ya no son dos desplegables sueltos: se elige UNA opcion en
                # lenguaje del negocio y la UI rellena mode/type (campos ocultos). Este
                # QA llevaba roto desde ese redisenyo -select_option sobre un input
                # hidden no puede funcionar- y nadie lo vio porque no va en pytest.
                page.locator("#svcCobro").select_option("retencion")
                assert page.locator("#svcPaymentMode").input_value() == "payment_required"
                assert page.locator("#svcPaymentType").input_value() == "preauth"
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
                page.locator("#page-ventas.active").wait_for()
                page.get_by_role("heading", name="Ventas", exact=True).wait_for()
                page.locator('.nav-item[data-tab="informes"]').click()
                page.locator("#page-informes.active").wait_for()
                page.wait_for_function("() => document.querySelectorAll('#infService option').length >= 2")
                assert page.locator("#infService option").count() >= 2
                selected_service = page.locator("#infService option", has_text="Servicio Browser Retencion").get_attribute("value")
                with page.expect_response(
                    lambda response: "/auth/analytics/overview" in response.url
                    and f"service_id={selected_service}" in response.url
                ) as service_report:
                    page.locator("#infService").select_option(selected_service)
                assert service_report.value.json()["service_id"] == selected_service
                page.locator("#infDateFrom").fill("2026-01-01")
                page.locator("#infDateTo").fill("2026-12-31")
                with page.expect_response(
                    lambda response: "/auth/analytics/overview" in response.url
                    and f"service_id={selected_service}" in response.url
                    and "date_from=2026-01-01" in response.url
                ) as custom_report:
                    page.locator("#infDateTo").press("Tab")
                assert custom_report.value.json()["service_id"] == selected_service
                assert "date_from=2026-01-01" in custom_report.value.url
                page.get_by_role("heading", name="Rendimiento económico", exact=True).wait_for()
                page.locator("#chartRevenue [data-chart-tip]").first.hover()
                page.locator("#chartRevenue .inf-chart-tooltip.visible").wait_for()
                page.locator(".inf-expand-btn").first.click()
                page.locator("#infChartModal.open").wait_for()
                page.locator("#infChartModalClose").click()
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#navBurger").click()
                page.locator("#sidebar.mobile-open").wait_for()
                page.locator('.nav-item[data-tab="informes"]').click()
                assert page.locator("#sidebar.mobile-open").count() == 0
                assert page.locator("#page-informes").evaluate(
                    "(element) => element.scrollWidth <= element.clientWidth + 2"
                )

                # La agenda se prueba la ULTIMA y en pantalla de escritorio: arrastrar
                # deja la pagina desplazada y el menu fuera de vista, y lo de arriba da
                # por hecho que se esta donde estaba.
                page.set_viewport_size({"width": 1500, "height": 950})
                # ── Agenda: escribir el servicio y estirar la cita ─────────
                # Las tres cosas que pidio el salon el 9-sep-2026 viendo su agenda
                # de verdad: el servicio se ESCRIBE (tienen 186 y el desplegable no
                # se puede usar), el cursor ya esta en ese campo al abrir, y la cita
                # se estira arrastrando su borde como en su programa de siempre.
                page.locator('.nav-item[data-tab="citas"]').click()
                page.locator("#page-citas.active").wait_for()
                page.locator("#citasNuevaBtn").click()
                page.locator("#newBookingDrawer.open").wait_for()
                assert page.evaluate("() => document.activeElement && document.activeElement.id") == "nbServicio", (
                    "al abrir Nueva cita el cursor tiene que estar en el servicio"
                )
                page.keyboard.type("mech", delay=30)
                page.wait_for_function("() => document.querySelectorAll('#nbSvcAc .nb-ac-item').length >= 2")
                sugerencias = page.eval_on_selector_all("#nbSvcAc .nb-ac-item b", "els => els.map(e => e.textContent)")
                assert all("mech" in s.lower() for s in sugerencias), sugerencias
                # Dos palabras y en desorden: asi busca la gente, no por prefijo.
                page.fill("#nbServicio", "")
                page.keyboard.type("largo mech", delay=30)
                page.wait_for_function("() => document.querySelectorAll('#nbSvcAc .nb-ac-item').length === 1")
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")
                assert "largo" in page.input_value("#nbServicio").lower()
                page.locator("#newBookingClose").click()

                for _ in range(dias_hasta_la_cita):
                    page.locator("#cdNext").click()
                    page.wait_for_timeout(600)

                # Pinchar un hueco vacio de la agenda y DESPUES elegir el servicio: la
                # hora pinchada tiene que seguir puesta. Antes se perdia -los huecos se
                # recargan al cambiar de servicio- y habia que volver a buscarla
                # (reportado el 9-sep-2026 pinchando las 13:00 de una profesional).
                # OJO: el primer `.cd-body` es la COLUMNA DE HORAS, no la de nadie.
                cuerpo = page.locator(".cd-body").last
                caja_col = cuerpo.bounding_box()
                # Con `position` es Playwright quien desplaza la pagina: la columna es
                # mas alta que la pantalla y un clic por coordenadas caia fuera.
                cuerpo.click(position={"x": caja_col["width"] / 2, "y": caja_col["height"] / 2})
                page.locator("#newBookingDrawer.open").wait_for()
                page.wait_for_function("() => document.getElementById('nbSlotSelected').value !== ''")
                hora_pinchada = page.locator("#nbSlotSelected").input_value()
                assert hora_pinchada, "pinchar un hueco no dejo la hora puesta"
                page.fill("#nbServicio", "")
                page.keyboard.type("corte", delay=30)
                page.wait_for_function("() => document.querySelectorAll('#nbSvcAc .nb-ac-item').length >= 1")
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")
                page.wait_for_timeout(1200)
                assert page.locator("#nbSlotSelected").input_value() == hora_pinchada, (
                    "elegir el servicio borro la hora que se habia pinchado (%s -> %s)"
                    % (hora_pinchada, page.locator("#nbSlotSelected").input_value())
                )
                page.locator("#newBookingClose").click()

                page.wait_for_function("() => document.querySelectorAll('.cd-event').length >= 1")
                evento = page.locator(".cd-event").first
                evento.scroll_into_view_if_needed()
                assert page.locator(".cd-ev-grip").count() >= 2, "la cita no tiene bordes para estirarla"
                # La altura se mide ANTES de empezar a arrastrar: durante el arrastre
                # el bloque ya se ha estirado en pantalla y comparar contra eso no
                # prueba nada (me paso al escribir este test).
                alto_antes = page.locator(".cd-event").first.bounding_box()["height"]
                caja = page.locator(".cd-ev-grip.bot").first.bounding_box()
                page.mouse.move(caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2)
                page.mouse.down()
                page.mouse.move(caja["x"] + caja["width"] / 2, caja["y"] + caja["height"] / 2 + 60, steps=12)
                page.wait_for_selector(".cd-ev-dur")
                with page.expect_response(lambda r: "/reschedule" in r.url) as guardado:
                    page.mouse.up()
                assert guardado.value.status == 200, guardado.value.status
                page.wait_for_timeout(2500)
                # Se tiene que VER mas larga: el calendario pintaba la duracion del
                # catalogo y no la de la cita, asi que se guardaba bien y seguia
                # dibujada igual (reportado el 9-sep-2026).
                alto_despues = page.locator(".cd-event").first.bounding_box()["height"]
                assert alto_despues > alto_antes + 20, (
                    "la cita se guardo estirada pero se sigue pintando igual (%s -> %s)"
                    % (alto_antes, alto_despues)
                )
                # Y soltar el borde no puede abrir el panel de Gestionar cita.
                assert page.get_by_role("heading", name="Gestionar cita").count() == 0, (
                    "estirar la cita abre el panel de Gestionar"
                )
                # Se vuelve a Informes: la parte de movil que viene detras da por
                # hecho que se esta ahi.

                browser.close()

                if console_errors:
                    raise AssertionError(f"Errores de consola: {console_errors}")
            # Lo que de verdad importa del arrastre: que la cita OCUPE mas en la
            # agenda. Si solo cambiara el dibujo, el asistente seguiria ofreciendo
            # ese rato y meteria a otra clienta encima.
            _final = _booking._load_booking_or_404(_cita["id"])
            _dura = agenda._booking_row_duration_min(_final, CID)
            assert _dura > 20, "estirar la cita no cambio lo que ocupa (%s min)" % _dura

            print("PASS: Informes, filtros, graficos, servicios, centros, Ventas, "
                  "agenda (servicio escrito + cita estirada a %d min) y responsive movil" % _dura)
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    finally:
        import shutil as _shutil

        _shutil.rmtree(raw_runtime, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
