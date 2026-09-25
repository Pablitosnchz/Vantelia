# Revisión de 08df105 — 25-sep-2026, 17:49 Europe/Madrid

**Astra. VEREDICTO: CAMBIOS.** Código exacto:
`08df105944fec2e8626da8dc86d3263ae7181aae`, padre `246bdce`,
copia `E:/Vantelia-copias/astra/rev-cierre-sara-25sep`.
Solo se revisa este diff y su contexto indispensable. Sin cambios de implementación.

## Lo corregido y verificado

Los **40 casos anteriores pasan**, incluidos los nueve hallazgos de la segunda revisión:

| Reproducción | Casos | Resultado | Tiempo |
| --- | --- | --- | --- |
| Lanzador y cuentas originales, montaje adaptado | 22 | verdes | 9,982 s |
| `repro_limites.py` | 3 | verdes | 2,622 s |
| `repro_5e2.py` | 8 | verdes | 4,412 s |
| `repro_246.py` | 7 | verdes | 2,814 s |

La adaptación de los 22 primeros solo añade las columnas de `llamadas_voz` introducidas
en `5e2c841` y la cuenta sana del montaje del lanzador; no cambia las aserciones ni las
guardas reales. El error de columnas del montaje antiguo no era una regresión del producto.
Se confirma restauración de ausencia de IDs, recuperación de la principal al reiniciar,
rechazo llegado durante Robinson, conservación de anotaciones concurrentes, recuperación
de transcripciones finales, avance de cola y segunda clave tras timeout.

No se encuentra otro defecto concreto en `_restaurar_ids` ni `_sigue_elegible` dentro
del alcance. Los once tests nuevos del commit se leyeron, sin repetir pytest: había una
suite ajena activa al empezar. No se atribuye su ejecución a esta revisión.

## Tres hallazgos pendientes

1. **Importante / P2 — Reconocer el día permite ignorar un horario no interpretado.**
   `backend/lanzador_llamadas.py:224` y `:242`.
   «El jueves de cinco a seis» pierde la hora porque el patrón ahora exige «la(s)».
   Reconocer únicamente jueves basta para `entendido=True`; a las **10:30 del jueves**
   se registra el POST al Twilio ficticio. El mismo caso bloquea con el lanzador del
   padre: antes entendía tarde. **Corrección:** reconocer la restricción completa o
   abstenerse; una parte reconocida no autoriza ampliar la disponibilidad.
   **Cobertura:** los tests nuevos contemplan texto completamente desconocido y hora
   con «a partir de las», no día reconocido con intervalo sin interpretar.

2. **Importante / P2 — «Hasta» se convierte en «desde».**
   `backend/lanzador_llamadas.py:225-231`, aplicado en `:299`.
   «El jueves hasta las cinco» fija `desde=17:00`. La llamada válida de las **16:30**,
   que pasaba en el padre, queda bloqueada y se aplaza hasta cuando la persona ya no
   está. Otro control a las 17:30 muestra que se permite llamar entonces; **esa
   permisividad ya fallaba en el padre**, no se presenta como regresión nueva.
   **Corrección:** distinguir inicio y fin; no interpretar cualquier hora como límite
   inicial. Si la condición no se comprende, no invertirla. **Cobertura:** falta un
   caso con «hasta» y controles a ambos lados del límite.

3. **Importante / P2 — Las exportaciones pueden agotar la recuperación en minutos.**
   `backend/transcripciones_llamadas.py:183-186` y `:201-203`;
   consumidor existente `backend/routers/admin_core.py:575`.
   Cada descarga JSONL lanza `recoger_pendientes`, además del vigilante horario.
   El nuevo contador consume un intento por invocación sin exigir intervalo desde
   `ultimo`. Reproducción: 24 invocaciones a la misma hora con proveedor 503; dos horas
   después el proveedor responde bien, pero hay **cero consultas nuevas y cero
   recuperaciones** porque se alcanzó `MAX_INTENTOS`. El comentario de «un día» no se
   impone en código. **Corrección:** respetar un próximo intento o una ventana real;
   las exportaciones repetidas no deben consumir el presupuesto temporal. Conservar
   el avance justo de la cola. **Cobertura:** el test nuevo prueba avanzar entre
   llamadas pendientes, no agotar intentos antes del plazo.

## Evidencia y límites

Base: `E:/Vantelia-copias/astra/evidencias/revision-cierre-sara-08df/`.

- `anteriores.log`, `limites.log`, `responsable.log`, `transcripciones.log`: los 40 verdes.
- `responsable_limites.py` y `.log`: tres comprobaciones rojas en el candidato;
  con `--parent` se sustituye **solo el lanzador** en memoria por el del padre:
  dos verdes y un fallo preexistente (`responsable_limites_padre.log`).
- `transcripciones_limite.py` y `.log`: un fallo, cero errores, 0,676 s.
- `repro_anteriores_adaptados.py`: montaje compatible para los 22 casos iniciales.

Los scripts del candidato usan módulos reales de la copia exacta, SQLite y configuración
ficticias y sockets bloqueados. Las únicas llamadas son al proveedor simulado. No hay
proveedor real, despliegue, acceso a secretos ni validación de voz con modelo real.
Las tres regresiones nuevas corresponden a cuatro aserciones rojas, una de las cuales
describe el comportamiento preexistente señalado arriba; no son cuatro defectos nuevos.

SHA-256 de los nuevos scripts:

| Script | Huella |
| --- | --- |
| `repro_anteriores_adaptados.py` | `37323520ed9b0619c43c2db3abbdf573e21f87830c405fd6052d16ae3a329d76` |
| `responsable_limites.py` | `3ad0c6c956504785645710bc931fdecb3d3aec701694d6ddd2ae8f4548c01e98` |
| `transcripciones_limite.py` | `5101666542c1e048042f4ed009c267d57244617c9fe3a5e53d73d428e309c4d7` |

## Relevo

Veredicto y reproducciones enviados a Claude por Sincronía. Pruebas propias terminadas,
sin procesos propios pendientes. Siguiente: corregir estos tres límites y revisar el
nuevo SHA. Esta revisión no da OK al despliegue de `08df105`.
