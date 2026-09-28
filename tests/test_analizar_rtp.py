# -*- coding: utf-8 -*-
"""El analizador de audio del puente de Sara (deploy/sara-puente/analizar_rtp.py) mide bien.

POR QUE EXISTE
--------------
28-sep-2026: con el puente se vio que Zadarma a veces entrega silencio al descolgar, y la
medida se hace con este analizador. Astra reprodujo cuatro fallos que podian esconder
justo lo que se buscaba: los tramos sin paquetes desaparecian (una espera de 4 s salia de
0 s), los WAV pegaban los paquetes sin sus huecos, dos flujos de la misma IP se pisaban, y
una pausa del negocio contaba como "espera" aunque volviera a hablar. Capturas sinteticas
en memoria: no hace falta red ni telefono.
"""
from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[1] / "deploy" / "sara-puente" / "analizar_rtp.py"
_spec = importlib.util.spec_from_file_location("analizar_rtp", RUTA)
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)

PUENTE = ar.PUENTE
ZADARMA = "185.45.152.34"
ELEVENLABS = "34.45.104.162"
VOZ = 0xAA        # A-law casi a fondo de escala
SILENCIO = 0xD5   # A-law del silencio: lo que manda Zadarma cuando no pasa la voz


def _registro(t, src, sport, dst, dport, carga):
    udp = struct.pack(">HHHH", sport, dport, 8 + len(carga), 0) + carga
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
                     bytes(int(x) for x in src.split(".")), bytes(int(x) for x in dst.split("."))) + udp
    trama = b"\x00" * 12 + b"\x08\x00" + ip
    segundos = int(t)
    return struct.pack("<IIII", segundos, int(round((t - segundos) * 1e6)), len(trama), len(trama)) + trama


def _flujo(desde, hasta, src, sport, dport, ssrc, byte):
    """RTP A-law de 20 ms, de `desde` a `hasta` (segundos), todo con el mismo byte."""
    registros, t, seq = [], desde, 0
    while t < hasta - 1e-9:
        rtp = struct.pack(">BBHII", 0x80, 8, seq, seq * 160, ssrc) + bytes([byte]) * 160
        registros.append((t, _registro(t, src, sport, PUENTE, dport, rtp)))
        t = round(t + 0.02, 3)
        seq += 1
    return registros


