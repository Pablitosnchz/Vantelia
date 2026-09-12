"""Preparación compartida de citas en días abiertos, sin saltos de día a ciegas."""
import asyncio
from datetime import timedelta

from evals import calendario


def proximo_dia_con_hueco(cliente_id, horas=("10:00", "11:00", "12:00")):
    from backend import agenda, timeutils

    def libres(dia):
        rejilla = agenda._build_slots_for_day(cliente_id, dia, duration_minutes=30)
        return [hora for hora in horas if hora in rejilla and asyncio.run(
            agenda._booking_slot_available(cliente_id, dia, hora, duration_minutes=60))]

    return calendario.buscar_dia_con_huecos(
        libres,
        timeutils._utc_now().date() + timedelta(days=1), horas=horas, dias=14)
