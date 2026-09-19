# -*- coding: utf-8 -*-
"""Los tres documentos de Cap Rocat como PDF RELLENABLE.

Campos de texto donde escriben (razón social, CIF, lugar y fecha, nombre y cargo…), una opción
única para la forma de pago (marcar una desmarca las otras) y recuadros de firma digital. El
texto del contrato queda fijo: solo se rellena lo que hay que rellenar.

Cómo funciona: se maqueta con el mismo HTML de siempre (Chromium), dejando en cada hueco una
marca invisible; después se buscan las marcas en el PDF y se ponen encima los campos de verdad
con pypdf.

Uso (en local, no en el servidor):  python scripts/caprocat_documentos_pdf.py
Salen en outreach/caprocat_adjuntos/ (fuera de git). Necesita `markdown`, `pypdf` y Playwright
con Chromium. Fuente: docs/legal/caprocat/*.md; si cambia el texto de un hueco, el script se para
diciendo cual no ha encontrado en vez de sacar un PDF con un campo de menos.
"""
import io
import os
import re
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject, DictionaryObject,
                           FloatObject, NameObject, NumberObject, TextStringObject)

RAIZ = Path(__file__).resolve().parents[1]
ORIGEN = str(RAIZ / 'docs' / 'legal' / 'caprocat')
DESTINO = str(RAIZ / 'outreach' / 'caprocat_adjuntos')
MM = 72 / 25.4          # puntos por milímetro
# Escalones de altura de las marcas: dos marcas en la misma línea se leerían como un solo
# trozo de texto con la posición de la primera, y los campos saldrían apilados.
ESCALONES = 4
ESCALON_PX = 3.0

CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #1f2a2e; }
h1 { font-size: 20pt; margin: 0 0 6pt; color: #12302f; letter-spacing: -0.2pt; }
h2 { font-size: 13pt; margin: 18pt 0 6pt; color: #12302f; border-bottom: 1px solid #d5dedd;
     padding-bottom: 3pt; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; color: #12302f; page-break-after: avoid; }
p { margin: 0 0 7pt; }
ul, ol { margin: 0 0 8pt; padding-left: 18pt; }
li { margin: 0 0 3pt; }
hr { border: 0; border-top: 1px solid #e3e9e8; margin: 12pt 0; }
code { font-family: Consolas, monospace; font-size: 9.5pt; background: #f1f5f4; padding: 0 3pt; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 10pt; page-break-inside: avoid; }
th, td { border: 1px solid #cfd9d8; padding: 5pt 7pt; text-align: left; vertical-align: middle; }
th { background: #eef3f2; font-weight: 600; }
thead:not(:has(th:not(:empty))) { display: none; }
table:has(thead th:nth-child(2):last-child) td:first-child { width: 34%; }
strong { color: #12302f; }
/* Huecos que se rellenan: se ven como tales también impresos. */
.fld { display: inline-block; height: 6.5mm; border-bottom: 1px solid #8fa3a6; background: #f7fbfb;
       position: relative; vertical-align: -1.6mm; }
.chk { display: inline-block; width: 4.4mm; height: 4.4mm; border: 1px solid #5f7478; border-radius: 50%;
       background: #fff; position: relative; vertical-align: -0.8mm; margin-right: 1.5mm; }
.sig { display: block; width: 72mm; height: 20mm; border: 1px dashed #8fa3a6; border-radius: 4px;
       background: #f7fbfb; position: relative; margin: 3pt 0 8pt; }
.mk { position: absolute; left: 0; top: 0; font-size: 2px; line-height: 2px; color: #fff; white-space: nowrap; }
.firmas td { vertical-align: top; width: 50%; }
"""

# ── Qué se rellena en cada documento ─────────────────────────────────────
# ⟦t:nombre:ancho_mm⟧ texto · ⟦r:grupo:valor⟧ opción única · ⟦f:nombre⟧ firma

def hoja(md):
    for etiqueta, campo in [('Razón social', 'razon_social'), ('CIF', 'cif'), ('Domicilio', 'domicilio'),
                            ('Representante y cargo', 'representante'),
                            ('Email de notificaciones y facturación', 'email')]:
        md = cambiar(md, '| %s | |' % etiqueta, '| %s | ⟦t:%s:104⟧ |' % (etiqueta, campo))
    md = cambiar(md, '- ☐ **Domiciliación SEPA**', '- ⟦r:forma_pago:SEPA⟧ **Domiciliación SEPA**')
    md = cambiar(md, '- ☐ **Transferencia** contra', '- ⟦r:forma_pago:Transferencia⟧ **Transferencia** contra')
    md = cambiar(md, '- ☐ **Transferencia anual**', '- ⟦r:forma_pago:Anual⟧ **Transferencia anual**')
    md = cambiar(md, 'Firmado en ______________________ a ______ de __________________ de 20____.', FIRMADO_EN)
    md = cambiar(md, '''| Por Vantelia | Por el Cliente |
|---|---|
| Pablo Sánchez Sánchez | Nombre: |
| | Cargo: |
| Firma: | Firma: |''', '''<table class="firmas"><thead><tr><th>Por Vantelia</th><th>Por el Cliente</th></tr></thead><tbody>
<tr><td>Pablo Sánchez Sánchez</td><td>Nombre: ⟦t:firmante_nombre:58⟧</td></tr>
<tr><td></td><td>Cargo: ⟦t:firmante_cargo:60⟧</td></tr>
<tr><td>Firma:⟦f:firma_vantelia⟧</td><td>Firma:⟦f:firma_cliente⟧</td></tr>
</tbody></table>''')
    return md


def contrato(md):
    md = cambiar(md, '''Razón social: ______________________________________
CIF: ____________________
Domicilio: ________________________________________
Representante legal: ______________________________
Email de notificaciones: __________________________
''', '''| | |
|---|---|
| Razón social | ⟦t:razon_social:104⟧ |
| CIF | ⟦t:cif:104⟧ |
| Domicilio | ⟦t:domicilio:104⟧ |
| Representante legal | ⟦t:representante:104⟧ |
| Email de notificaciones | ⟦t:email:104⟧ |

''')
    md = cambiar(md, '- Forma de pago: ______________________ (transferencia o domiciliación, a indicar en la firma).',
                 '- Forma de pago: ⟦t:forma_pago:55⟧ (transferencia o domiciliación, a indicar en la firma).')
    md = cambiar(md, 'Firmado en ___________________ a ____ de _________________ de 20___.', FIRMADO_EN)
    md = cambiar(md, '''**Por Vantelia**

Nombre: Pablo Sánchez Sánchez
Firma:


**Por el Cliente**

Nombre: __________________________
Cargo: ___________________________
Firma:''', '''<table class="firmas"><thead><tr><th>Por Vantelia</th><th>Por el Cliente</th></tr></thead><tbody>
<tr><td>Nombre: Pablo Sánchez Sánchez</td><td>Nombre: ⟦t:firmante_nombre:58⟧</td></tr>
<tr><td></td><td>Cargo: ⟦t:firmante_cargo:60⟧</td></tr>
<tr><td>Firma:⟦f:firma_vantelia⟧</td><td>Firma:⟦f:firma_cliente⟧</td></tr>
</tbody></table>''')
    return md


def dpa(md):
    md = cambiar(md, '''Por el Cliente (Responsable del Tratamiento)

Nombre: ________________________  Cargo: ________________  Fecha: __________

Firma:


Por Vantelia (Encargado del Tratamiento)

Nombre: Pablo Sánchez Sánchez  Fecha: __________

Firma:''', '''<table class="firmas"><thead><tr><th>Por el Cliente (Responsable del Tratamiento)</th><th>Por Vantelia (Encargado del Tratamiento)</th></tr></thead><tbody>
<tr><td>Nombre: ⟦t:firmante_nombre:58⟧</td><td>Nombre: Pablo Sánchez Sánchez</td></tr>
<tr><td>Cargo: ⟦t:firmante_cargo:60⟧</td><td></td></tr>
<tr><td>Fecha: ⟦t:fecha_cliente:60⟧</td><td>Fecha: ⟦t:fecha_vantelia:60⟧</td></tr>
<tr><td>Firma:⟦f:firma_cliente⟧</td><td>Firma:⟦f:firma_vantelia⟧</td></tr>
</tbody></table>''')
    return md


FIRMADO_EN = 'Firmado en ⟦t:firmado_en:48⟧ a ⟦t:firmado_dia:12⟧ de ⟦t:firmado_mes:34⟧ de ⟦t:firmado_anio:18⟧.'

DOCS = [
    ('hoja-de-pedido-caprocat.md', 'Cap Rocat - 1 Hoja de pedido.pdf', hoja),
    ('contrato-caprocat.md', 'Cap Rocat - 2 Contrato de servicio.pdf', contrato),
    ('dpa-caprocat.md', 'Cap Rocat - 3 DPA (encargo de tratamiento).pdf', dpa),
]

AYUDA = {
    'razon_social': 'Razón social', 'cif': 'CIF', 'domicilio': 'Domicilio',
    'representante': 'Representante', 'email': 'Email de notificaciones',
    'forma_pago': 'Forma de pago', 'firmado_en': 'Lugar de la firma', 'firmado_dia': 'Día',
    'firmado_mes': 'Mes', 'firmado_anio': 'Año', 'firmante_nombre': 'Nombre de quien firma',
    'firmante_cargo': 'Cargo de quien firma', 'fecha_cliente': 'Fecha', 'fecha_vantelia': 'Fecha',
    'firma_cliente': 'Firma del Cliente', 'firma_vantelia': 'Firma de Vantelia',
}


def cambiar(md, viejo, nuevo):
    n = md.count(viejo)
    assert n == 1, ('no aparece una vez', viejo[:60], n)
    return md.replace(viejo, nuevo)


def a_html(md):
    """Markdown -> HTML, y cada ⟦…⟧ en su hueco con su marca invisible."""
    html = markdown.markdown(md, extensions=['tables', 'sane_lists', 'md_in_html'])
    contador = [0]

    def marca(texto):
        k = contador[0] % ESCALONES
        contador[0] += 1
        return '<span class="mk" style="top:%.1fpx">QQ%s-%dQQ</span>' % (k * ESCALON_PX, texto, k)

    def hueco(m):
        tipo, resto = m.group(1), m.group(2)
        partes = resto.split(':')
        if tipo == 't':
            nombre, ancho = partes[0], partes[1]
            return '<span class="fld" style="width:%smm">%s</span>' % (ancho, marca('t-%s-%s' % (nombre, ancho)))
        if tipo == 'r':
            return '<span class="chk">%s</span>' % marca('r-%s-%s' % (partes[0], partes[1]))
        return '<span class="sig">%s</span>' % marca('f-%s' % partes[0])

    return re.sub(r'⟦([trf]):([^⟧]+)⟧', hueco, html)


def marcas(ruta_pdf):
    """Dónde ha caído cada marca: (página, tipo, datos, x, y_arriba)."""
    encontradas = []
    for n, pagina in enumerate(PdfReader(ruta_pdf).pages):
        def visitor(text, cm, tm, font_dict, font_size, n=n):
            # Al leer el PDF se cuelan espacios dentro de la marca («SEP A»): con ellos el valor
            # de la opcion no casaria con su dibujo y marcarla no haria nada.
            trozos = re.findall(r'QQ([trf])-(.+?)-(\d)QQ', re.sub(r'\s+', '', text or ''))
            assert len(trozos) <= 1, ('dos marcas leidas juntas: campos apilados', trozos)
            for tipo, datos, k in trozos:
                x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                # 1,5 pt de la propia marca y su escalón, pasado a puntos (1 px = 0,75 pt).
                encontradas.append((n, tipo, datos.split('-'), x, y + 1.5 + int(k) * ESCALON_PX * 0.75))
        pagina.extract_text(visitor_text=visitor)
    return encontradas


def _stream(escritor, contenido, ancho, alto, recursos=None):
    s = DecodedStreamObject()
    s.set_data(contenido.encode('latin-1'))
    s.update({
        NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
        NameObject('/BBox'): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(ancho), FloatObject(alto)]),
    })
    if recursos is not None:
        s[NameObject('/Resources')] = recursos
    return escritor._add_object(s)


def rellenable(ruta_pdf, encontradas):
    lector = PdfReader(ruta_pdf)
    escritor = PdfWriter(clone_from=lector)
    helv = escritor._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')}))
    zadb = escritor._add_object(DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/ZapfDingbats')}))
    fuentes = DictionaryObject({NameObject('/Helv'): helv, NameObject('/ZaDb'): zadb})
    campos = ArrayObject()
    escritor._root_object[NameObject('/AcroForm')] = escritor._add_object(DictionaryObject({
        NameObject('/Fields'): campos,
        NameObject('/NeedAppearances'): BooleanObject(True),
        NameObject('/DR'): DictionaryObject({NameObject('/Font'): fuentes}),
        NameObject('/DA'): TextStringObject('/Helv 10 Tf 0 g'),
        NameObject('/SigFlags'): NumberObject(1),
    }))
    grupos = {}

    def anotar(n, ref):
        pagina = escritor.pages[n]
        if '/Annots' in pagina:
            anotaciones = pagina['/Annots'].get_object()
        else:
            anotaciones = ArrayObject()
            pagina[NameObject('/Annots')] = anotaciones
        anotaciones.append(ref)

    def rect(x, arriba, ancho, alto):
        return ArrayObject([FloatObject(round(v, 2)) for v in (x, arriba - alto, x + ancho, arriba)])

    for n, tipo, datos, x, arriba in encontradas:
        pagina_ref = escritor.pages[n].indirect_reference
        comunes = {
            NameObject('/Type'): NameObject('/Annot'), NameObject('/Subtype'): NameObject('/Widget'),
            NameObject('/F'): NumberObject(4), NameObject('/P'): pagina_ref,
        }
        if tipo == 't':
            nombre, ancho_mm = datos[0], float(datos[1])
            campo = DictionaryObject(comunes)
            campo.update({
                NameObject('/FT'): NameObject('/Tx'), NameObject('/T'): TextStringObject(nombre),
                NameObject('/TU'): TextStringObject(AYUDA.get(nombre, nombre)),
                NameObject('/Rect'): rect(x, arriba, ancho_mm * MM, 6.5 * MM),
                NameObject('/DA'): TextStringObject('/Helv 10 Tf 0 g'), NameObject('/V'): TextStringObject(''),
            })
            ref = escritor._add_object(campo)
            campos.append(ref)
            anotar(n, ref)
        elif tipo == 'r':
            grupo, valor = datos[0], datos[1]
            if grupo not in grupos:
                padre = DictionaryObject({
                    NameObject('/FT'): NameObject('/Btn'), NameObject('/T'): TextStringObject(grupo),
                    NameObject('/TU'): TextStringObject(AYUDA.get(grupo, grupo)),
                    # Radio (1<<15) y sin poder quedarse sin marcar una vez elegida (1<<14).
                    NameObject('/Ff'): NumberObject((1 << 15) | (1 << 14)),
                    NameObject('/V'): NameObject('/Off'), NameObject('/Kids'): ArrayObject(),
                })
                grupos[grupo] = escritor._add_object(padre)
                campos.append(grupos[grupo])
            lado = 4.4 * MM
            recursos = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/ZaDb'): zadb})})
            marcado = _stream(escritor, 'q 0.07 0.19 0.18 rg BT /ZaDb 8 Tf 2.2 3.1 Td (l) Tj ET Q', lado, lado, recursos)
            vacio = _stream(escritor, '', lado, lado)
            hijo = DictionaryObject(comunes)
            hijo.update({
                NameObject('/Parent'): grupos[grupo],
                NameObject('/Rect'): rect(x, arriba, lado, lado),
                NameObject('/AS'): NameObject('/Off'),
                NameObject('/MK'): DictionaryObject({NameObject('/CA'): TextStringObject('l')}),
                NameObject('/AP'): DictionaryObject({NameObject('/N'): DictionaryObject({
                    NameObject('/' + valor): marcado, NameObject('/Off'): vacio})}),
                NameObject('/DA'): TextStringObject('/ZaDb 0 Tf 0 g'),
            })
            ref = escritor._add_object(hijo)
            grupos[grupo].get_object()['/Kids'].append(ref)
            anotar(n, ref)
        else:
            nombre = datos[0]
            campo = DictionaryObject(comunes)
            campo.update({
                NameObject('/FT'): NameObject('/Sig'), NameObject('/T'): TextStringObject(nombre),
                NameObject('/TU'): TextStringObject(AYUDA.get(nombre, nombre)),
                NameObject('/Rect'): rect(x, arriba, 72 * MM, 20 * MM),
            })
            ref = escritor._add_object(campo)
            campos.append(ref)
            anotar(n, ref)

    with open(ruta_pdf, 'wb') as salida:
        escritor.write(salida)


def main():
    os.makedirs(DESTINO, exist_ok=True)
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        for fuente, salida, preparar in DOCS:
            md = preparar(io.open(os.path.join(ORIGEN, fuente), encoding='utf-8').read())
            html = ('<!doctype html><html lang="es"><head><meta charset="utf-8"><style>%s</style>'
                    '</head><body>%s</body></html>' % (CSS, a_html(md)))
            pagina.set_content(html, wait_until='load')
            ruta = os.path.join(DESTINO, salida)
            pagina.pdf(path=ruta, format='A4', print_background=True, display_header_footer=True,
                       header_template='<div></div>',
                       footer_template=('<div style="font-size:8pt;color:#7a8a8e;width:100%;'
                                        'text-align:center;font-family:Arial">Vantelia · '
                                        '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'),
                       margin={'top': '20mm', 'bottom': '20mm', 'left': '18mm', 'right': '18mm'})
            esperadas = len(re.findall(r'⟦[trf]:', md))
            encontradas = marcas(ruta)
            assert len(encontradas) == esperadas, (salida, 'marcas', len(encontradas), 'de', esperadas)
            rellenable(ruta, encontradas)
            campos = PdfReader(ruta).get_fields() or {}
            print('%-48s %d huecos -> %d campos: %s' % (salida, esperadas, len(campos), ', '.join(sorted(campos))))
        navegador.close()


main()
