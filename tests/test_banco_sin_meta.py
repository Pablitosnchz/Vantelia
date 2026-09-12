"""El banco captura también los formularios: nunca deben alcanzar Meta."""
import ast
import asyncio
from pathlib import Path



def test_instalar_captura_cierra_la_salida_de_payload(monkeypatch):
    from backend import messaging
    for nombre in ("_send_whatsapp_text", "_send_whatsapp_list", "_send_whatsapp_buttons",
                   "_send_whatsapp_cta_url", "_send_whatsapp_payload"):
        monkeypatch.setattr(messaging, nombre, getattr(messaging, nombre))
    async def salida_real(**kwargs):
        raise AssertionError("El banco ha intentado salir a Meta")
    monkeypatch.setattr(messaging, "_send_whatsapp_payload", salida_real)
    # El runner antiguo cambia stdout al importar. Ejecutar su función real sin
    # arrancar el CLI ni cargar configuración/credenciales de un negocio.
    fuente = (Path(__file__).resolve().parents[1] / "scripts/evaluar_asistente.py").read_text(encoding="utf-8")
    funcion = next(n for n in ast.parse(fuente).body if isinstance(n, ast.FunctionDef)
                   and n.name == "_instalar_captura")
    espacio = {}
    exec(compile(ast.Module(body=[funcion], type_ignores=[]), "runner-captura", "exec"), espacio)
    dichos = espacio["_instalar_captura"]()
    assert asyncio.run(messaging._send_whatsapp_payload(payload={})) is False
    assert asyncio.run(messaging._send_whatsapp_text(text="respuesta de prueba")) is True
    assert dichos == ["respuesta de prueba"]
