"""Audio de una llamada de Sara capturada en el puente, separado por sentido.

Uso (en el VPS, con la captura hecha durante la llamada; el puerto 5099 trae la senalizacion
con Zadarma, que marca el momento en que descuelgan):
    tcpdump -i eth0 -n -s 0 -w llamada.pcap 'udp portrange 10000-10100 or udp port 5099'
    python3 analizar_rtp.py llamada.pcap [carpeta_de_salida]

Saca el nivel de cada sentido cada 0,5 s (dBFS) contando desde el "200 OK" de Zadarma (si
la captura lo tiene; si no, desde el primer paquete de audio), las esperas entre que el
negocio deja de hablar y Sara empieza, y el volumen de Sara por tramo. Escribe negocio.wav
y sara.wav (8 kHz) alineados entre si y con los huecos de red en su sitio.
Sin dependencias: pcap y G.711 (PT 8 = A-law, PT 0 = mu-law) decodificados a mano.
Ver docs/SARA_SIP.md, "El puente".
"""
import math
import os
import struct
import sys
import wave

PUENTE = "72.62.188.104"
ZADARMA = "185.45."  # prefijo de los servidores de Zadarma
UMBRAL = -40.0  # dBFS: por encima, alguien habla (heuristica, no deteccion de turnos)
PASO = 0.5  # segundos por casilla


def alaw(a):
    a ^= 0x55
    t = (a & 0x0F) << 4
    seg = (a & 0x70) >> 4
    if seg == 0:
        t += 8
    else:
        t = (t + 0x108) << (seg - 1)
    return t if a & 0x80 else -t


def ulaw(u):
    u = ~u & 0xFF
    t = ((u & 0x0F) << 3) + 0x84
    t <<= (u & 0x70) >> 4
    return (0x84 - t) if u & 0x80 else (t - 0x84)


TABLAS = {8: [alaw(i) for i in range(256)], 0: [ulaw(i) for i in range(256)]}


def leer(ruta):
    """(flujos, sip). flujos: {(ip_o, puerto_o, ip_d, puerto_d, ssrc): [(t, tipo, carga)]}.
    sip: [(t, ip_o, texto)] de los mensajes SIP por UDP."""
    flujos, sip = {}, []
    with open(ruta, "rb") as f:
        cab = f.read(24)
        endian = "<" if cab[:4] == b"\xd4\xc3\xb2\xa1" else ">"
        while True:
            h = f.read(16)
            if len(h) < 16:
                break
            ts, tus, incl, _ = struct.unpack(endian + "IIII", h)
            datos = f.read(incl)
            if len(datos) < 42 or datos[12:14] != b"\x08\x00":
                continue
            ip = datos[14:]
            if ip[9] != 17:
                continue
            ihl = (ip[0] & 0x0F) * 4
            src = ".".join(str(b) for b in ip[12:16])
            dst = ".".join(str(b) for b in ip[16:20])
            sport, dport = struct.unpack(">HH", ip[ihl:ihl + 4])
            carga_udp = ip[ihl + 8:]
            t = ts + tus / 1e6
            if carga_udp[:7] == b"SIP/2.0" or carga_udp[:6] in (b"INVITE", b"ACK si", b"BYE si"):
                sip.append((t, src, carga_udp.decode("latin-1", "replace")))
                continue
            rtp = carga_udp
            if len(rtp) < 12 or (rtp[0] >> 6) != 2:
                continue
            tipo = rtp[1] & 0x7F
            if tipo not in TABLAS:
                continue
            ssrc = struct.unpack(">I", rtp[8:12])[0]
            off = 12 + 4 * (rtp[0] & 0x0F)
            if rtp[0] & 0x10:
                off += 4 + 4 * struct.unpack(">H", rtp[off + 2:off + 4])[0]
            flujos.setdefault((src, sport, dst, dport, ssrc), []).append((t, tipo, rtp[off:]))
    return flujos, sip


def descolgado(sip):
    """Momento del 200 OK de Zadarma al INVITE (cuando descuelgan), o None."""
    for t, src, texto in sip:
        if src.startswith(ZADARMA) and texto.startswith("SIP/2.0 200") and \
                "INVITE" in texto.split("CSeq:", 1)[-1][:40]:
            return t
    return None


def sentido(clave):
    src, _, dst, _, _ = clave
    if dst != PUENTE:
        return None  # lo que reenvia el puente: es lo mismo, no se mide dos veces
    return "negocio" if src.startswith(ZADARMA) else "sara"


def dbfs(valores):
    rms = math.sqrt(sum(x * x for x in valores) / len(valores)) or 1
    return 20 * math.log10(rms / 32768.0)


