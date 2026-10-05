# -*- coding: utf-8 -*-
"""El seguimiento tras la demo: de "te la mando" al lead cualificado.

POR QUE EXISTE
--------------
Pablo (5-oct-2026): "quiero los leads ya cualificados para ponerme a trabajar con ellos; a
partir de ahi ya me encargo yo. Prefiero email". Diseno en docs/SISTEMA_CAPTACION_FINAL.md.

Lo que NO puede pasar y vigilan estos tests:
- escribir a quien dijo que no, se dio de baja, respondio o ya es de Pablo;
- escribir dos veces el mismo toque (un envio en duda no se repite);
- que abrir un enlace (un antivirus lo hace) cualifique a alguien;
- que un lead cualificado no le llegue a Pablo, o le llegue dos veces;
- que el correo frio o Sara le escriban o le llamen encima del seguimiento.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from test_booking_exhaustive import api_module, client  # noqa: F401
from test_captacion_voz import _Falso, captacion, envios  # noqa: F401

# Octubre de 2026: Madrid = UTC+2. El lunes 12 es fiesta nacional.
LUNES_1200 = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
MARTES_1030 = datetime(2026, 10, 6, 8, 30, tzinfo=timezone.utc)
MARTES_2000 = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)
VIERNES_1030 = datetime(2026, 10, 9, 8, 30, tzinfo=timezone.utc)
VIERNES_1700 = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
MARTES_13_1030 = datetime(2026, 10, 13, 8, 30, tzinfo=timezone.utc)
EMAIL = "info@sonrisa.es"
FIJO = "911234567"


@pytest.fixture()
def sd(captacion, envios, monkeypatch):  # noqa: F811
    """Base de captacion temporal, envios capturados, secreto de enlaces y reloj fijo."""
    from backend import appstate, outreach, seguimiento_demo, timeutils

    monkeypatch.setenv("OUTREACH_TRACKING_SECRET", "secreto-seguimiento")
    monkeypatch.setenv("OUTREACH_TRACKING_BASE_URL", "https://app.test")
    monkeypatch.setattr(outreach, "_outreach_smtp_health", lambda: {"ok": True})
    monkeypatch.setattr(timeutils, "_utc_now", lambda: LUNES_1200)
    with appstate.state_lock:
        appstate.rate_limit_buckets.clear()
    return seguimiento_demo


def _negocio(email=EMAIL, nombre="Clínica Sonrisa", sector="clinica dental", telefono=FIJO, estado="contacted"):
    from backend import outreach

    with closing(outreach._outreach_db()) as conn:
        conn.execute("INSERT OR REPLACE INTO prospects (email, business_name, niche, phone, status, created_at, "
                     "updated_at) VALUES (?,?,?,?,?,?,?)", (email, nombre, sector, telefono, estado, "x", "x"))
        conn.commit()


def _evento(email, tipo, ts, url=""):
    from backend import outreach

    with closing(outreach._outreach_db()) as conn:
        conn.execute("INSERT INTO events (email, type, stage, url, ts) VALUES (?,?,?,?,?)",
                     (email, tipo, "fu1", url, ts.isoformat(timespec="seconds")))
        conn.commit()


def _demo_de_sara(captacion, telefono=FIJO, email=EMAIL, nombre="Marta"):  # noqa: F811
    """Sara llama y manda la demo (por correo a un fijo; por SMS a un movil)."""
    hecho = captacion.llamar(telefono, "Clínica Sonrisa", "clinica dental", email, origen="auto", cliente=_Falso())
    respuesta = captacion.herramienta("enviar_informacion", {captacion.CAMPO_LLAMADA: hecho["llamada"],
                                                             "nombre": nombre})
    assert respuesta["ok"] is True
    return hecho["llamada"], respuesta


def _seg(sd, email=EMAIL):
    with sd._conexion() as conn:
        return sd._por_email(conn, email)


def _ronda(sd, ahora, mandar=None):
    hechos = []

    def falso(fila, plantilla, paso, momento):
        hechos.append((fila["id"], plantilla, paso))
        return "<toque%d@test>" % paso, "asunto"

    salida = sd.ronda(ahora=ahora, mandar=mandar or falso, esperar_turno=lambda: None)
    return hechos, salida


# --- Inscripcion: la demo que manda Sara -------------------------------------------------------

def test_la_demo_de_sara_queda_apuntada_y_en_seguimiento(sd, captacion, envios):  # noqa: F811
    """El correo con la demo ahora va a `sends` con su Message-ID: sin eso el lector de
    respuestas no veia a quien contestaba, y el seguimiento no podia escribir en su hilo."""
    _negocio()
    llamada_id, _ = _demo_de_sara(captacion)
    from backend import outreach

    with closing(outreach._outreach_db()) as conn:
        envio = conn.execute("SELECT * FROM sends WHERE email=? AND stage='demo_llamada'", (EMAIL,)).fetchone()
    assert envio is not None and envio["message_id"].startswith("<")
    fila = _seg(sd)
    assert (fila["origen"], fila["canal"], fila["destino"], fila["llamada_id"]) == ("llamada", "email", EMAIL,
                                                                                    llamada_id)
    assert fila["hilo"] == envio["message_id"] and fila["asunto_hilo"] == "Lo que te conté por teléfono"
    assert fila["contacto"] == "Marta" and fila["estado"] == "activo"
    # Lunes a mediodia -> el martes a las 10:30 (Madrid).
    assert fila["proximo"] == MARTES_1030.isoformat(timespec="seconds")


def test_a_un_movil_el_seguimiento_va_por_sms(sd, captacion, envios):  # noqa: F811
    _negocio(telefono="675802001")
    _demo_de_sara(captacion, telefono="675802001")
    fila = _seg(sd)
    assert (fila["canal"], fila["destino"]) == ("sms", "+34675802001")
    assert len(sd.pasos("llamada", "sms")) == 2, "por SMS, dos toques y no tres"


def test_sara_dice_que_escribira_pablo_solo_si_le_va_a_escribir(sd, captacion, envios):  # noqa: F811
    _negocio()
    _, apagado = _demo_de_sara(captacion)
    assert "Pablo" not in apagado["mensaje"], "con el interruptor apagado no se promete nada"
    sd.guardar_config(encendido=True)
    _negocio(email="hola@otra.es", nombre="Otra", telefono="912222222")
    _, encendido = _demo_de_sara(captacion, telefono="912222222", email="hola@otra.es")
    assert "Pablo, el fundador, le escribira" in encendido["mensaje"]


def test_no_se_inscribe_a_quien_no_se_le_puede_escribir(sd):
    for estado in ("replied", "client", "lost", "bounced", "baja"):
        email = "%s@x.es" % estado
        _negocio(email=email, estado=estado)
        assert sd.inscribir(origen="llamada", canal="email", destino=email, prospecto=email) is None, estado


def test_una_fila_por_negocio_y_lo_nuevo_manda_si_aun_no_se_le_ha_escrito(sd):
    _negocio()
    primero = sd.inscribir(origen="correo", canal="email", destino=EMAIL, prospecto=EMAIL)
    segundo = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, contacto="Marta")
    assert primero == segundo
    assert _seg(sd)["origen"] == "llamada", "una demo pedida por telefono pesa mas que un uso suelto"


# --- Cuando --------------------------------------------------------------------------------------

def test_los_toques_caen_en_dia_laborable_a_las_10_30_y_saltan_festivos(sd):
    # Viernes 9 -> el lunes 12 es fiesta nacional -> martes 13.
    assert sd.cuando_toca(VIERNES_1700, 1) == MARTES_13_1030
    assert sd.cuando_toca(LUNES_1200, 1) == MARTES_1030
    # "¿Que te ha parecido?" unas horas despues de usarla, dentro del horario.
    assert sd.cuando_toca(LUNES_1200, 0) == LUNES_1200 + timedelta(hours=3)
    assert sd.primer_hueco(MARTES_2000) == datetime(2026, 10, 7, 8, 30, tzinfo=timezone.utc)


# --- Los toques ------------------------------------------------------------------------------------

def test_sin_interruptor_no_sale_nada_y_fuera_de_horario_tampoco(sd):
    _negocio()
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    hechos, salida = _ronda(sd, MARTES_1030)
    assert hechos == [] and salida["motivo"] == "apagado"
    sd.guardar_config(encendido=True)
    hechos, salida = _ronda(sd, MARTES_2000)
    assert hechos == [] and salida["motivo"] == "fuera_de_horario"
    hechos, _ = _ronda(sd, MARTES_1030 - timedelta(hours=1))
    assert hechos == [], "a las 9:30 aun no le toca (su toque es a las 10:30)"


def test_la_secuencia_entera_y_se_cierra_sola(sd):
    _negocio()
    sd.guardar_config(encendido=True)
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    momento = MARTES_1030
    plantillas = []
    for _ in range(3):
        hechos, _salida = _ronda(sd, momento)
        assert len(hechos) == 1
        plantillas.append(hechos[0][1])
        momento = datetime.fromisoformat(_seg(sd)["proximo"]) if _seg(sd)["proximo"] else momento
    assert plantillas == ["primero", "valor", "cierre"]
    fila = _seg(sd)
    assert fila["estado"] == "terminado" and fila["paso"] == 3
    hechos, _ = _ronda(sd, momento + timedelta(days=30))
    assert hechos == []


def test_el_primer_correo_va_en_el_hilo_de_sara_y_pide_una_respuesta(sd, captacion, envios):  # noqa: F811
    _negocio()
    sd.guardar_config(encendido=True)
    _demo_de_sara(captacion)
    hilo = _seg(sd)["hilo"]
    envios["email"].clear()
    salida = sd.ronda(ahora=MARTES_1030, esperar_turno=lambda: None)
    assert salida["enviados"] == 1
    mensaje = envios["email"][0]
    assert mensaje["To"] == EMAIL and mensaje["Subject"] == "Re: Lo que te conté por teléfono"
    assert mensaje["In-Reply-To"] == hilo
    texto = mensaje.get_body(preferencelist=("plain",)).get_content()
    assert texto.startswith("Hola, Marta:")
    assert "Ayer hablasteis con Sara" in texto, "vale tambien si llamaron ellos al 91"
    assert "Contéstame con el día y la hora" in texto
    assert "/interes/" in texto and "?r=si" in texto and "?r=no" in texto
    assert "/demo/go/" in texto, "no la probo: se le deja el enlace"
    assert "{" not in texto
    from backend import outreach

    with closing(outreach._outreach_db()) as conn:
        envio = conn.execute("SELECT * FROM sends WHERE stage='seguimiento_1'").fetchone()
    assert envio["email"] == EMAIL and envio["message_id"] == mensaje["Message-ID"]


def test_los_correos_son_cortos_y_sin_restos(sd):
    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, negocio="Clínica Sonrisa",
                          sector="clinica dental", contacto="Marta Ruiz", ahora=LUNES_1200)
    fila = sd._fila(seg_id)
    for plantilla in ("primero", "valor", "cierre", "que_tal"):
        hecho = sd.contenido(fila, plantilla, MARTES_1030)
        cuerpo = hecho["texto"].split("Un saludo,")[0]
        palabras = [p for p in cuerpo.split() if not p.startswith("http")]
        assert len(palabras) <= 130, (plantilla, len(palabras))
        assert "{" not in hecho["texto"] and "{" not in hecho["html"], plantilla
        assert hecho["texto"].startswith("Hola, Marta:")
    valor = sd.contenido(fila, "valor", MARTES_1030)["texto"]
    assert "clinica_dental.mp3" in valor, "el audio de una llamada real de su sector"
    assert sd.OFERTA_PRUEBA in valor


def test_el_sms_va_sin_tildes_y_con_su_enlace(sd):
    seg_id = sd.inscribir(origen="llamada", canal="sms", destino="675802001", negocio="Peluquería Ñandú",
                          ahora=LUNES_1200)
    for plantilla in ("primero", "cierre"):
        texto = sd.texto_sms(sd._fila(seg_id), plantilla)
        assert not set("áéíóúÁÉÍÓÚñÑ¿¡") & set(texto), texto
        assert "/interes/" + sd.token_de(seg_id) in texto


@pytest.mark.parametrize("como_se_para,estado", [
    ("respondio", "respondio"), ("baja", "parado"), ("no_llamar", "parado"), ("cliente", "parado"),
])
def test_se_para_solo_con_cualquier_senal(sd, como_se_para, estado):
    from backend import outreach

    _negocio()
    sd.guardar_config(encendido=True)
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, telefono=FIJO, ahora=LUNES_1200)
    with closing(outreach._outreach_db()) as conn:
        if como_se_para == "respondio":
            conn.execute("INSERT INTO events (email, type, stage, ts) VALUES (?, 'reply', 'demo_llamada', ?)",
                         (EMAIL, (LUNES_1200 + timedelta(hours=2)).isoformat()))
        elif como_se_para == "baja":
            conn.execute("INSERT INTO suppressions (email, reason, added_at) VALUES (?, 'BAJA', 'x')", (EMAIL,))
        elif como_se_para == "no_llamar":
            conn.execute("INSERT INTO no_llamar (telefono, motivo, creado) VALUES (?, 'no', 'x')", ("+34" + FIJO,))
        else:
            conn.execute("UPDATE prospects SET status='client' WHERE email=?", (EMAIL,))
        conn.commit()
    hechos, _ = _ronda(sd, MARTES_1030)
    assert hechos == []
    assert _seg(sd)["estado"] == estado


def test_un_toque_en_duda_no_se_repite_y_uno_que_no_salio_si(sd):
    _negocio()
    sd.guardar_config(encendido=True)
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)

    def no_salio(fila, plantilla, paso, momento):
        raise sd.NoEnviado("conexion rechazada")

    _ronda(sd, MARTES_1030, mandar=no_salio)
    assert _seg(sd)["paso"] == 0, "seguro que no salio: se reintenta"
    hechos, _ = _ronda(sd, MARTES_1030 + timedelta(minutes=10))
    assert [h[2] for h in hechos] == [1]

    _negocio(email="dos@x.es", telefono="912222222")
    sd.inscribir(origen="llamada", canal="email", destino="dos@x.es", prospecto="dos@x.es", ahora=LUNES_1200)

    def en_duda(fila, plantilla, paso, momento):
        raise RuntimeError("se corto tras aceptar el mensaje")

    _ronda(sd, MARTES_1030 + timedelta(minutes=20), mandar=en_duda)
    fila = _seg(sd, "dos@x.es")
    assert fila["paso"] == 1, "pudo salir: cuenta como hecho"
    with sd._conexion() as conn:
        toque = conn.execute("SELECT estado FROM seguimiento_demo_toques WHERE seguimiento_id=? AND paso=1",
                             (fila["id"],)).fetchone()
    assert toque["estado"] == "incierto"
    hechos, _ = _ronda(sd, MARTES_1030 + timedelta(minutes=30))
    assert all(h[0] != fila["id"] for h in hechos), "el mismo toque nunca dos veces"


def test_el_tope_del_dia(sd, monkeypatch):
    monkeypatch.setattr(sd, "MAX_CORREOS_AL_DIA", 1)
    sd.guardar_config(encendido=True)
    for numero in range(3):
        email = "n%d@x.es" % numero
        _negocio(email=email, telefono="91000000%d" % numero)
        sd.inscribir(origen="llamada", canal="email", destino=email, prospecto=email, ahora=LUNES_1200)
    hechos, _ = _ronda(sd, MARTES_1030)
    assert len(hechos) == 1


def test_lo_que_se_quedo_sin_empezar_caduca(sd):
    _negocio()
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    sd.guardar_config(encendido=True)
    hechos, _ = _ronda(sd, LUNES_1200 + timedelta(days=16))
    assert hechos == [] and _seg(sd)["estado"] == "caducado"


# --- El correo frio y Sara no le escriben ni le llaman encima ---------------------------------------

def test_en_seguimiento_el_correo_frio_no_le_escribe_y_sara_no_le_llama(sd):
    from backend import lanzador_llamadas, outreach

    _negocio(estado="contacted")
    with closing(outreach._outreach_db()) as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?,?)",
                     (EMAIL, "cold", "una pregunta", "2026-09-01T08:00:00+00:00", "send"))
        conn.commit()
    candidatos = lanzador_llamadas.candidatos(MARTES_1030)
    assert [c["prospecto"] for c in candidatos] == [EMAIL], "sin seguimiento, Sara podria llamarle"
    sd.inscribir(origen="correo", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    with closing(outreach._outreach_db()) as conn:
        assert outreach._outreach_send_eligibility(conn, EMAIL, "fu1", 0)["reason"] == "en_seguimiento_de_la_demo"
        import outreach_campaign  # type: ignore

        assert outreach_campaign.fetch_candidates(conn, "fu1", 0, 10) == []
    assert lanzador_llamadas.candidatos(MARTES_1030) == []


# --- Cualificar: la pagina /interes ---------------------------------------------------------------

def test_abrir_el_enlace_no_cualifica_y_enviar_el_formulario_si(sd, client, envios):  # noqa: F811
    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, negocio="Clínica Sonrisa",
                          sector="clinica dental", contacto="Marta", telefono=FIJO, ahora=LUNES_1200)
    token = sd.token_de(seg_id)
    pagina = client.get("/interes/%s?r=si" % token)
    assert pagina.status_code == 200 and "Clínica Sonrisa" in pagina.text and 'value="Marta"' in pagina.text.replace(
        "'", '"')
    assert sd._fila(seg_id)["estado"] == "activo", "un antivirus que abre el enlace no cualifica a nadie"
    envio = client.post("/interes/%s" % token, data={
        "r": "si", "nombre": "Marta", "como": "telefono", "cuando": "mañana por la mañana",
        "telefono": "911234567", "email": EMAIL, "pregunta": "¿Funciona con nuestra agenda?"})
    assert envio.status_code == 200 and "Pablo te contacta mañana por la mañana" in envio.text
    fila = sd._fila(seg_id)
    assert fila["estado"] == "cualificado" and fila["cualificado_por"] == "formulario"
    # Pablo se entera al momento, con la ficha.
    asuntos = [a[0] for a in envios["avisos"]]
    assert asuntos == ["🔥 Lead cualificado: Clínica Sonrisa — por teléfono mañana por la mañana"]
    texto_aviso = envios["avisos"][0][1]
    assert "¿Funciona con nuestra agenda?" in texto_aviso and "Borrador para contestarle" in texto_aviso
    # Sale de toda automatizacion y entra en el Plan de escala.
    from backend import db, outreach

    with closing(outreach._outreach_db()) as conn:
        assert conn.execute("SELECT status FROM prospects WHERE email=?", (EMAIL,)).fetchone()[0] == "replied"
    with closing(db._get_db_connection()) as conn:
        oportunidad = conn.execute("SELECT * FROM growth_opportunities WHERE id=?",
                                   (fila["oportunidad_id"],)).fetchone()
    assert oportunidad["stage"] == "conversacion" and oportunidad["company"] == "Clínica Sonrisa"
    # Un segundo envio no avisa otra vez.
    client.post("/interes/%s" % token, data={"r": "si", "telefono": "911234567"})
    assert len(envios["avisos"]) == 1


def test_ahora_no_cierra_y_no_se_le_vuelve_a_escribir_ni_a_llamar(sd, client):  # noqa: F811
    from backend import outreach

    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, telefono=FIJO,
                          ahora=LUNES_1200)
    respuesta = client.post("/interes/%s" % sd.token_de(seg_id), data={"r": "no", "motivo": "ya_tenemos"})
    assert respuesta.status_code == 200 and "No os volveremos a escribir" in respuesta.text
    fila = sd._fila(seg_id)
    assert fila["estado"] == "descartado" and "ya tienen algo parecido" in fila["motivo"]
    with closing(outreach._outreach_db()) as conn:
        assert conn.execute("SELECT 1 FROM suppressions WHERE email=?", (EMAIL,)).fetchone()
        assert conn.execute("SELECT status FROM prospects WHERE email=?", (EMAIL,)).fetchone()[0] == "lost"
        assert conn.execute("SELECT 1 FROM no_llamar WHERE telefono=?", ("+34" + FIJO,)).fetchone()


def test_enlaces_falsos_y_bots(sd, client):  # noqa: F811
    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    token = sd.token_de(seg_id)
    assert sd.id_del_token(token) == seg_id
    assert client.get("/interes/%s" % (token[:-2] + "xx")).status_code == 404
    assert client.get("/interes/sd_inventado.abc").status_code == 404
    # El campo trampa solo lo rellena un bot.
    client.post("/interes/%s" % token, data={"r": "si", "web": "http://spam", "telefono": FIJO})
    assert sd._fila(seg_id)["estado"] == "activo"
    # Sin ningun contacto, se vuelve a pedir.
    sin_contacto = client.post("/interes/%s" % token, data={"r": "si", "telefono": "", "email": ""})
    assert sin_contacto.status_code == 400 and sd._fila(seg_id)["estado"] == "activo"


# --- Cualificar: las respuestas por correo ---------------------------------------------------------

CITA = ("\n\nEl lun, 5 oct 2026 a las 10:30, Pablo Sanchez <pablo@out.vantelia.es> escribió:\n"
        "> Si ahora no es para vosotros, dímelo aquí y no os escribo más.")


def test_una_respuesta_con_interes_es_un_lead_y_pablo_recibe_la_ficha(sd, envios):
    from backend import outreach

    _negocio()
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    outreach._outreach_notify_reply({"email": EMAIL, "stage": "seguimiento_1", "subject": "Re: La demo",
                                     "body_excerpt": "Sí, me gustaría verlo. Llamadme el jueves." + CITA})
    assert _seg(sd)["estado"] == "cualificado" and _seg(sd)["cualificado_por"] == "respuesta"
    assert len(envios["avisos"]) == 1, "uno solo: la ficha"
    assert envios["avisos"][0][0].startswith("🔥 Lead cualificado: Clínica Sonrisa")
    assert "Llamadme el jueves" in envios["avisos"][0][1]
    assert "no os escribo más" not in envios["avisos"][0][1], "lo citado no es lo que dijo"


def test_un_no_por_correo_cierra_y_pablo_recibe_el_aviso_de_siempre(sd, envios):
    from backend import outreach

    _negocio()
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    outreach._outreach_notify_reply({"email": EMAIL, "stage": "seguimiento_2", "subject": "Re: La demo",
                                     "body_excerpt": "No estamos interesados, gracias." + CITA})
    assert _seg(sd)["estado"] == "descartado"
    assert len(envios["avisos"]) == 1 and envios["avisos"][0][0].startswith("📬 Respuesta")


def test_sin_modelo_lo_que_no_es_un_no_claro_cuenta_como_pregunta():
    from backend import seguimiento_demo

    assert seguimiento_demo.clasificar_respuesta("¿Cuánto cuesta?")["intencion"] == "pregunta"
    assert seguimiento_demo.clasificar_respuesta("No nos interesa" + CITA)["intencion"] == "no_interesado"
    assert seguimiento_demo.clasificar_respuesta("Gracias" + CITA)["intencion"] == "pregunta"
    assert seguimiento_demo.clasificar_respuesta("Estaré fuera de la oficina hasta el lunes")["intencion"] == \
        "fuera_de_oficina"


# --- Cualificar: las senales de la demo -----------------------------------------------------------

def test_pulsar_activar_en_su_demo_es_un_lead(sd, envios):
    """Noelia Brown, 5-oct-2026, 13:50: pulso "Activar gratis e instalar" y nadie se entero."""
    _negocio(email="info@noelia.es", nombre="Noelia Brown", sector="peluqueria", telefono="671137353")
    _evento("info@noelia.es", "claim_intent", LUNES_1200 - timedelta(hours=1))
    assert sd.procesar_senales(LUNES_1200)["cualificados"] == 1
    fila = _seg(sd, "info@noelia.es")
    assert fila["estado"] == "cualificado" and fila["cualificado_por"] == "demo_claim"
    assert [a[0] for a in envios["avisos"]] == ["🔥 Lead cualificado: Noelia Brown"]
    assert "Activar gratis" in envios["avisos"][0][1]
    # La misma senal no se procesa dos veces (cursor) y un segundo boton no avisa otra vez.
    _evento("info@noelia.es", "contact_intent", LUNES_1200)
    sd.procesar_senales(LUNES_1200 + timedelta(minutes=10))
    assert len(envios["avisos"]) == 1


def test_un_boton_de_quien_ya_lleva_pablo_no_avisa(sd, envios):
    _negocio(estado="replied")
    _evento(EMAIL, "claim_intent", LUNES_1200)
    sd.procesar_senales(LUNES_1200)
    assert envios["avisos"] == [] and _seg(sd) is None


def test_quien_usa_la_demo_de_un_correo_frio_entra_en_seguimiento_en_su_hilo(sd):
    from backend import outreach

    _negocio()
    with closing(outreach._outreach_db()) as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode, message_id) VALUES (?,?,?,?,?,?)",
                     (EMAIL, "fu1", "te dejo el ejemplo", "2026-10-02T08:00:00+00:00", "send", "<fu1@x>"))
        conn.commit()
    _evento(EMAIL, "demo_interacted", LUNES_1200)
    assert sd.inscribir_a_quien_la_usa(LUNES_1200) == 0
    assert _seg(sd) is None, "con el interruptor apagado, el correo frio sigue como siempre"
    # Al encenderlo entra tambien quien la uso mientras estaba apagado.
    sd.guardar_config(encendido=True)
    assert sd.inscribir_a_quien_la_usa(LUNES_1200 + timedelta(minutes=10)) == 1
    assert sd.inscribir_a_quien_la_usa(LUNES_1200 + timedelta(minutes=20)) == 0, "una vez"
    fila = _seg(sd)
    assert (fila["origen"], fila["hilo"], fila["asunto_hilo"]) == ("correo", "<fu1@x>", "te dejo el ejemplo")
    # "¿Que te ha parecido?" unas horas despues de usarla, no mientras la usa.
    assert datetime.fromisoformat(fila["proximo"]) >= LUNES_1200 + timedelta(hours=3)
    asunto = sd.contenido(fila, "que_tal", LUNES_1200)["asunto"]
    assert asunto == "Re: te dejo el ejemplo"


def test_pasar_a_pablo_en_la_llamada_es_un_lead_sin_otro_correo(sd, captacion, envios):  # noqa: F811
    _negocio()
    hecho = captacion.llamar(FIJO, "Clínica Sonrisa", "clinica dental", EMAIL, origen="auto", cliente=_Falso())
    captacion.herramienta("pasar_a_pablo", {captacion.CAMPO_LLAMADA: hecho["llamada"], "cuando": "mañana a las 10",
                                            "nombre": "Marta", "notas": "quiere verlo con su agenda"})
    fila = _seg(sd)
    assert fila["estado"] == "cualificado" and fila["cualificado_por"] == "llamada_pablo"
    assert fila["oportunidad_id"]
    assert len(envios["avisos"]) == 1, "solo el aviso de Sara: nada de duplicados"
    assert envios["avisos"][0][0].startswith("🙋")


# --- Recordatorio y panel --------------------------------------------------------------------------

def test_un_recordatorio_si_a_las_24_h_sigue_sin_tocar(sd, envios):
    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    sd.cualificar(seg_id, por="formulario", ahora=LUNES_1200)
    assert sd.recordar(LUNES_1200 + timedelta(hours=5)) == 0
    assert sd.recordar(MARTES_1030 + timedelta(hours=2)) == 1
    assert envios["avisos"][-1][0].startswith("⏰ Sigue esperando")
    assert sd.recordar(MARTES_1030 + timedelta(hours=3)) == 0, "uno solo"


def test_si_pablo_ya_movio_la_oportunidad_no_hay_recordatorio(sd, envios):
    from backend import db

    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    sd.cualificar(seg_id, por="formulario", ahora=LUNES_1200)
    with closing(db._get_db_connection()) as conn:
        conn.execute("UPDATE growth_opportunities SET stage='demo', updated_at='2026-10-05T14:00:00+00:00' "
                     "WHERE id=?", (sd._fila(seg_id)["oportunidad_id"],))
        conn.commit()
    assert sd.recordar(MARTES_1030 + timedelta(hours=2)) == 0


def test_el_embudo_cuenta_leads_por_cada_100_llamadas(sd, captacion, client):  # noqa: F811
    _negocio()
    llamada_id, _ = _demo_de_sara(captacion)
    captacion._actualizar(llamada_id, conversation_id="conv_1")
    sd.cualificar(_seg(sd)["id"], por="formulario", ahora=LUNES_1200)
    embudo = sd.embudo(LUNES_1200 + timedelta(hours=1))
    assert embudo["llamadas_con_persona"] == 1 and embudo["demos_por_sara"] == 1
    assert embudo["cualificados_por_llamada"] == 1 and embudo["leads_por_100_llamadas"] == 100.0
    panel = client.get("/admin/captacion/seguimiento", headers={"Authorization": "Bearer test-admin-token"})
    assert panel.status_code == 200
    assert panel.json()["cualificados"][0]["negocio"] == "Clínica Sonrisa"
    assert client.get("/admin/captacion/seguimiento").status_code in (401, 403)


def test_el_panel_enciende_y_ensena_los_correos(sd, client):  # noqa: F811
    cabeceras = {"Authorization": "Bearer test-admin-token"}
    r = client.put("/admin/captacion/seguimiento/config", json={"encendido": True}, headers=cabeceras)
    assert r.status_code == 200 and r.json() == {"encendido": True}
    vista = client.get("/admin/captacion/seguimiento/vista-previa", headers=cabeceras).json()["toques"]
    assert {t["plantilla"] for t in vista} == {"primero", "valor", "cierre", "que_tal"}
    assert all("{" not in t["texto"] for t in vista)


# --- La demo -------------------------------------------------------------------------------------

def test_la_demo_lleva_el_boton_me_interesa_y_abre_el_formulario(sd, api_module, client):  # noqa: F811
    cliente_id = "demo_auto_sonrisa_test01"
    normalizado = api_module._normalize_client_config(cliente_id, {
        "nombre": "Clínica Sonrisa", "color": "#00b1d9", "icono": "CS", "bienvenida": "Hola.",
        "allowed_origins": ["http://testserver"], "contacto": {"email": EMAIL, "telefono": ""},
        "booking": {"enabled": False}, "whatsapp": {"enabled": False}})
    with api_module.state_lock:
        configs = dict(api_module.CONFIG_CLIENTES)
        configs[cliente_id] = normalizado
        api_module._update_runtime_configs(configs)
    api_module._persist_configs_to_disk(configs)
    api_module._register_demo_tenant(cliente_id, email=EMAIL)
    pagina = client.get("/demo/%s" % cliente_id)
    assert 'href="/interes/demo/%s"' % cliente_id in pagina.text
    _negocio()
    formulario = client.get("/interes/demo/%s" % cliente_id)
    assert formulario.status_code == 200 and "Quiero saber más" in formulario.text
    assert _seg(sd) is None, "abrir la pagina no apunta nada (un antivirus tambien la abre)"
    hecho = client.post("/interes/demo/%s" % cliente_id, data={"r": "si", "como": "video", "cuando": "cuando sea",
                                                               "email": EMAIL, "nombre": "Marta"})
    assert hecho.status_code == 200 and "Pablo te contacta muy pronto" in hecho.text
    fila = _seg(sd)
    assert fila["origen"] == "demo" and fila["estado"] == "cualificado" and fila["cualificado_por"] == "formulario"
    assert client.get("/interes/demo/demo_auto_no_existe_9", follow_redirects=False).status_code == 303


def test_quien_genera_su_demo_en_la_web_entra_en_la_captacion_y_en_seguimiento(sd):
    from backend import outreach

    seg_id = sd.inscribir_demo_web("hola@fisio.es", "Fisio Centro", "Fisioterapia", "https://fisio.es")
    assert seg_id and sd._fila(seg_id)["origen"] == "web"
    with closing(outreach._outreach_db()) as conn:
        prospecto = conn.execute("SELECT * FROM prospects WHERE email='hola@fisio.es'").fetchone()
    assert prospecto["status"] == "engaged" and prospecto["source"] == "demo_web"
    texto = sd.contenido(sd._fila(seg_id), "primero", MARTES_1030)["texto"]
    assert "preparaste en nuestra web la demo de Fisio Centro" in texto


def test_la_ficha_lleva_el_borrador_y_lo_que_pregunto_en_su_demo(sd, monkeypatch):
    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, negocio="Clínica Sonrisa",
                          contacto="Marta", ahora=LUNES_1200)
    with sd._conexion() as conn:
        conn.execute("UPDATE seguimiento_demo SET uso_demo=? WHERE id=?",
                     (json.dumps({"clics": 2, "mensajes": 3, "preguntas": ["¿Tenéis hueco el sábado?"]}), seg_id))
        conn.commit()
    datos = sd.ficha(seg_id)
    assert datos["siguiente"]["mailto"].startswith("mailto:" + EMAIL)
    assert "Hola, Marta:" in datos["siguiente"]["borrador"]
    assert "¿Tenéis hueco el sábado?" in datos["siguiente"]["ideas"][1]
    asunto, texto, html = sd.aviso(datos)
    assert "escribió 3 mensajes al chat" in texto and "abrió el enlace 2 veces" in texto
    assert "<script" not in html


# --- Lo que no puede pasar al apagar y encender, o con dos rondas a la vez -------------------------

def test_una_senal_vieja_no_reabre_a_quien_pablo_descarto(sd, envios):
    _negocio(email="info@noelia.es", nombre="Noelia Brown", sector="peluqueria", telefono="671137353")
    _evento("info@noelia.es", "claim_intent", LUNES_1200 - timedelta(hours=1))
    sd.procesar_senales(LUNES_1200)
    seg_id = _seg(sd, "info@noelia.es")["id"]
    sd.descartar(seg_id, motivo="otro", detalle="Le llame y no", ahora=LUNES_1200 + timedelta(hours=2))
    # Se vuelve a leer todo (al apagar y encender, o si se pierde el cursor): la vieja no cuenta.
    with sd._conexion() as conn:
        conn.execute("DELETE FROM seguimiento_demo_ajustes WHERE clave='cursor_eventos'")
        conn.commit()
    assert sd.procesar_senales(LUNES_1200 + timedelta(hours=3))["cualificados"] == 0
    assert _seg(sd, "info@noelia.es")["estado"] == "descartado" and len(envios["avisos"]) == 1
    # Una nueva, despues de cerrarlo, si: ha vuelto a pulsar.
    _evento("info@noelia.es", "claim_intent", LUNES_1200 + timedelta(hours=4))
    assert sd.procesar_senales(LUNES_1200 + timedelta(hours=5))["cualificados"] == 1


def test_mientras_la_usa_no_se_le_pregunta_que_le_parece(sd):
    _negocio()
    sd.guardar_config(encendido=True)
    sd.inscribir(origen="correo", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200,
                 primero_en=LUNES_1200)
    _evento(EMAIL, "demo_interacted", LUNES_1200 + timedelta(minutes=30))
    hechos, _ = _ronda(sd, LUNES_1200 + timedelta(hours=1))
    assert hechos == []
    assert datetime.fromisoformat(_seg(sd)["proximo"]) == LUNES_1200 + timedelta(minutes=30, hours=3)
    hechos, _ = _ronda(sd, LUNES_1200 + timedelta(hours=4))
    assert [h[1] for h in hechos] == ["que_tal"]


def test_dos_rondas_a_la_vez_no_se_esperan(sd):
    sd.guardar_config(encendido=True)
    assert sd._cerrojo.acquire(blocking=False)
    try:
        assert sd.ronda(ahora=MARTES_1030)["motivo"] == "ya_hay_una_ronda"
    finally:
        sd._cerrojo.release()


def test_el_boton_del_panel_no_se_queda_colgado(sd, client, monkeypatch):  # noqa: F811
    llamadas = []
    monkeypatch.setattr(sd, "ronda", lambda **k: llamadas.append(k) or {"enviados": 0})
    r = client.post("/admin/captacion/seguimiento/ronda", headers={"Authorization": "Bearer test-admin-token"})
    assert r.status_code == 200 and r.json()["ronda"] == {"motivo": "en_marcha"}


# --- Revision de Astra a c00d68c ---------------------------------------------------------------

def test_el_tope_del_buzon_es_uno_para_todos(sd, monkeypatch):
    """Con el tope del dia del buzon ya gastado por la captacion, el seguimiento no suma correos
    encima (solo contaba los suyos). Los SMS no salen por el buzon: siguen."""
    from backend import outreach

    monkeypatch.setattr(outreach, "_outreach_tope_total_del_dia", lambda efectivo: 1)
    with closing(outreach._outreach_db()) as conn:
        conn.execute("INSERT INTO sends (email, stage, subject, sent_at, mode) VALUES (?,?,?,?,?)",
                     ("otro@x.es", "fu1", "x", MARTES_1030.isoformat(timespec="seconds"), "send"))
        conn.commit()
    sd.guardar_config(encendido=True)
    _negocio()
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    sd.inscribir(origen="llamada", canal="sms", destino="675802001", ahora=LUNES_1200)
    hechos, _ = _ronda(sd, MARTES_1030 + timedelta(minutes=5))
    assert [sd._fila(h[0])["canal"] for h in hechos] == ["sms"]
    # Y un toque en duda cuenta en el tope de todos (pudo salir), tambien para el piloto.
    with closing(outreach._outreach_db()) as conn:
        dia = MARTES_1030.date().isoformat()
        assert outreach._outreach_enviados_hoy_total(conn, dia) == 1
        conn.execute("INSERT INTO seguimiento_demo_toques (seguimiento_id, paso, canal, estado, momento) "
                     "VALUES ('sd_dudoso1', 1, 'email', 'incierto', ?)", (MARTES_1030.isoformat(timespec="seconds"),))
        conn.commit()
        assert outreach._outreach_enviados_hoy_total(conn, dia) == 2


def test_si_el_buzon_se_pausa_mientras_espera_turno_no_sale(sd, monkeypatch):
    _negocio()
    sd.guardar_config(encendido=True)
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    pausa = {"activa": False}
    monkeypatch.setattr(sd, "_correo_en_pausa", lambda: pausa["activa"])
    enviados = []
    sd.ronda(ahora=MARTES_1030, esperar_turno=lambda: pausa.update(activa=True),
             mandar=lambda fila, plantilla, paso, momento: enviados.append(paso) or ("<x@y>", "a"))
    assert enviados == []
    with sd._conexion() as conn:
        assert conn.execute("SELECT COUNT(*) FROM seguimiento_demo_toques WHERE seguimiento_id=?",
                            (seg_id,)).fetchone()[0] == 0, "la reserva se suelta: saldra cuando se pueda"


def test_una_demo_nueva_tras_caducar_empieza_de_verdad(sd):
    _negocio()
    sd.guardar_config(encendido=True)
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    hace_tiempo = LUNES_1200 + timedelta(days=16)
    sd.caducar(hace_tiempo)
    assert _seg(sd)["estado"] == "caducado"
    sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=hace_tiempo)
    assert _seg(sd)["creado"] == hace_tiempo.isoformat(timespec="seconds")
    hechos, _ = _ronda(sd, datetime.fromisoformat(_seg(sd)["proximo"]))
    assert [h[1] for h in hechos] == ["primero"], "antes lo volvia a caducar y nunca salia"


# --- El pie de los correos de Pablo ----------------------------------------------------------------

def test_los_correos_de_pablo_llevan_el_pie_profesional(sd):
    """Pablo, 5-oct-2026, al ver un correo con la firma en texto plano: "pon el que tenemos
    nosotros profesional" (el de los correos de captacion: logo, cargo, telefono y web)."""
    from backend import segunda_oportunidad
    import outreach_templates  # type: ignore

    _negocio()
    seg_id = sd.inscribir(origen="llamada", canal="email", destino=EMAIL, prospecto=EMAIL, ahora=LUNES_1200)
    correos = [sd.contenido(sd._fila(seg_id), "primero", MARTES_1030),
               segunda_oportunidad.correo("Pelu", "peluqueria", "https://demo", "ayer")]
    for hecho in correos:
        assert outreach_templates.VANTELIA_SIGNATURE["logo_url"] in hecho["html"]
        assert "Fundador, Vantelia" in hecho["html"] and "Fundador, Vantelia" in hecho["texto"]
        assert "Pablo Sánchez · Vantelia" not in hecho["texto"]
