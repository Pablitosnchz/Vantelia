# Revisión c40a60c — 25-sep-2026, 18:57 Europe/Madrid

**Astra. VEREDICTO: CAMBIOS.** SHA exacto
`c40a60c5bcfa036d156cf3e19b99fa9075f2b859`, padre `08df105`.
Copia: `E:/Vantelia-copias/astra/rev-tramos-sara-25sep`.
Solo diff y contexto necesario; implementación intacta, sin push ni despliegue.

## Corregido y verificado

**44 casos anteriores verdes:** 22 originales (montaje adaptado), 3 de recuperación,
8 de responsable, 7 de transcripciones, 3 límites horarios y 1 de reintentos.
Se cierran los tres P2 de la revisión anterior en esas reproducciones.
Veinticuatro recogidas secuenciales a la misma hora consumen ahora **un** intento y
la transcripción se recupera cuando el proveedor vuelve dos horas después.

El script anterior de reintentos tenía una ruta fija a la copia de `08df105`;
`repro_reintentos_actual.py` cambia únicamente esa ruta al cargarlo, sin modificar
aserciones ni código. No se repite pytest ni la suite que Claude mantiene en marcha.

## Hallazgos

1. **Importante / P2 — La negación invierte la disponibilidad.**
   `backend/lanzador_llamadas.py:222`, aplicado en `:267-271`.
   `_HASTA` consume «hasta las cinco» dentro de «el jueves **no está** hasta las
   cinco», dejando fuera la negación. Resultado del recorrido real con Twilio
   ficticio: **marca a las 16:30** cuando aún no está y **bloquea las 17:30** cuando
   ya está. Ambos casos pasan al cargar solo el lanzador de `08df105` en memoria:
   es una regresión causal, **2 rojos candidato / 2 verdes padre**.
   **Arreglo:** interpretar negación y límite conjuntamente, o abstenerse si no se
   comprende la condición completa. Reconocer una hora aislada no autoriza llamar.
   **Cobertura actual:** los tests añadidos cubren «hasta» afirmativo, no negado.

2. **Importante / P2 — El intervalo entre intentos no se reclama atómicamente.**
   `backend/transcripciones_llamadas.py:190`, escritura posterior al HTTP en `:205-210`.
   Varias recogidas simultáneas (exportaciones o exportación y vigilante) seleccionan
   la misma fila antes de que ninguna registre `ultimo`. Todas pueden consumir un
   intento dentro de los 55 minutos. La reproducción fuerza 24 recogidas simultáneas
   con proveedor ficticio 503: **24 intentos a la misma hora; cero recuperaciones**
   cuando el proveedor vuelve a responder dos horas después. El caso consecutivo
   está corregido; el concurrente queda abierto.
   **Arreglo:** reclamar el intento y su plazo transaccionalmente antes del HTTP;
   los competidores deben saltar la fila. No mantener una transacción abierta durante
   la llamada externa. **Cobertura actual:** prueba descargas consecutivas, no simultáneas.

## Evidencia

Base: `E:/Vantelia-copias/astra/evidencias/revision-tramos-sara-c40/`.

| Artefacto | Resultado |
| --- | --- |
| `anteriores.log`, `limites.log`, `responsable.log`, `transcripciones.log`, `horarios.log`, `reintentos.log` | 44 verdes |
| `responsable_negacion.py` / `.log` | 2 fallos, cero errores, 3,652 s |
| `responsable_negacion_padre.log` (`--parent`) | 2 verdes, 6,018 s |
| `transcripciones_concurrencia.py` / `.log` | 1 fallo y 1 control verde, cero errores, 2,347 s |

El control nuevo comprueba 54:59 (no reintenta) y 55:00 (sí reintenta).
El montaje concurrente libera las respuestas simuladas desde el supervisor, para
que también pueda terminar cuando un arreglo impida las peticiones duplicadas.

Huellas SHA-256:

- `responsable_negacion.py`: `81cb4b5c16e925929f76236621a842708d968d92fde04b08e5a7fe7bb4ab493d`.
- `transcripciones_concurrencia.py`: `d657c2e5016b951c08cac46bb5275d0b03032a9136372c1eb014151a38460ee6`.
- `transcripciones_concurrencia.log`: `069fe9d2e965e3cb32f13d29498d67cf7a1c6d26a3aa7d12b3221475f0f4602f`.

Módulos reales, configuración y SQLite ficticias, sockets bloqueados. No llamadas
reales, proveedores reales ni validación del comportamiento de voz del modelo.
Veredictos y reproducciones enviados a Claude por Sincronía. Las pruebas propias
han terminado. Siguiente: corregir estos dos límites y revisar el SHA resultante;
esta revisión no da OK de despliegue a `c40a60c`.
