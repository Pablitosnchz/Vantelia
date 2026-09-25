# Revisión 5dcc0ad — 25-sep-2026, 19:53 Europe/Madrid

**Astra. VEREDICTO: CAMBIOS.** SHA exacto
`5dcc0adc91805223113145b8556fb3c530d30c82`, padre `c40a60c`.
Copia: `E:/Vantelia-copias/astra/rev-cas-sara-25sep`.
Solo diff y contexto indispensable; implementación intacta.

## Corregido y validado

**23 pruebas relacionadas verdes**: responsable (8), límites horarios (3), negación
«no está hasta» (2), transcripciones (7), reintentos secuenciales (1) y concurrencia (2).
Los dos P2 anteriores quedan corregidos en sus reproducciones.

La reclamación de intentos mediante upsert condicional se confirma por lectura y
comportamiento: 24 recogidas simultáneas gastan **un** intento, recuperan la
transcripción dos horas después y respetan la frontera 54:59/55:00. Se aprueba esa
parte del cambio dentro del alcance revisado. El adaptador del repro concurrente
solo cambia la ruta fija anterior al SHA actual; conserva las aserciones.

No se repiten los 25 casos ajenos a las funciones cambiadas ni la suite completa de Claude.
El resultado completo del candidato no se ha comprobado aquí; tampoco se presenta
la suite anterior de `c40a60c` como evidencia de este SHA.

## Único hallazgo pendiente

**Importante / P2 — `_NO_HASTA` convierte una duda en disponibilidad.**
`backend/lanzador_llamadas.py:221`, aplicado antes de `_NEGACION`.

Con «el jueves **no sé si está hasta las cinco**», el patrón de cero a tres palabras
arbitrarias consume `no se si esta hasta las cinco` y lo convierte en `desde=17:00`.
La duda desaparece de `resto`; la comprobación de negación posterior ya no la detecta.
A las **17:30** el recorrido real alcanza el POST a Twilio ficticio, aunque no se ha
acreditado esa disponibilidad. Cargando solo el lanzador del padre `c40a60c` en memoria,
el mismo caso no marca: **1 rojo candidato / 1 verde padre**.

**Arreglo:** no usar palabras arbitrarias como prueba de que la frase significa
«disponible desde». Limitar el reconocimiento a expresiones comprendidas o devolver
`entendido=False`; una duda no autoriza una rellamada. **Cobertura actual:** los nuevos
tests verifican «no llega», «no está» y otra negación, pero no incertidumbre dentro
del fragmento que `_NO_HASTA` consume.

## Evidencia y relevo

Base: `E:/Vantelia-copias/astra/evidencias/revision-cas-sara-5dcc/`.

- `responsable.log`, `horarios.log`, `negacion.log`, `transcripciones.log`,
  `reintentos.log`, `concurrencia.log`: 23 verdes, cero errores.
- `responsable_incertidumbre.py` y `.log`: un fallo, cero errores, 2,349 s.
- `responsable_incertidumbre_padre.log` (`--parent`): un verde, 1,454 s.
- SHA-256 del script causal:
  `7a925de5639d6cdbc960bedc8c9d5c7960a8276f1b3cc19e69241eebc5101d24`.

Módulos reales con SQLite y configuración ficticias; sockets bloqueados. Sin pytest
duplicado, proveedores reales, secretos, cambios de implementación ni despliegue.
El veredicto y las reproducciones se han entregado a Claude por Sincronía. Pruebas
propias terminadas. Siguiente: corregir este único P2 y revisar el SHA resultante;
no se da OK de despliegue a `5dcc0ad`.
