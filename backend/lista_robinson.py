"""Consulta a la Lista Robinson (Adigital) antes de llamar a un negocio.

POR QUE EXISTE
--------------
La Circular 1/2023 de la AEPD (art. 4) obliga a consultar los sistemas de exclusion
publicitaria antes de una llamada comercial sin consentimiento. Sara (captacion por
telefono, `captacion_voz`) solo llama a numeros que NO estan en la lista, y si la
consulta no se puede hacer, NO llama: sin respuesta de la lista no hay llamada.

EL PROTOCOLO (del cliente oficial de Adigital, github.com/adigital-org/slr-client)
---------------------------------------------------------------------------------
- `POST https://api.listarobinson.es/v1/api/user`, firmado con AWS SigV4 en la
  query string (region `eu-west-1`, servicio `execute-api`) con la clave y el
  secreto de la empresa (`ROBINSON_API_KEY` / `ROBINSON_API_SECRET`).
- El cuerpo son hasta 60 huellas SHA-256 separadas por comas, sin repetir. NUNCA se
  manda el telefono: la huella es `sha256("04" + telefono normalizado)`, donde "04"
  es el canal de llamadas y el telefono va como "0034911234567".
- La respuesta es `{huella: {"found": true|false, ...}}`: `found` = esta en la lista.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote, urlparse

import httpx

from backend import settings

URL = "https://api.listarobinson.es/v1/api/user"
REGION = "eu-west-1"
SERVICIO = "execute-api"
CANAL_LLAMADAS = "04"
HUELLAS_POR_PETICION = 60


def configurada() -> bool:
    return bool(settings.ROBINSON_API_KEY and settings.ROBINSON_API_SECRET)


def normalizar(telefono: str) -> str:
    """Igual que el cliente oficial: "+34 91 123..." y "91 123..." -> "0034911234567"."""
    valor = str(telefono or "").strip()
    digitos = re.sub(r"[^0-9]", "", valor)
    if valor.startswith("+"):
        return "00" + digitos
    if valor.startswith("00"):
        return digitos
    return "0034" + digitos


def huella(telefono: str) -> str:
    return hashlib.sha256((CANAL_LLAMADAS + normalizar(telefono)).encode()).hexdigest()


def _hmac(clave: bytes, mensaje: str) -> bytes:
    return hmac.new(clave, mensaje.encode(), hashlib.sha256).digest()


def firma_query(url: str, cuerpo: str, clave: str, secreto: str,
                ahora: Optional[datetime] = None) -> str:
    """Query string SigV4 (la misma construccion que Signing.js del cliente oficial)."""
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sello = ahora.strftime("%Y%m%dT%H%M%SZ")
    dia = sello[:8]
    partes = urlparse(url)
    alcance = "/".join([dia, REGION, SERVICIO, "aws4_request"])
    query = ("X-Amz-Algorithm=AWS4-HMAC-SHA256"
             "&X-Amz-Credential=" + quote(clave + "/" + alcance, safe="") +
             "&X-Amz-Date=" + sello +
             "&X-Amz-SignedHeaders=host")
    peticion_canonica = "\n".join([
        "POST", partes.path, query, "host:%s\n" % partes.netloc, "host",
        hashlib.sha256(cuerpo.encode()).hexdigest(),
    ])
    a_firmar = "\n".join(["AWS4-HMAC-SHA256", sello, alcance,
                          hashlib.sha256(peticion_canonica.encode()).hexdigest()])
    llave = _hmac(("AWS4" + secreto).encode(), dia)
    for trozo in (REGION, SERVICIO, "aws4_request"):
        llave = _hmac(llave, trozo)
    firma = hmac.new(llave, a_firmar.encode(), hashlib.sha256).hexdigest()
    return "?" + query + "&X-Amz-Signature=" + firma


def consultar(telefonos: Iterable[str], *, cliente: Optional[httpx.Client] = None) -> Dict[str, bool]:
    """{telefono: esta_en_la_lista}. Lanza si no se puede consultar: quien llama NO
    debe interpretar un fallo como "no esta"."""
    if not configurada():
        raise RuntimeError("Lista Robinson sin configurar (ROBINSON_API_KEY / ROBINSON_API_SECRET).")
    por_huella: Dict[str, List[str]] = {}
    for telefono in telefonos:
        por_huella.setdefault(huella(telefono), []).append(telefono)
    resultado: Dict[str, bool] = {}
    huellas = list(por_huella)
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=30.0)
    try:
        for i in range(0, len(huellas), HUELLAS_POR_PETICION):
            lote = huellas[i:i + HUELLAS_POR_PETICION]
            cuerpo = ",".join(lote)
            r = cliente.post(URL + firma_query(URL, cuerpo, settings.ROBINSON_API_KEY,
                                                settings.ROBINSON_API_SECRET),
                             content=cuerpo.encode())
            if r.status_code >= 400:
                raise RuntimeError("Lista Robinson respondio %s: %s" % (r.status_code, r.text[:200]))
            datos = r.json()
            if not isinstance(datos, dict):
                raise RuntimeError("La Lista Robinson devolvio una respuesta que no se entiende.")
            for h in lote:
                entrada = datos.get(h)
                encontrado = entrada.get("found") if isinstance(entrada, dict) else None
                # Solo un booleano de verdad decide: `{}`, `null` o `found: null` NO son
                # "no esta en la lista" (revision de Astra, 24-sep-2026: con eso se llamaba).
                if not isinstance(encontrado, bool):
                    raise RuntimeError("La Lista Robinson no contesto bien por todos los numeros.")
                for telefono in por_huella[h]:
                    resultado[telefono] = encontrado
    finally:
        if propio:
            cliente.close()
    return resultado
