"""Genera el manual "Conecta tu WhatsApp al asistente" en PDF para un cliente.

Reutilizable: la plantilla (plantilla.html) es la misma para todos y las capturas del portal
son reales (img/, las saca capturas.py con un negocio de ejemplo). Por cliente cambian el
nombre, su usuario del portal y, si se pide, la pagina de prueba y facturacion.

    .venv/Scripts/python.exe scripts/manual_whatsapp/generar.py --negocio "Cap Rocat" \\
        --usuario reservas@caprocat.com --salida "D:/Vantelia_clientes/Cap Rocat/Manual.pdf" \\
        --facturacion --factura 2026-001 --importe "400 €, IVA incluido" --cuota "1.290 € al año, IVA incluido"

Sin --facturacion sale sin esa pagina (para un cliente que paga de otra forma o ya pago).
Hace falta Google Chrome instalado (lo usa Playwright) o la variable CHROME_PATH.
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import tempfile
from datetime import date
from html import escape
from pathlib import Path
from string import Template

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
LOGO = RAIZ / "hostinger_site" / "assets" / "img" / "logo-vantelia.webp"
CHROME = os.getenv("CHROME_PATH") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
CONTACTO = ("Pablo Sánchez", "Fundador, Vantelia", "+34 675 802 001 · info@vantelia.es")


def _uri(ruta: Path) -> str:
    return ruta.resolve().as_uri()


def _qr() -> str:
    """Un QR de verdad para la ilustracion del paso 5 (el real lo ensena Meta en pantalla)."""
    import segno

    buf = io.BytesIO()
    segno.make("Vantelia - ilustracion: el codigo real lo muestra Meta", error="m").save(
        buf, kind="png", scale=6, border=1, dark="#0B132B")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _ayuda(grande: bool) -> str:
    nombre, cargo, datos = CONTACTO
    texto = ("<b>¿Prefieres hacerlo con nosotros?</b> Te acompañamos en una videollamada de 15 minutos y lo dejamos "
             "conectado. Contesta a nuestro correo con el día y la hora que te vengan bien.")
    return ('<div class="ayuda"%s><div>%s</div><div class="contacto"><strong>%s</strong>%s<br>%s</div></div>'
            % ("" if grande else ' style="margin-top:9mm"', texto, escape(nombre), escape(cargo), escape(datos)))


def _pagina_facturacion(args, negocio: str, logo: str) -> str:
    dias = int(args.dias)
    return Template('''
<section class="pagina">
  <span class="etiqueta">Prueba y facturación</span>
  <h2>Qué pasa desde el día que conectas</h2>
  <p class="lead">Los días de prueba empiezan cuando el asistente ya atiende tu WhatsApp, no antes.</p>
  <div class="linea-tiempo">
    <div class="hito"><div class="bola">Día 0</div><b>Conectas tu WhatsApp</b>
      <p>Empiezan los $dias días de prueba sin coste. Ese mismo día abonas por transferencia la factura de puesta
      en marcha <b>$factura</b> ($importe). Los datos bancarios están en la factura.</p></div>
    <div class="hito"><div class="bola">1–$dias</div><b>Lo probáis de verdad</b>
      <p>Con vuestros clientes reales. Cualquier respuesta que queráis cambiar, nos lo pedís y la ajustamos.</p></div>
    <div class="hito"><div class="bola">Día $dias</div><b>Empieza la cuota</b>
      <p>$cuota, por domiciliación. El día de la conexión te mandamos un enlace seguro de Stripe para indicar la
      cuenta. No se cobra nada antes.</p></div>
  </div>
  $ayuda
  <div class="pie"><span class="marca"><img src="$logo" alt="">Vantelia</span><span>Conecta tu WhatsApp · $negocio · 5</span></div>
</section>''').substitute(dias=dias, factura=escape(args.factura), importe=escape(args.importe),
                          cuota=escape(args.cuota), ayuda=_ayuda(True), logo=logo, negocio=negocio)


def generar(args) -> Path:
    from playwright.sync_api import sync_playwright

    hoy = date.today()
    negocio = escape(args.negocio)
    logo = _uri(LOGO)
    html = Template((AQUI / "plantilla.html").read_text(encoding="utf-8")).substitute(
        negocio=negocio, usuario=escape(args.usuario), fecha="%s de %d" % (MESES[hoy.month - 1].capitalize(), hoy.year),
        logo=logo, qr=_qr(), img_acceso=_uri(AQUI / "img" / "01_acceso.png"),
        img_whatsapp=_uri(AQUI / "img" / "02_whatsapp.png"), img_conectado=_uri(AQUI / "img" / "03_conectado.png"),
        bloque_ayuda_corto="" if args.facturacion else _ayuda(False),
        pagina_facturacion=_pagina_facturacion(args, negocio, logo) if args.facturacion else "")
    salida = Path(args.salida).resolve()
    salida.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pagina_html = Path(tmp) / "manual.html"
        pagina_html.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            navegador = p.chromium.launch(executable_path=CHROME)
            pagina = navegador.new_page()
            pagina.goto(pagina_html.as_uri())
            pagina.wait_for_timeout(400)
            pagina.pdf(path=str(salida), format="A4", print_background=True, prefer_css_page_size=True)
            navegador.close()
    return salida


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--negocio", required=True, help="Nombre del negocio tal como lo conoce el cliente")
    parser.add_argument("--usuario", required=True, help="Su usuario del portal (email)")
    parser.add_argument("--salida", required=True, help="Ruta del PDF")
    parser.add_argument("--facturacion", action="store_true", help="Añade la página de prueba y facturación")
    parser.add_argument("--dias", default="10", help="Días de prueba")
    parser.add_argument("--factura", default="", help="Número de la factura de puesta en marcha")
    parser.add_argument("--importe", default="", help="Importe de esa factura, con el IVA dicho")
    parser.add_argument("--cuota", default="", help="La cuota, con su periodo y el IVA dicho")
    args = parser.parse_args()
    if args.facturacion and not (args.factura and args.importe and args.cuota):
        parser.error("--facturacion necesita --factura, --importe y --cuota")
    print(generar(args))


if __name__ == "__main__":
    main()
