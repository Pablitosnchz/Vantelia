# -*- coding: utf-8 -*-
"""Mide el asistente contra el banco de casos. Un numero, no una sensacion.

Los fallos aparecian de uno en uno, en casa del cliente, y cada arreglo era un
parche. Esto lo convierte en una tirada que se repite igual: si algo empeora se ve
aqui, con nombre y apellidos.

    python scripts/evaluar_asistente.py --cliente alicia_rincon_estilistas
    python scripts/evaluar_asistente.py --caso precio-mechas-sin-cifra
    python scripts/evaluar_asistente.py --db-copia /tmp/qa.db

Habla con el modelo de verdad (cuesta unos centimos) por el recorrido REAL de
WhatsApp. Con `--db-copia` las citas que cree caen en esa copia y no en la agenda
del negocio: uselo siempre contra un cliente vivo.

SALIDA: exit 1 si falla algun caso CRITICO. Los criticos son los que le cuestan
dinero o credibilidad al negocio (inventarse un precio, dar por hecha una cita que
no existe, negar un servicio que si hace).
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import pathlib
import re
import sys
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _norm(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or "").lower())
    return "".join(c for c in limpio if not unicodedata.combining(c))


_DIAS_DE_LA_SEMANA = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_UN_DIA = r"(?:%s)s?" % "|".join(_DIAS_DE_LA_SEMANA)
# «hoy lunes», «mañana, martes 15», «pasado mañana miercoles» hablan de UN dia, no de la
# semana. «por la mañana, sabados» no es un dia relativo.
_DIA_PEGADO_A_HOY = re.compile(
    r"\b(?:hoy|pasado manana|(?<!la )manana)\b[\s,:(]*(?:es\s+|el\s+)?%s\b(?:\s+\d{1,2}\b)?" % _UN_DIA)
_TODA_LA_SEMANA = re.compile(r"\b(?:todos los dias|cada dia|toda la semana|los siete dias|7 dias a la semana)\b")
_SALVO_UN_DIA = re.compile(
    r"\b(?:excepto|salvo|menos|cerramos|cerrado|cerrados|no abrimos|descansamos)(?:\s+\w+){0,2}?\s+%s\b"
    % _UN_DIA)


def _da_el_horario_de_la_semana(texto_normalizado: str) -> bool:
    """¿Cuenta como es la semana, y no solo hoy y mañana? No depende del dia en que se mide.

    Vale nombrar dos dias de la semana, la semana entera («todos los dias») o la
    excepcion («excepto los domingos»); los dias pegados a hoy/mañana no cuentan. No
    comprueba que el horario dicho coincida con el del negocio.
    """
    plano = _DIA_PEGADO_A_HOY.sub(" ", texto_normalizado)
    if _TODA_LA_SEMANA.search(plano) or _SALVO_UN_DIA.search(plano):
        return True
    return len(set(re.findall(r"\b(%s)s?\b" % "|".join(_DIAS_DE_LA_SEMANA), plano))) >= 2


def _cargar_casos():
    from evals import casos_asistente

    return casos_asistente.CASOS


def _ruta_del_banco(ruta):
    return pathlib.Path(ruta).expanduser().resolve()


def _mismo_archivo_del_banco(primero, segundo):
    primero, segundo = _ruta_del_banco(primero), _ruta_del_banco(segundo)
    return (os.path.normcase(str(primero)) == os.path.normcase(str(segundo))
            or (primero.exists() and segundo.exists() and primero.samefile(segundo)))


def _archivos_sqlite_del_banco(ruta):
    base = _ruta_del_banco(ruta)
    return [pathlib.Path(str(base) + sufijo) for sufijo in ("", "-wal", "-shm")]


def _preparar_copia(origen: str, destino: str) -> None:
    """Trabajar sobre una copia: las citas de prueba no tocan la agenda real.

    OJO: `settings.DB_PATH` se calcula al IMPORTAR y no lee la variable de entorno,
    asi que exportar DB_PATH no aislaba nada. Costo siete citas de prueba metidas en
    la agenda de un salon real. Hay que reapuntar el modulo, y despues comprobarlo.
    """
    from contextlib import closing
    import sqlite3

    from backend import settings

    origen_path = _ruta_del_banco(origen)
    destino_path = _ruta_del_banco(destino)
    if not origen_path.is_file():
        raise SystemExit("No existe la base de datos de origen: %s. Se aborta sin crear una copia vacía." % origen_path)
    protegidos = _archivos_sqlite_del_banco(origen_path)
    destinos = _archivos_sqlite_del_banco(destino_path)
    # Validar TODO antes de borrar: Windows puede representar el mismo fichero
    # con mayúsculas, rutas relativas, enlaces o nombres cortos. Sus sidecars
    # también pertenecen al origen y nunca pueden ser el destino de la limpieza.
    for candidato in destinos:
        for protegido in protegidos:
            if _mismo_archivo_del_banco(candidato, protegido):
                raise SystemExit("La copia debe estar separada del origen y sus archivos WAL/SHM. Se aborta sin borrar nada.")
    # mode=ro también evita crear un origen vacío si desaparece tras validarlo.
    # Abrirlo ANTES de limpiar el destino conserva la copia previa si no se puede abrir.
    try:
        origen_db = sqlite3.connect(origen_path.as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise SystemExit("No se puede abrir la base de datos de origen; se aborta sin borrar la copia: %s" % exc) from exc
    # Con `shutil.copyfile` la copia sale DESFASADA: SQLite en modo WAL guarda los
    # ultimos cambios en un fichero aparte (-wal) que no se copia, asi que la copia
    # traia citas ya borradas y el dedup las daba por vivas. `backup()` consolida.
    with closing(origen_db):
        for candidato in destinos:
            try:
                os.remove(str(candidato))
            except FileNotFoundError:
                pass
        with closing(sqlite3.connect(str(destino_path))) as destino_db:
            with destino_db:
                origen_db.backup(destino_db)
    os.environ["DB_PATH"] = str(destino_path)
    settings.DB_PATH = destino_path
    # La copia sale de PRODUCCION, que va por detras del codigo que se mide: si el
    # candidato crea una tabla, aqui no esta y el banco mide un error de esquema en
    # vez del asistente (13-sep-2026: `conversation_states` dio 0 de 41 con "no
    # such table"). Se migra igual que el arnes del humo, con la misma razon.
    from evals import arnes

    arnes._migrar_la_copia()


def _comprobar_aislamiento(destino: str) -> None:
    """Se niega a seguir si las escrituras irian a la base de datos de verdad."""
    from backend import db, settings

    efectiva = str(settings.DB_PATH)
    if not _mismo_archivo_del_banco(efectiva, destino):
        raise SystemExit(
            "NO se esta usando la copia (%s), sino %s. Se aborta para no tocar la "
            "agenda del negocio." % (destino, efectiva)
        )
    with db._get_db_connection() as conexion:
        fichero = conexion.execute("PRAGMA database_list").fetchone()[2]
    if not _mismo_archivo_del_banco(fichero, destino):
        raise SystemExit(
            "las conexiones siguen abriendo %s. Se aborta." % fichero
        )


def _instalar_captura():
    """Usa la captura compartida, incluido el payload de formularios de Meta."""
    from evals import arnes
    arnes.cortar_el_mundo_exterior()
    return arnes.capturar_envios()


def _citas_del_telefono(cliente_id: str, telefono: str):
    """Las citas vivas de ese telefono. Sirve para mirar la AGENDA, no el texto."""
    from backend import db

    with db._get_db_connection() as conexion:
        filas = conexion.execute(
            "SELECT booking_code, status, booking_date, booking_time FROM bookings"
            " WHERE cliente_id=? AND REPLACE(REPLACE(telefono,' ',''),'+','') LIKE ?"
            " ORDER BY created_at", (cliente_id, "%" + telefono[-9:]),
        ).fetchall()
    return [dict(f) for f in filas]


def _preparar_cita(cliente_id: str, telefono: str, indice: int = 0):
    """Le deja una cita ya cogida, para poder probar cancelar y reprogramar.

    Cada caso coge un dia distinto y el ULTIMO hueco: los casos comparten la copia
    de la agenda y, cogiendo todos el primer hueco libre, se quitaban el sitio unos
    a otros y fallaban por colision, no por el asistente.

    Se crea por el nucleo de siempre (`_create_booking_core`), no a mano: si eso se
    rompe, el caso falla al prepararlo, que tambien es informacion.
    """
    from backend import agenda, booking, db, timeutils

    hoy = timeutils._utc_now().date()
    with db._get_db_connection() as conexion:
        empleados = conexion.execute(
            "SELECT * FROM employees WHERE cliente_id=? AND is_active=1 LIMIT 1",
            (cliente_id,),
        ).fetchall()
    if not empleados:
        return None
    servicios = booking._public_services_for_booking(cliente_id)
    servicio = servicios[0]["nombre"] if servicios else ""
    for salto in range(21):
        dia = hoy + __import__("datetime").timedelta(days=2 + salto)
        fecha = dia.isoformat()
        huecos = asyncio.run(agenda._available_slots_for_day(cliente_id, fecha)) or []
        if not huecos:
            continue
        # Empezando por el final y desplazado por caso: asi dos casos no pelean por
        # el mismo hueco (y ninguno le quita el primero al que reserva hablando).
        orden = list(reversed(huecos))
        orden = orden[(indice * 2) % len(orden):] + orden[:(indice * 2) % len(orden)]
        for hora in orden:
            try:
                fila = asyncio.run(booking._create_booking_core(
                    cliente_id, employee_row=empleados[0], nombre="Prueba Eval",
                    email="", telefono=telefono, servicio=servicio,
                    booking_date=fecha, booking_time=hora, notas="",
                    source="eval", send_confirmation=False,
                ))
                return dict(fila)
            except Exception:  # noqa: BLE001
                continue
    return None


def _aplica_a_este_negocio(cliente_id: str, caso: dict) -> bool:
    """Hay casos que dependen de lo que el negocio haya decidido.

    "Si tienes precio publicado, dilo" no vale para quien ha decidido no dar
    precios por mensaje: ahi lo correcto es justo lo contrario, y el caso daba por
    roto un comportamiento CORRECTO.
    """
    condicion = caso.get("solo_si", "")
    if not condicion:
        return True
    if isinstance(condicion, (list, tuple)):
        # Todas a la vez: "presupuesto de alisado pide foto" necesita que haya alisado
        # Y una regla de foto. Una sola que falte y el caso no aplica.
        return all(_aplica_a_este_negocio(cliente_id, dict(caso, solo_si=c)) for c in condicion)
    if condicion.startswith(("tiene_servicio:", "no_tiene_servicio:")):
        # El caso nombra un servicio del salón piloto ("unas mechas", "las cejas"). En
        # un negocio que no lo tiene, pedirlo no mide al asistente: mide el catálogo.
        # Todas las palabras dentro del nombre de un mismo servicio activo.
        from backend import booking, textnorm

        # Nombre O categoria: los alisados del salon se llaman "Keratina premium..." y
        # "Acido lactico bio premium..."; lo que dice "alisado" es su categoria.
        palabras = textnorm._strip_accents(condicion.split(":", 1)[1].lower()).split()
        nombres = [textnorm._strip_accents(("%s %s" % (s.get("nombre") or "", s.get("category") or "")).lower())
                   for s in booking._public_services_for_booking(cliente_id)]
        hay = any(all(p in nombre for p in palabras) for nombre in nombres)
        return hay if condicion.startswith("tiene_servicio:") else not hay
    if condicion.startswith("tiene_regla:"):
        # Una politica del negocio (p. ej. pedir foto): sin esa regla, exigirla seria
        # medir una decision que ese negocio no ha tomado.
        from backend import rules

        accion = condicion.split(":", 1)[1]
        return any(r.get("accion") == accion for r in rules.listar(cliente_id, solo_activas=True))
    if condicion == "telefono_publicado":
        # El rescate "llamanos" solo existe si el negocio publica telefono.
        from backend import clients

        return bool(clients.call_us_line(cliente_id))
    if condicion == "precios_visibles":
        from backend import booking

        return not booking.precios_ocultos(cliente_id)
    if condicion == "sin_precio_global":
        # Solo para quien ha apagado los precios ENTEROS (`mostrar_precios: False`).
        from backend import booking

        return booking.precios_ocultos(cliente_id)
    if condicion.startswith("sin_precio:"):
        # El caso comprueba que NO se da el precio de algo. Si este negocio si lo
        # da, el caso no aplica -y sobre todo: no puede contarse como FALLO-.
        # Paso el 27-ago-2026 y costo una tarde: la copia local no tenia
        # `mostrar_precios` puesto, el asistente daba precios porque asi estaba
        # configurado, y dos casos criticos salian rojos sin haber nada roto.
        from backend import booking

        return bool(booking.no_se_da_precio_de(cliente_id, condicion.split(":", 1)[1]))
    if condicion.startswith("tiene_qa:"):
        # El caso mide que se dice LO QUE EL NEGOCIO TIENE ESCRITO. Si este
        # negocio no lo tiene escrito, el caso no aplica: darlo por roto seria
        # medir una Q&A que nadie configuro, la misma trampa que los precios.
        from backend import rag

        return bool(rag._match_qa_answer(cliente_id, condicion.split(":", 1)[1]))
    return True


def _ficha_del_negocio(cliente_id: str) -> str:
    """Los ajustes del tenant que CAMBIAN lo que contesta, dichos en voz alta.

    La copia local se desvia de produccion sin que nadie lo note, y entonces la
    tirada mide otro producto. Ya ha pasado dos veces el mismo dia -primero
    `booking.estilo`, luego `mostrar_precios`-, las dos con horas perdidas
    persiguiendo fallos que no existian. Aqui se ven de un vistazo y se pueden
    comparar con los del servidor.
    """
    from backend import booking, clients

    try:
        cfg = (clients._get_client_config(cliente_id) or {}).get("booking") or {}
    except Exception:  # noqa: BLE001
        return "no se ha podido leer"
    reglas = booking.familias_sin_precio(cliente_id)
    return "estilo=%s  mostrar_precios=%r  preferir_packs=%r  familias_sin_precio=%s" % (
        cfg.get("estilo") or "guiado", cfg.get("mostrar_precios"),
        cfg.get("preferir_packs"), ",".join(reglas) or "ninguna")


def _quien_contesta(cliente_id: str) -> str:
    """Que cerebro va a atender la tirada: el agente o las listas de siempre.

    Se imprime SIEMPRE porque medir con el cerebro que no es da falsos aprobados
    y no se nota. Paso el 27-ago-2026: en produccion este salon tiene
    `booking.estilo = conversacional` (manda el agente) y la copia local no, asi
    que la tirada contestaba con el RAG generico -"llama al salon"- y el caso
    salia OK sin haber ejercitado ni una linea de lo que se estaba probando.
    """
    from backend import clients, whatsapp

    try:
        config = clients._get_client_config(cliente_id) or {}
    except Exception:  # noqa: BLE001
        return "desconocido"
    if whatsapp._wa_modo_conversacional(config):
        return "el agente (modo conversacional)"
    return ("las listas guiadas (booking.estilo != conversacional): el agente NO "
            "entra, asi que lo que dependa de el NO se esta midiendo")


def _ejecutar_caso(cliente_id: str, caso, dichos, indice: int):
    """Devuelve (paso, respuestas, motivo)."""
    from backend import whatsapp
    from evals import arnes

    telefono = "34600%06d" % (990000 + indice)
    whatsapp._wa_clear_flow(cliente_id, telefono)
    marca = len(dichos)

    # Casos que necesitan una cita ya cogida (cancelar, cambiar de hora).
    previa = _preparar_cita(cliente_id, telefono, indice) if caso.get("con_cita") else None
    if caso.get("con_cita") and not previa:
        raise PrecondicionNoDisponible("no se ha podido preparar la cita previa del caso")
    antes = _citas_del_telefono(cliente_id, telefono)

    mensajes = [m.replace("{codigo}", (previa or {}).get("booking_code", ""))
                for m in caso["mensajes"]]
    for turno, mensaje in enumerate(mensajes, 1):
        try:
            asyncio.run(whatsapp._handle_whatsapp_message(
                cliente_id=cliente_id, phone_number_id="phone_eval",
                from_number=telefono, incoming_text=mensaje,
                interactive_id="", request=None,
            ))
        except arnes.InstrumentoNoCompatible as exc:
            exc.actividad_no_medida = {
                "mensajes_iniciados": mensajes[:turno], "mensajes_completados": turno - 1,
                "respuestas": list(dichos[marca:]),
            }
            whatsapp._wa_clear_flow(cliente_id, telefono)
            raise
        except Exception as exc:  # noqa: BLE001
            whatsapp._wa_clear_flow(cliente_id, telefono)
            return False, dichos[marca:], "ha reventado: %r" % exc
    whatsapp._wa_clear_flow(cliente_id, telefono)

    respuestas = dichos[marca:]
    if caso.get("exige_respuesta") and not respuestas:
        return False, respuestas, "se ha quedado callada"

    # Lo que cuenta de una reserva no es lo que diga, es lo que quede en la agenda.
    exigido = caso.get("agenda")
    if exigido:
        despues = _citas_del_telefono(cliente_id, telefono)
        vivas = [c for c in despues if c["status"] in ("confirmed", "pending_review")]
        nuevas = len(despues) - len(antes)
        if exigido == "crea" and nuevas < 1:
            return False, respuestas, "no ha quedado ninguna cita en la agenda"
        if exigido == "no_crea" and nuevas > 0:
            return False, respuestas, "ha cogido una cita que nadie confirmo"
        if exigido == "cancela" and vivas:
            return False, respuestas, "la cita sigue viva: %s" % vivas
        if exigido == "cambia":
            # Mover no es duplicar: llego a crear una SEGUNDA cita y "reprogramar"
            # la original a su propio sitio. Con solo mirar si habia alguna en otra
            # fecha, eso pasaba por bueno.
            if len(vivas) != 1:
                return False, respuestas, (
                    "tiene que quedar UNA cita viva y hay %d: %s" % (
                        len(vivas), [(c["booking_date"], c["booking_time"]) for c in vivas])
                )
            movidas = [c for c in vivas
                       if (c["booking_date"], c["booking_time"])
                       != ((previa or {}).get("booking_date"), (previa or {}).get("booking_time"))]
            if not movidas:
                return False, respuestas, "la cita no se ha movido de sitio"
    motivo = _falta_en_respuestas(caso, respuestas)
    return not motivo, respuestas, motivo


def _falta_en_respuestas(caso, respuestas) -> str:
    """Lo que el caso exige a las PALABRAS: "" si cumple, o el motivo del fallo."""
    # Se mira la ULTIMA respuesta y el conjunto: hay casos donde lo importante
    # esta en el cierre y otros donde vale que aparezca en cualquier momento.
    todo = _norm(" ".join(respuestas))
    ultimo = _norm(respuestas[-1]) if respuestas else ""

    # Hay cosas que no se pueden medir por vocabulario: el modelo dice "¿que te
    # parece el martes?" o "¿cuando te viene bien?" y las dos valen. Lo que si es
    # objetivo es si le ha soltado un puñado de horas.
    if caso.get("sin_horas"):
        horas = set(re.findall(r"\d{1,2}[:.]\d{2}", " ".join(respuestas)))
        if len(horas) >= 2:
            return "ofrece horas (%s) sin saber que dia quiere" % sorted(horas)[:4]

    debe = caso.get("debe") or []
    if debe and not any(_norm(p) in todo for p in debe):
        return "no dice nada de %s" % debe

    if caso.get("horario_semanal") and not _da_el_horario_de_la_semana(todo):
        return "no da el horario de la semana (solo hoy/manana o nada)"

    # Donde no puede aparecer lo prohibido. Por defecto en ninguna respuesta, pero
    # hay casos en los que decirlo AL PRINCIPIO es lo correcto y el fallo esta en
    # insistir: a "quiero mechas" el negocio ofrece diagnostico -es su politica-, y
    # lo que no vale es repetirlo cuando ella ya ha dicho que no lo quiere. Medir
    # eso contra todas las respuestas castiga justo el comportamiento bueno.
    donde = "ultima" if caso.get("no_debe_en") == "ultima" else "todas"
    for prohibido in caso.get("no_debe") or []:
        objetivo = ultimo if donde == "ultima" else todo
        if _norm(prohibido) in objetivo:
            return "no deberia decir %r" % prohibido
    return ""


class PrecondicionNoDisponible(ValueError):
    """El instrumento no ha podido preparar un requisito previo a conversar."""


def _guardar_informe(destino, informe):
    """Reemplazo atomico: un fallo conserva el ultimo caso ya guardado."""
    destino = _ruta_del_banco(destino)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(destino.parent),
                                     prefix=".banco-", suffix=".json", delete=False) as archivo:
        temporal = pathlib.Path(archivo.name)
        try:
            json.dump(informe, archivo, ensure_ascii=False, indent=2)
        except BaseException:
            archivo.close()
            temporal.unlink()
            raise
    try:
        os.replace(str(temporal), str(destino))
    finally:
        if temporal.exists():
            temporal.unlink()


def _contadores_del_informe(previstos, registros):
    return {
        "previstos": previstos,
        "medidos": sum(r["estado"] in ("ok", "fallo") for r in registros),
        "no_medidos": sum(r["estado"] == "no_medido" for r in registros),
        "no_aplican": sum(r["estado"] == "no_aplica" for r in registros),
        "primer_intento_medido": sum(bool(r["intentos"]) for r in registros),
        "primer_intento_fallido": sum(bool(r["intentos"]) and not r["intentos"][0]["ok"] for r in registros),
        "ok_primer_intento": sum(r["estado"] == "ok" and len(r["intentos"]) == 1 for r in registros),
        "ok_tras_reintento": sum(r["estado"] == "ok" and len(r["intentos"]) == 2 for r in registros),
        "reintentos": sum(len(r["intentos"]) == 2 for r in registros),
        "reintentos_no_medidos": sum(r["estado"] == "no_medido" and len(r["intentos"]) == 1 for r in registros),
        "fallos": {g: sum(r["estado"] == "fallo" and r["gravedad"] == g for r in registros)
                   for g in ("critico", "importante", "deseable")},
    }


def _sha_del_banco():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(pathlib.Path(__file__).resolve().parents[1]),
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _arbol_sucio_del_banco():
    try:
        return bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=str(pathlib.Path(__file__).resolve().parents[1]),
            stderr=subprocess.DEVNULL, text=True,
        ).strip())
    except (OSError, subprocess.CalledProcessError):
        return None


def _motivo_para_no_medir(cliente_id: str) -> str:
    """Por que esta maquina NO puede medir a ese negocio. Vacio si puede.

    Sin los datos RAG del negocio en esta maquina, cada mensaje revienta con "No hay
    datos configurados" y el banco lo contaba como FALLO del asistente. Paso el
    13-sep-2026 midiendo metareview (sus datos solo estan en el servidor): 12 fallos
    que no existian. Eso no es una medicion del asistente: no se mide.
    """
    from backend import settings

    datos = settings.DATA_DIR / cliente_id
    if not datos.exists():
        return "NO MEDIBLE: no hay datos RAG locales de %s en %s" % (cliente_id, datos)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", default="alicia_rincon_estilistas")
    parser.add_argument("--caso", default="", help="ejecutar solo este id")
    parser.add_argument("--db-copia", default="", help="copia la BD aqui y trabaja sobre ella")
    parser.add_argument("--db-origen", default="storage/vantelia.db")
    parser.add_argument("--detalle", action="store_true", help="imprime lo que contesta")
    parser.add_argument("--guardar", default="", help="guarda informe JSON con todos los intentos")
    args = parser.parse_args()
    if args.guardar:
        destino_informe = _ruta_del_banco(args.guardar)
        for ruta_bd in (args.db_origen, args.db_copia):
            if ruta_bd and any(_mismo_archivo_del_banco(destino_informe, archivo)
                               for archivo in _archivos_sqlite_del_banco(ruta_bd)):
                parser.error("el informe debe guardarse fuera de las bases de datos y sus archivos WAL/SHM")
        args.guardar = str(destino_informe)
    inicio = datetime.now(timezone.utc).isoformat()
    identidad = ({"sha": _sha_del_banco(), "arbol_sucio": _arbol_sucio_del_banco()}
                 if args.guardar else {})
    registros = []
    informe = {"version": 1, "cliente": args.cliente, **identidad,
               "inicio_utc": inicio, "fin_utc": None, "estado": "en_curso",
               "contesta": None, "configuracion": None, "casos": registros,
               "contadores": _contadores_del_informe(0, registros)}
    if args.guardar:
        try:
            _guardar_informe(args.guardar, informe)
        except OSError as exc:
            parser.error("no se puede guardar el informe: %s" % exc)

    if args.db_copia:
        _preparar_copia(args.db_origen, args.db_copia)
        _comprobar_aislamiento(args.db_copia)
    elif any(c.get("agenda") or c.get("con_cita") for c in _cargar_casos()):
        # Hay casos que RESERVAN de verdad. Sin copia irian a la agenda del negocio.
        print("Estos casos crean y cancelan citas: usa --db-copia /tmp/eval.db")
        return 2

    casos = [c for c in _cargar_casos() if not args.caso or c["id"] == args.caso]
    if not casos:
        print("no hay ningun caso con ese id")
        return 2

    # Sin los datos del negocio en esta maquina no se conversa (ver la funcion).
    motivo = _motivo_para_no_medir(args.cliente)
    if motivo:
        print(motivo)
        informe.update(estado="no_medible", motivo=motivo,
                       fin_utc=datetime.now(timezone.utc).isoformat())
        if args.guardar:
            _guardar_informe(args.guardar, informe)
        return 2

    # Quien va a contestar, dicho en voz alta antes de empezar: una tirada
    # medida contra el cerebro que no es aprueba sin probar nada.
    contesta = _quien_contesta(args.cliente)
    configuracion = _ficha_del_negocio(args.cliente)
    informe.update(contesta=contesta, configuracion=configuracion)
    def persistir():
        if args.guardar:
            informe["contadores"] = _contadores_del_informe(len(casos), registros)
            _guardar_informe(args.guardar, informe)
    print("Contesta: %s" % contesta)
    print("Config:   %s" % configuracion)
    print()

    dichos = _instalar_captura()
    fallos = {"critico": [], "importante": [], "deseable": []}
    aciertos = 0

    from evals import arnes, calendario

    saltados = 0
    sin_calendario = []
    sin_preparacion = []
    sin_instrumento = []
    for indice, caso in enumerate(casos):
        registro = {"id": caso["id"], "gravedad": caso["gravedad"],
                    "estado": "no_aplica", "motivo": "", "fechas": {},
                    "mensajes": list(caso["mensajes"]), "intentos": []}
        registros.append(registro)
        if not _aplica_a_este_negocio(args.cliente, caso):
            registro["motivo"] = "no aplica a este negocio"
            print("  --   [%-11s] %-34s (no aplica a este negocio)"
                  % (caso["gravedad"], caso["id"]))
            saltados += 1
            persistir()
            continue
        # Resolver una vez: ambos intentos usan la misma fecha y precondiciones.
        try:
            mensajes, fechas = calendario.resolver_mensajes(args.cliente, caso)
        except calendario.CalendarioNoDisponible as exc:
            registro.update(estado="no_medido", motivo=str(exc))
            sin_calendario.append(caso["id"])
            print("NO MEDIDO %-34s calendario: %s" % (caso["id"], exc))
            persistir()
            continue
        caso = dict(caso, mensajes=mensajes)
        registro.update(mensajes=mensajes, fechas=fechas)
        if fechas:
            print("  calendario %s: %s" % (caso["id"], fechas))
        # Al otro lado hay un modelo: la misma pregunta puede salir distinta dos
        # veces. Un fallo DE VERDAD falla las dos; un tropiezo, no. Sin esto, una
        # tirada entera se daba por mala por un traspies -paso con
        # `no-inventar-duraciones`, que al repetirlo contestaba "de 195 a 440
        # minutos"- y una medicion que acusa de mas se deja de mirar igual que una
        # que no acusa nunca.
        try:
            paso, respuestas, motivo = _ejecutar_caso(args.cliente, caso, dichos, indice)
            registro["intentos"].append({"numero": 1, "ok": paso,
                                          "respuestas": list(respuestas), "motivo": motivo})
            registro["estado"] = "en_curso"
            persistir()
            segundo_intento = False
            if not paso:
                segundo_intento = True
                paso, respuestas, motivo = _ejecutar_caso(
                    args.cliente, caso, dichos, indice + 1000)
                registro["intentos"].append({"numero": 2, "ok": paso,
                                              "respuestas": list(respuestas), "motivo": motivo})
                persistir()
        except arnes.InstrumentoNoCompatible as exc:
            registro.update(estado="no_medido", motivo=str(exc))
            registro["actividad_no_medida"] = dict(
                getattr(exc, "actividad_no_medida", {}), numero_intento=len(registro["intentos"]) + 1)
            sin_instrumento.append(caso["id"])
            print("NO MEDIDO %-34s instrumento: %s" % (caso["id"], exc))
            persistir()
            continue
        except PrecondicionNoDisponible as exc:
            registro.update(estado="no_medido", motivo=str(exc))
            sin_preparacion.append(caso["id"])
            print("NO MEDIDO %-34s preparacion: %s" % (caso["id"], exc))
            persistir()
            continue
        registro.update(estado="ok" if paso else "fallo", motivo=motivo)
        marca = "  OK  " if paso else "FALLA "
        print("%s [%-11s] %-34s%s" % (
            marca, caso["gravedad"], caso["id"],
            "  (al segundo intento)" if paso and segundo_intento else ""))
        if paso:
            aciertos += 1
        else:
            fallos[caso["gravedad"]].append((caso, motivo, respuestas))
            print("           %s (%s)" % (
                motivo,
                "en la ultima respuesta" if caso.get("no_debe_en") == "ultima"
                else "las DOS veces",
            ))
            print("           por que importa: %s" % caso.get("por_que", ""))
        if args.detalle and respuestas:
            for r in respuestas:
                print("           > %s" % r.replace("\n", " ")[:160])
        persistir()

    sin_medida = sin_calendario + sin_preparacion + sin_instrumento
    print("\n" + "=" * 68)
    print("  %d de %d medidos; %d no medidos; %d no aplican; %d previstos" % (
        aciertos, len(casos) - saltados - len(sin_medida),
        len(sin_medida), saltados, len(casos)))
    for gravedad in ("critico", "importante", "deseable"):
        if fallos[gravedad]:
            print("  %s: %s" % (
                gravedad.upper(), ", ".join(c["id"] for c, _m, _r in fallos[gravedad])
            ))
    informe.update(estado="terminado", fin_utc=datetime.now(timezone.utc).isoformat())
    persistir()
    if sin_instrumento:
        print("\n  MEDICION INCOMPLETA (instrumento): %s" % ", ".join(sin_instrumento))
        return 1
    if sin_preparacion:
        print("\n  MEDICION INCOMPLETA (preparacion): %s" % ", ".join(sin_preparacion))
    if sin_calendario:
        print("\n  MEDICION INCOMPLETA (calendario): %s" % ", ".join(sin_calendario))
        return 1
    if sin_preparacion:
        return 1
    if fallos["critico"]:
        print("\n  HAY CRITICOS ROTOS: esto no se pone delante de un cliente.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