def _captura(tmp_path, *partes):
    registros = sorted((r for parte in partes for r in parte), key=lambda x: x[0])
    ruta = tmp_path / "llamada.pcap"
    with open(ruta, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for _, registro in registros:
            f.write(registro)
    return ar.analizar(str(ruta))


def test_un_hueco_sin_paquetes_no_se_come_la_espera(tmp_path):
    r = _captura(tmp_path,
                 _flujo(100.0, 101.0, ZADARMA, 16000, 10000, 1, VOZ),
                 _flujo(105.0, 106.0, ELEVENLABS, 11000, 10002, 2, VOZ))
    assert r["esperas"] == [(1.0, 5.0, 4.0)], "4 s sin paquetes siguen siendo 4 s de espera"
    assert 3.0 in r["casillas"] and 3.0 not in r["niveles"]["negocio"], "el hueco sale como hueco"


def test_los_wav_conservan_los_huecos_y_van_alineados(tmp_path):
    r = _captura(tmp_path,
                 _flujo(100.0, 101.0, ZADARMA, 16000, 10000, 1, VOZ),
                 _flujo(105.0, 106.0, ELEVENLABS, 11000, 10002, 2, VOZ))
    assert min(r["wav"]["negocio"]) == 0
    assert min(r["wav"]["sara"]) == 5 * 8000, "Sara empieza 5 s despues, tambien en su WAV"
    assert max(r["wav"]["sara"]) == 6 * 8000 - 1


def test_dos_flujos_de_la_misma_ip_no_se_pisan(tmp_path):
    r = _captura(tmp_path,
                 _flujo(100.0, 101.0, ZADARMA, 16000, 10000, 1, VOZ),      # tono antes de descolgar
                 _flujo(103.0, 104.0, ZADARMA, 16002, 10000, 7, SILENCIO))  # otro puerto y otro SSRC
    negocio = [f for f in r["flujos"] if f[0] == "negocio"]
    assert len(negocio) == 2
    assert r["niveles"]["negocio"][0.0] > -10 and r["niveles"]["negocio"][3.0] < -70


def test_si_el_negocio_vuelve_a_hablar_no_hay_espera_falsa(tmp_path):
    r = _captura(tmp_path,
                 _flujo(100.0, 101.0, ZADARMA, 16000, 10000, 1, VOZ),
                 _flujo(101.0, 102.0, ZADARMA, 16000, 10000, 1, SILENCIO),
                 _flujo(102.0, 103.0, ZADARMA, 16000, 10000, 1, VOZ),
                 _flujo(102.5, 104.0, ELEVENLABS, 11000, 10002, 2, VOZ))
    assert r["esperas"] == [], "Sara le corto a media frase: eso no es una espera"
    assert r["solapes"] == [2.5]


def test_el_jitter_no_se_come_audio_en_el_wav(tmp_path):
    """Dos paquetes seguidos que llegan con 1 ms de diferencia no se pisan en el WAV: van
    donde dice su marca de tiempo RTP, no donde cayo su llegada."""
    voz = struct.pack(">BBHII", 0x80, 8, 0, 0, 5) + bytes([VOZ]) * 160
    silencio = struct.pack(">BBHII", 0x80, 8, 1, 160, 5) + bytes([SILENCIO]) * 160
    r = _captura(tmp_path, [(100.0, _registro(100.0, ZADARMA, 16000, PUENTE, 10000, voz)),
                            (100.001, _registro(100.001, ZADARMA, 16000, PUENTE, 10000, silencio))])
    wav = r["wav"]["negocio"]
    assert len(wav) == 320
    assert all(wav[i] > 30000 for i in range(160)), "la voz del primero entera"


def test_paquetes_desordenados_al_principio_no_revientan_el_wav(tmp_path):
    """Revision de Astra: si el primero que llega es el segundo (timestamp 160 y luego 0), la
    resta sin signo lo mandaba a 4.294.967.136 y el WAV pedia 32 GiB. Una marca imposible
    (media hora mas alla) tampoco puede estirar el WAV."""
    segundo = struct.pack(">BBHII", 0x80, 8, 1, 160, 9) + bytes([SILENCIO]) * 160
    primero = struct.pack(">BBHII", 0x80, 8, 0, 0, 9) + bytes([VOZ]) * 160
    loco = struct.pack(">BBHII", 0x80, 8, 2, 160 + 2 ** 31, 9) + bytes([VOZ]) * 160
    r = _captura(tmp_path, [(100.0, _registro(100.0, ZADARMA, 16000, PUENTE, 10000, segundo)),
                            (100.001, _registro(100.001, ZADARMA, 16000, PUENTE, 10000, primero)),
                            (100.002, _registro(100.002, ZADARMA, 16000, PUENTE, 10000, loco))])
    wav = r["wav"]["negocio"]
    assert min(wav) == 0 and max(wav) == 319, "320 muestras, en su orden"
    assert all(wav[i] > 30000 for i in range(160)), "el que llego tarde va delante"
    assert r["inicio_wav"] == pytest.approx(-0.02)


@pytest.mark.parametrize("con_200ok", [True, False])
def test_cuenta_desde_que_descuelgan(tmp_path, con_200ok):
    sip = []
    if con_200ok:
        texto = (b"SIP/2.0 200 OK\r\nVia: SIP/2.0/UDP 72.62.188.104:5099\r\n"
                 b"CSeq: 102 INVITE\r\nContent-Length: 0\r\n\r\n")
        sip = [(102.0, _registro(102.0, "185.45.155.14", 5060, PUENTE, 5099, texto))]
    r = _captura(tmp_path, _flujo(100.0, 105.0, ZADARMA, 16000, 10000, 1, SILENCIO), sip)
    assert r["cero_es_200ok"] is con_200ok
    assert r["primer_rtp"] == (-2.0 if con_200ok else 0.0), "el tono de antes de descolgar no cuenta"
    assert r["casillas"][0] == (-2.0 if con_200ok else 0.0)
