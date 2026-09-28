"""Audio de una llamada de Sara capturada en el puente, separado por sentido.

Uso (en el VPS, con la captura hecha durante la llamada):
    tcpdump -i eth0 -n -s 0 -w llamada.pcap 'udp portrange 10000-10100'
    python3 analizar_rtp.py llamada.pcap [carpeta_de_salida]

Saca el nivel de cada sentido cada 0,5 s (dBFS), las esperas entre que el negocio deja de
hablar y Sara empieza, y el volumen de Sara por tramo. Escribe negocio.wav y sara.wav (8 kHz).
Sin dependencias: pcap y G.711 (PT 8 = A-law, PT 0 = mu-law) decodificados a mano.
Ver docs/SARA_SIP.md, "El puente".
"""
import math
import os
import struct
import sys
import wave

PUENTE = "72.62.188.104"
ZADARMA = "185.45."  # prefijo de los servidores de medios de Zadarma
UMBRAL = -40.0  # dBFS: por encima, alguien habla


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
    """{(origen, destino): [(segundo, tipo, carga), ...]} de los paquetes RTP G.711."""
    flujos = {}
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
            rtp = ip[ihl + 8:]
            if len(rtp) < 12 or (rtp[0] >> 6) != 2:
                continue
            tipo = rtp[1] & 0x7F
            if tipo not in TABLAS:
                continue
            off = 12 + 4 * (rtp[0] & 0x0F)
            if rtp[0] & 0x10:
                off += 4 + 4 * struct.unpack(">H", rtp[off + 2:off + 4])[0]
            flujos.setdefault((src, dst), []).append((ts + tus / 1e6, tipo, rtp[off:]))
    return flujos


def sentido(src, dst):
    if dst == PUENTE:
        return "negocio" if src.startswith(ZADARMA) else "sara"
    return None  # lo que reenvia el puente: es lo mismo, no se mide dos veces


def main():
    ruta = sys.argv[1] if len(sys.argv) > 1 else "llamada.pcap"
    salida = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(ruta))
    flujos = leer(ruta)
    if not flujos:
        print("sin RTP G.711 en la captura")
        return
    t0 = min(p[0][0] for p in flujos.values())
    niveles = {}
    for (src, dst), paquetes in flujos.items():
        nombre = sentido(src, dst)
        if not nombre:
            continue
        tabla = TABLAS[paquetes[0][1]]
        # Cada paquete en su momento de llegada (no uno detras de otro): un hueco en la red
        # sale como hueco, no como audio adelantado.
        serie_muestras = {}
        muestras = []
        for t, _, carga in paquetes:
            valores = [tabla[b] for b in carga]
            muestras.extend(valores)
            clave = round(math.floor((t - t0) * 2) / 2, 1)
            serie_muestras.setdefault(clave, []).extend(valores)
        with wave.open(os.path.join(salida, "%s.wav" % nombre), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(struct.pack("<%dh" % len(muestras), *muestras))
        niveles[nombre] = {
            t: 20 * math.log10((math.sqrt(sum(x * x for x in v) / len(v)) or 1) / 32768.0)
            for t, v in serie_muestras.items()
        }
        print("flujo %-7s %s -> %s  PT=%d  empieza +%.1fs  %d paquetes"
              % (nombre, src, dst, paquetes[0][1], paquetes[0][0] - t0, len(paquetes)))

    tiempos = sorted(set(niveles.get("negocio", {})) | set(niveles.get("sara", {})))
    print("\n   t     negocio   sara   (dBFS; habla si > %d)" % UMBRAL)
    for t in tiempos:
        a = niveles.get("negocio", {}).get(t)
        b = niveles.get("sara", {}).get(t)
        marca = ("N" if a is not None and a > UMBRAL else " ") + ("S" if b is not None and b > UMBRAL else " ")
        print("%5.1f  %s  %s  %s" % (t, "%6.1f" % a if a is not None else "   -  ",
                                     "%6.1f" % b if b is not None else "   -  ", marca))

    print("\nesperas (el negocio deja de hablar -> Sara empieza):")
    hablaba_n = hablaba_s = False
    fin_n = None
    for t in tiempos:
        n = niveles.get("negocio", {}).get(t, -99) > UMBRAL
        s = niveles.get("sara", {}).get(t, -99) > UMBRAL
        if hablaba_n and not n:
            fin_n = t
        if s and not hablaba_s and fin_n is not None:
            print("  +%.1fs -> +%.1fs : %.1f s" % (fin_n, t, t - fin_n))
            fin_n = None
        hablaba_n, hablaba_s = n, s

    tramos, actual = [], []
    for t in sorted(niveles.get("sara", {})):
        v = niveles["sara"][t]
        if v > UMBRAL:
            actual.append(v)
        elif actual:
            tramos.append(actual)
            actual = []
    if actual:
        tramos.append(actual)
    print("\nvolumen de Sara por tramo (media / min / max dBFS):")
    for tr in tramos:
        print("  %5.1f  %5.1f  %5.1f   (%d x 0,5 s)" % (sum(tr) / len(tr), min(tr), max(tr), len(tr)))


if __name__ == "__main__":
    main()
