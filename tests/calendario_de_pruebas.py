"""Preparación compartida de citas en días abiertos, sin saltos de día a ciegas."""
from datetime import timedelta

from evals import calendario


def proximo_dia_con_hueco(cliente_id, horas=("10:00", "11:00", "12:00")):
    from backend import agenda, timeutils

    return calendario.buscar_dia_con_huecos(
        lambda dia: agenda._build_slots_for_day(cliente_id, dia, duration_minutes=30),
        timeutils._utc_now().date() + timedelta(days=1), horas=horas, dias=14)
