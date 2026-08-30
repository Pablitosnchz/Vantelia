"""La suite no puede hablar con el buzon de verdad.

Incidente ago-2026: pytest cargaba el .env real (settings.py hace load_dotenv
sin override) y los tests de reserva mandaban confirmaciones de VERDAD por
smtp.hostinger.com a direcciones inventadas (@test.es, @example.com). Cientos
de rebotes duros -> Hostinger suspendia el envio de info@vantelia.es y acababa
en el limite diario del buzon.

El cortafuegos vive en tests/conftest.py y se aplica al importarse. Estos tests
son la alarma: si alguien lo quita o el .env vuelve a colarse, saltan aqui y no
en la bandeja de un desconocido.
"""
from __future__ import annotations

import imaplib
import smtplib

import pytest

from conftest import ENTORNO_AL_ARRANCAR_LA_SUITE


def test_el_entorno_de_los_tests_no_trae_credenciales_reales():
    sucias = sorted(k for k, v in ENTORNO_AL_ARRANCAR_LA_SUITE.items() if v)
    assert not sucias, "El .env real se ha colado en la suite: " + ", ".join(sucias)


def test_no_se_puede_abrir_smtp_de_verdad():
    with pytest.raises(RuntimeError, match="no pueden abrir conexiones SMTP"):
        smtplib.SMTP("smtp.hostinger.com", 587)
    with pytest.raises(RuntimeError, match="no pueden abrir conexiones SMTP"):
        smtplib.SMTP_SSL("smtp.hostinger.com", 465)


def test_no_se_puede_abrir_imap_de_verdad():
    with pytest.raises(RuntimeError, match="no pueden abrir conexiones IMAP"):
        imaplib.IMAP4_SSL("imap.hostinger.com", 993)


def test_enviar_un_email_desde_el_codigo_nunca_llega_a_la_red(api_module):
    """O el canal se ve sin configurar, o el cortafuegos corta la conexion.

    Los dos caminos acaban en RuntimeError; ninguno abre un socket. Otros
    ficheros de la suite dejan SMTP_HOST con hosts de mentira en el entorno del
    proceso, asi que aqui no se puede exigir que este vacio: se exige que no
    salga nada.
    """
    from backend import emailing

    assert "hostinger" not in emailing._smtp_host()
    with pytest.raises(RuntimeError):
        emailing._send_email_message("nadie@example.invalid", "asunto", "texto")
