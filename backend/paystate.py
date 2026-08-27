"""Estado de cobro de una cita: cuanto vale, cuanto se ha cobrado y cuanto falta.

Fuente UNICA para panel, emails y WhatsApp. Nace de un problema real (ago 2026):
una peluqueria cobra 50 EUR de senal y el resto en el salon, pero la cita aparecia
como "Pagado" a secas. La recepcionista veia el badge verde y no sabia que
quedaban 70 EUR por cobrar.

El dinero de una cita puede entrar por DOS sitios (ver docs): `booking_payments`
(el cobro de la reserva: senal, importe completo o retencion) y `customer_payments`
con `kind='pos'` (lo que se cobra en el mostrador). Si solo se mira uno, el saldo
miente. Aqui se suman los dos.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from backend import db, settings

# Estados de cobro que se muestran, de menos a mas resuelto.
SIN_COBRO = "sin_cobro"          # el servicio no lleva pago online
PENDIENTE = "pendiente"          # se pidio pago y no ha entrado nada
RETENIDO = "retenido"            # tarjeta retenida, sin cobrar
SENAL = "senal"                  # pagada una parte (la senal); queda resto
PAGADO = "pagado"                # cubierto del todo
REEMBOLSADO = "reembolsado"

# Estados de `booking_payments` / `customer_payments` que cuentan como dinero cobrado.
_ESTADOS_COBRADOS = {"paid", "partially_refunded"}


def _euros(cents: int) -> str:
    valor = (int(cents or 0)) / 100
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto[:-3] + " €" if texto.endswith(",00") else texto + " €"


def paid_cents_for_bookings(cliente_id: str, booking_ids: List[str]) -> Dict[str, int]:
    """Cobrado por cita sumando los dos sistemas de pago, en dos queries.

    Batch a proposito: el listado de citas del panel no puede permitirse una
    consulta por fila.
    """
    total: Dict[str, int] = {}
    ids = [bid for bid in booking_ids if bid]
    if not cliente_id or not ids:
        return total
    estados = ",".join("?" for _ in _ESTADOS_COBRADOS)
    with db._get_db_connection() as connection:
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            marcas = ",".join("?" for _ in chunk)
            for tabla in ("booking_payments", "customer_payments"):
                try:
                    filas = connection.execute(
                        f"SELECT booking_id, amount_cents, status FROM {tabla} "
                        f"WHERE cliente_id=? AND booking_id IN ({marcas}) "
                        f"AND status IN ({estados})",
                        (cliente_id, *chunk, *_ESTADOS_COBRADOS),
                    ).fetchall()
                except sqlite3.OperationalError as exc:  # noqa: PERF203 - tabla ausente en tests antiguos
                    settings.logger.debug("paystate: no se pudo leer %s: %s", tabla, exc)
                    continue
                for fila in filas:
                    bid = fila["booking_id"]
                    total[bid] = total.get(bid, 0) + int(fila["amount_cents"] or 0)
    return total


def summary(
    price_cents: int,
    paid_cents: int,
    *,
    payment_status: str = "",
    booking_payment_status: str = "",
) -> Dict[str, Any]:
    """Resumen de cobro listo para pintar. No toca la base de datos."""
    price = max(0, int(price_cents or 0))
    paid = max(0, int(paid_cents or 0))
    pending = max(0, price - paid)
    estado_cita = str(payment_status or "").strip()
    estado_pago = str(booking_payment_status or "").strip()

    if estado_pago == "preauthorized" or estado_cita == "preauthorized":
        kind, label = RETENIDO, f"Retención {_euros(paid or price)}"
    elif estado_cita == "refunded":
        kind, label = REEMBOLSADO, "Reembolsado"
    elif paid <= 0:
        if estado_cita in ("pending", "optional") or estado_pago == "pending":
            kind, label = PENDIENTE, "Pendiente de pago"
        else:
            kind, label = SIN_COBRO, ""
    elif pending > 0 and price > 0:
        kind, label = SENAL, f"Señal {_euros(paid)} · faltan {_euros(pending)}"
    else:
        kind, label = PAGADO, f"Pagado {_euros(paid)}" if paid else "Pagado"

    return {
        "kind": kind,
        "label": label,
        "price_cents": price,
        "paid_cents": paid,
        "pending_cents": pending if kind in (SENAL, PENDIENTE) else 0,
    }


def summary_for_booking(
    cliente_id: str,
    booking_row: sqlite3.Row,
    *,
    paid_cents: Optional[int] = None,
    booking_payment_status: str = "",
) -> Dict[str, Any]:
    """Resumen de una cita concreta. `paid_cents` se pasa ya calculado en listados."""
    if paid_cents is None:
        paid_cents = paid_cents_for_bookings(cliente_id, [booking_row["id"]]).get(booking_row["id"], 0)
    claves = booking_row.keys()
    return summary(
        int((booking_row["service_price_cents"] if "service_price_cents" in claves else 0) or 0),
        paid_cents,
        payment_status=(booking_row["payment_status"] if "payment_status" in claves else "") or "",
        booking_payment_status=booking_payment_status,
    )


def customer_line(resumen: Dict[str, Any], ocultar_precio: bool = False) -> str:
    """Como se le cuenta el cobro al CLIENTE final. Una frase, sin jerga.

    Fuente unica para el email de confirmacion, el resumen de WhatsApp y la
    linea del checkout: si la senal se dice de tres formas distintas, el cliente
    llama al salon preguntando cuanto debe.

    `ocultar_precio`: hay negocios que NO dan precios por mensaje -es su norma, y
    el asistente la respeta en todo lo demas-. Decirles "quedan 210 EUR por abonar"
    les cuenta el precio por la puerta de atras, justo a quien se le acaba de
    explicar que el presupuesto se da en persona. Con esto puesto se dice lo que
    ha pagado y nada mas.
    """
    kind = resumen.get("kind")
    pagado = _euros(resumen.get("paid_cents") or 0)
    falta = _euros(resumen.get("pending_cents") or 0)
    if kind == SENAL:
        if ocultar_precio:
            return "Señal de %s pagada. El resto se abona en el centro." % pagado
        return "Señal de %s pagada. Quedan %s por abonar en el centro." % (pagado, falta)
    if kind == PAGADO:
        return "Pagado %s. No tienes que abonar nada más." % pagado
    if kind == RETENIDO:
        return (
            "Hemos retenido %s en tu tarjeta como garantía de la reserva. "
            "No es un cobro." % _euros(resumen.get("paid_cents") or resumen.get("price_cents") or 0)
        )
    return ""


def checkout_line(servicio: str, amount_cents: int, full_cents: int, payment_type: str,
                  ocultar_precio: bool = False) -> Dict[str, str]:
    """Nombre y descripcion de la linea de Stripe Checkout.

    Sin esto, quien paga una senal de 50 EUR de un servicio de 120 EUR ve
    "Corte de pelo — 50,00 EUR" y cree que ese es el precio.

    `ocultar_precio` para los negocios que no dan precios por mensaje: decir "los
    210 EUR restantes se abonan en el centro" es contarle el precio de todas
    formas. Se le dice que es una senal -que es lo que necesita saber para pagar-
    y el resto se ve en el centro.
    """
    nombre = servicio or "Reserva"
    resto = max(0, int(full_cents or 0) - int(amount_cents or 0))
    if payment_type == "preauth":
        return {"name": nombre, "description": "Retención de %s en tu tarjeta como garantía. No es un cobro." % _euros(amount_cents)}
    if payment_type == "deposit" and (resto > 0 or ocultar_precio):
        if ocultar_precio:
            descripcion = ("Señal de %s para reservar. El resto se abona en el centro."
                           % _euros(amount_cents))
        else:
            descripcion = ("Señal de %s para reservar. Los %s restantes se abonan en el centro."
                           % (_euros(amount_cents), _euros(resto)))
        return {"name": "%s · señal" % nombre, "description": descripcion}
    return {"name": nombre, "description": ""}
