# -*- coding: utf-8 -*-
"""Comprueba, punto por punto, lo que se le ha PROMETIDO a Alicia por escrito.

Ella lo ha dado por bueno el 5-sep-2026, asi que este fichero es el contrato.
Cada caso dice que tiene que aparecer y que NO puede aparecer. No mide calidad:
mide cumplimiento.
"""
import asyncio, datetime, os, re, sys, unicodedata

RAIZ = r"e:\Vantelia"; sys.path.insert(0, RAIZ); os.chdir(RAIZ)
DEST = sys.argv[1]; os.environ["DB_PATH"] = DEST
from evals import arnes
arnes.preparar_copia(sys.argv[2], DEST)
arnes.comprobar_aislamiento(DEST); arnes.cortar_el_mundo_exterior()
dichos = arnes.capturar_envios()

from backend import agenda, booking, db, inbox, timeutils, whatsapp

CID = "alicia_rincon_estilistas"


def norm(t):
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    return "".join(c for c in t if ord(c) < 128)


def asc(t):
    t = unicodedata.normalize("NFKD", str(t or ""))
    return "".join(c for c in t if ord(c) < 128)


def conversa(tel, mensajes):
    whatsapp._wa_clear_flow(CID, tel)
    marca = len(dichos)
    for m in mensajes:
        asyncio.run(whatsapp._handle_whatsapp_message(
            cliente_id=CID, phone_number_id="p", from_number=tel,
            incoming_text=m, interactive_id="", request=None))
    return " ".join(dichos[marca:])


# (titulo, mensajes, debe_aparecer[any-of por grupo], no_puede_aparecer)
CASOS = [
    ("Precio de mechas: sin cifra, con diagnostico",
     ["cuanto cuestan unas mechas?"],
     [["diagnostico", "valoracion"]],
     [r"\b\d{2,3}\s*(euros|eur|â‚¬|€)"]),
    ("Precio de color / tinte",
     ["cuanto cuesta un cambio de color?"],
     [["diagnostico", "valoracion", "verte", "ver tu cabello"]],
     [r"\b\d{2,3}\s*(euros|eur|€)"]),
    ("Precio de Grey Blending",
     ["me hariais un grey blending? cuanto vale?"],
     [["diagnostico", "valoracion", "ver tu cabello", "en persona"]],
     [r"\b\d{2,3}\s*(euros|eur|€)"]),
    ("Precio de permanente",
     ["cuanto cuesta una permanente?"],
     [["diagnostico", "valoracion"]],
     [r"\b\d{2,3}\s*(euros|eur|€)"]),
    ("Extensiones: diagnostico y cita",
     ["quiero ponerme extensiones, cuanto cuesta?"],
     [["diagnostico", "valoracion"], ["cita", "agendar", "dia"]],
     [r"\b\d{2,3}\s*(euros|eur|€)"]),
    ("Alisado: pide foto por detras y se para",
     ["cuanto cuesta un alisado de queratina?"],
     [["foto"], ["detras"], ["contacto", "contactamos", "ponemos en contacto"]],
     [r"\b\d{2,3}\s*(euros|eur|€)"]),
    ("Insiste porque vive lejos: telefono",
     ["cuanto cuestan unas mechas?",
      "es que vivo a 80 km, no puedo ir solo para que me deis el precio"],
     [["625 120 100", "966 670 924", "llamar", "llamanos"]],
     []),
    ("No sabe que hacerse: no elige por ella",
     ["no se si hacerme unas mechas, un matiz o un tinte"],
     [["diagnostico", "valoracion"]],
     [r"te recomiendo (el|la|un|una)\s"]),
    ("Saludo: su frase y sin menu",
     ["hola"],
     [["carino"]],
     [r"1\.\s", r"agendar cita", r"opcion"]),
    ("Gracias: contesta y cierra",
     ["gracias"],
     [["gracias a ti"]],
     [r"servicio con ese nombre", r"no tengo un servicio"]),
    ("Horario: lo que ella tiene escrito",
     ["que horario teneis?"],
     [["10:00", "lunes", "sabado"]],
     []),
]

print("=" * 72)
print(" CUMPLIMIENTO DE LO PROMETIDO A ALICIA")
print("=" * 72)
fallos = 0
for i, (titulo, mensajes, exige, prohibe) in enumerate(CASOS):
    tel = "34600880%03d" % i
    try:
        texto = norm(conversa(tel, mensajes))
    except Exception as exc:  # noqa: BLE001
        print("ERROR  %s -> %s" % (titulo, str(exc)[:80])); fallos += 1; continue
    faltan = [grupo for grupo in exige if not any(norm(x) in texto for x in grupo)]
    sobran = [p for p in prohibe if re.search(p, texto)]
    ok = not faltan and not sobran
    print(("OK    " if ok else "FALLA ") + titulo)
    if not ok:
        fallos += 1
        for grupo in faltan:
            print("        falta decir alguna de:", grupo)
        for p in sobran:
            m = re.search(p, texto)
            print("        NO deberia decir:", p, "->", texto[max(0, m.start()-40):m.end()+40])

# --- Pide cita de diagnostico: dias, horas y 15 minutos ---
tel = "34600880900"
texto = norm(conversa(tel, [
    "hola, quiero hacerme un alisado pero no se cual",
    "y cuanto me costaria?",
    "vale, me puedes agendar una cita para un diagnostico",
]))
pide_largo = "de largo" in texto or "corto, medio, largo" in texto
da_dias = any(d in texto for d in ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado"))
print(("OK    " if (da_dias and not pide_largo) else "FALLA ")
      + "Pide cita de diagnostico: ofrece dias sin preguntar el largo")
if pide_largo or not da_dias:
    fallos += 1
    print("        pregunta el largo:", pide_largo, "| ofrece dias:", da_dias)

# --- El asistente se calla cuando el salon entra en la conversacion ---
tel = "34600880901"
conversa(tel, ["que horario teneis?"])
sid = None
with db._get_db_connection() as cx:
    fila = cx.execute("SELECT id FROM chat_sessions WHERE cliente_id=? AND origin LIKE ? "
                      "ORDER BY rowid DESC LIMIT 1", (CID, "%" + tel[-9:])).fetchone()
    sid = fila["id"] if fila else None
if sid:
    inbox.claim(sid, CID, agent_user_id="", agent_name="Equipo")
    marca = len(dichos)
    asyncio.run(whatsapp._handle_whatsapp_message(
        cliente_id=CID, phone_number_id="p", from_number=tel,
        incoming_text="cuanto cuestan unas mechas?", interactive_id="", request=None))
    callado = len(dichos) == marca
    print(("OK    " if callado else "FALLA ") + "El asistente se calla si el salon toma el chat")
    if not callado:
        fallos += 1
        print("        siguio hablando:", asc(dichos[marca])[:120])
else:
    print("--    no se pudo comprobar el silencio (sin sesion)")

print("=" * 72)
print(("TODO CUMPLE" if not fallos else "INCUMPLE %d PUNTOS" % fallos))
sys.exit(1 if fallos else 0)
