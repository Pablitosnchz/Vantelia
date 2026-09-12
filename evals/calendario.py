"""Fechas reproducibles para instrumentos; nunca cambia la agenda del negocio."""
from datetime import date, timedelta


class CalendarioNoDisponible(ValueError):
    pass


def buscar_dia_con_huecos(consultar, desde, horas=(), dias=30):
    """Consulta fechas futuras hasta encontrar TODOS los huecos requeridos."""
    for salto in range(dias):
        dia = desde + timedelta(days=salto)
        libres = set(consultar(dia.isoformat()) or [])
        if libres and set(horas) <= libres:
            return dia.isoformat()
    raise CalendarioNoDisponible("No hay día con los huecos requeridos en %d días" % dias)


def nombre_del_dia(iso):
    dia = date.fromisoformat(iso)
    # Una fecha con día semanal se interpreta primero como relativa en el núcleo.
    # La fecha numérica incluye el año y conserva el día elegido incluso a >7 días.
    return dia.strftime("%d/%m/%Y")



def resolver_mensajes(cliente_id, caso, codigo=None, *, hoy=None, consultar=None):
    """Sustituye marcadores; sin precondiciones no se mide al asistente.

    consultar devuelve (horas del horario, horas libres). Un día lleno NO es
    un día cerrado. El llamador puede inyectarlo para tests sin modelo ni BD.
    """
    import asyncio

    mensajes = list(caso["mensajes"])
    if not any("{dia_" in m for m in mensajes):
        return ([m.replace("{codigo}", codigo) for m in mensajes]
                if codigo is not None else mensajes), {}
    consultar_cerrado = consultar
    if consultar is None or hoy is None:
        from backend import agenda, booking, clients, reserva

        if hoy is None:
            cfg = clients._get_client_config(cliente_id)
            hoy = reserva.ahora_local(cfg.get("booking", {}).get("timezone", "Europe/Madrid")).date()
        if consultar is None:
            servicio = caso.get("servicio_calendario", "")
            if servicio == "valoracion":
                servicio = str((booking._servicio_de_valoracion(cliente_id) or {}).get("nombre") or "")
                if not servicio:
                    raise CalendarioNoDisponible("El caso requiere un servicio de valoración configurado")
            consultar = lambda dia: asyncio.run(agenda._public_slot_sets_for_day(
                cliente_id, dia, servicio=servicio))
            consultar_cerrado = lambda dia: asyncio.run(agenda._public_slot_sets_for_day(cliente_id, dia))
    valores = {"codigo": codigo} if codigo is not None else {}
    desde = hoy + timedelta(days=1)
    if any("{dia_abierto" in m for m in mensajes):
        iso = buscar_dia_con_huecos(lambda dia: consultar(dia)[1], desde,
                                    horas=caso.get("horas_calendario", ()))
        valores.update(dia_abierto=iso, dia_abierto_nombre=nombre_del_dia(iso))
    if any("{dia_cerrado" in m for m in mensajes):
        for salto in range(30):
            iso = (desde + timedelta(days=salto)).isoformat()
            if not consultar_cerrado(iso)[0]:
                valores.update(dia_cerrado=iso, dia_cerrado_nombre=nombre_del_dia(iso))
                break
        else:
            raise CalendarioNoDisponible("No hay día cerrado en los próximos 30 días")
    for clave, valor in valores.items():
        mensajes = [m.replace("{" + clave + "}", valor) for m in mensajes]
    if any("{dia_" in m for m in mensajes):
        raise CalendarioNoDisponible("Marcador de calendario desconocido")
    return mensajes, {k: v for k, v in valores.items() if k != "codigo"}