def analizar(ruta):
    """Todo lo que se imprime, en datos (para los tests)."""
    flujos, sip = leer(ruta)
    medibles = {k: v for k, v in flujos.items() if sentido(k)}
    if not medibles:
        return None
    primer_rtp = min(p[0][0] for p in medibles.values())
    t_ok = descolgado(sip)
    cero = t_ok if t_ok is not None else primer_rtp
    ultimo = max(p[-1][0] for p in medibles.values())
    casillas = [round(PASO * i, 1) for i in range(int(math.floor((primer_rtp - cero) / PASO)),
                                                  int(math.floor((ultimo - cero) / PASO)) + 1)]
    muestras = {"negocio": {}, "sara": {}}
    wav = {"negocio": {}, "sara": {}}
    descripcion = []
    for clave in sorted(medibles, key=lambda k: medibles[k][0][0]):
        nombre = sentido(clave)
        paquetes = medibles[clave]
        tabla = TABLAS[paquetes[0][1]]
        descripcion.append((nombre, clave, paquetes[0][1], paquetes[0][0] - cero, len(paquetes)))
        for t, _, carga in paquetes:
            valores = [tabla[b] for b in carga]
            casilla = round(PASO * math.floor((t - cero) / PASO), 1)
            muestras[nombre].setdefault(casilla, []).extend(valores)
            # Cada paquete en su sitio: un hueco de red queda como hueco en el WAV.
            inicio = int(round((t - primer_rtp) * 8000))
            for i, v in enumerate(valores):
                wav[nombre][inicio + i] = v
    niveles = {n: {c: dbfs(v) for c, v in m.items()} for n, m in muestras.items()}

    # Una casilla sin paquetes cuenta como "no habla": es precisamente lo que hay que ver.
    esperas, solapes = [], []
    hablaba_n = hablaba_s = False
    fin_n = None
    for c in casillas:
        n = niveles["negocio"].get(c, -99.0) > UMBRAL
        s = niveles["sara"].get(c, -99.0) > UMBRAL
        if hablaba_n and not n:
            fin_n = c
        if s and not hablaba_s:
            if n:  # Sara corta al negocio a media frase: eso no es una espera
                solapes.append(c)
            elif fin_n is not None:
                esperas.append((fin_n, c, round(c - fin_n, 1)))
                fin_n = None
        hablaba_n, hablaba_s = n, s

    tramos, actual = [], []
    for c in casillas:
        v = niveles["sara"].get(c)
        if v is not None and v > UMBRAL:
            actual.append(v)
        elif actual:
            tramos.append(actual)
            actual = []
    if actual:
        tramos.append(actual)
    return {"cero_es_200ok": t_ok is not None, "primer_rtp": primer_rtp - cero, "flujos": descripcion,
            "casillas": casillas, "niveles": niveles, "esperas": esperas, "solapes": solapes,
            "tramos_sara": tramos, "wav": wav}


def escribir_wav(ruta, muestras):
    largo = (max(muestras) + 1) if muestras else 0
    datos = [0] * largo
    for i, v in muestras.items():
        datos[i] = v
    with wave.open(ruta, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<%dh" % largo, *datos))


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else "llamada.pcap"
    salida = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(ruta))
    r = analizar(ruta)
    if r is None:
        print("sin RTP G.711 hacia el puente en la captura")
        return
    print("tiempos desde el %s" % ("200 OK de Zadarma (descuelgan)" if r["cero_es_200ok"]
                                   else "primer paquete de audio: la captura no tiene el 200 OK"))
    for nombre, (src, sp, dst, dp, ssrc), tipo, inicio, n in r["flujos"]:
        print("flujo %-7s %s:%d -> %s:%d  ssrc=%08x  PT=%d  empieza %+.1fs  %d paquetes"
              % (nombre, src, sp, dst, dp, ssrc, tipo, inicio, n))
    print("\n   t     negocio   sara   (dBFS; habla si > %d; --- = sin paquetes)" % UMBRAL)
    for c in r["casillas"]:
        a = r["niveles"]["negocio"].get(c)
        b = r["niveles"]["sara"].get(c)
        marca = ("N" if a is not None and a > UMBRAL else " ") + ("S" if b is not None and b > UMBRAL else " ")
        print("%5.1f  %s  %s  %s" % (c, "%6.1f" % a if a is not None else "   ---",
                                     "%6.1f" % b if b is not None else "   ---", marca))
    print("\nesperas (el negocio deja de hablar -> Sara empieza):")
    for fin, empieza, espera in r["esperas"]:
        print("  %+.1fs -> %+.1fs : %.1f s" % (fin, empieza, espera))
    for c in r["solapes"]:
        print("  %+.1fs : Sara empieza mientras habla el negocio" % c)
    print("\nvolumen de Sara por tramo (media / min / max dBFS):")
    for tr in r["tramos_sara"]:
        print("  %5.1f  %5.1f  %5.1f   (%d x %.1f s)" % (sum(tr) / len(tr), min(tr), max(tr), len(tr), PASO))
    for nombre, muestras in r["wav"].items():
        if muestras:
            escribir_wav(os.path.join(salida, "%s.wav" % nombre), muestras)
    print("\nWAV alineados desde el primer paquete de audio (%+.1fs)." % r["primer_rtp"])


if __name__ == "__main__":
    main()
