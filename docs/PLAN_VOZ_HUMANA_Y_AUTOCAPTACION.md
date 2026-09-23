# Plan: voz que suena humana y Vantelia como su propio cliente

Idea de Pablo (23-sep-2026): llevar el asistente de voz al nivel de las agencias
que suenan "practicamente indistinguibles", ser nuestros propios clientes (voz,
widget y WhatsApp de Vantelia hechos con Vantelia) y que la propia agente llame a
los negocios de captacion: la llamada ES la demostracion.

Investigado el 23-sep-2026. Lo marcado **(por verificar)** no se ha probado aun.

---

## Actualizacion 23-sep (noche): la voz sera de ElevenLabs

Medido y escuchado esa misma noche (muestras en `storage/muestras_voz/`, fuera de git):

| Motor | Latencia medida | Veredicto de Pablo |
| --- | --- | --- |
| `gpt-realtime` + alloy (el actual) | 1,25 s | se nota que no es nativa |
| `gpt-realtime-2.1` | 1,45-1,52 s | mas lento, sin ganancia |
| GPT-Live-1 (14 voces) | 0,55-1,02 s (media 0,83) | mejor ritmo, pero voces con acento |
| **ElevenLabs "Laura - Customer service"** (castellana) | Flash v2.5: 0,2 s hasta el primer audio | **"hiperrealista"**; elegida |

Decisiones:
- **Voz: ElevenLabs Agents con Laura y el modelo Flash v2.5** (un agente en espanol
  solo admite Flash o Turbo). Por telefono suena peor que en la web por la propia
  linea (8 kHz), igual que una persona; en la web va a 44,1 kHz.
- La seccion A.2 queda superada: GPT-Live pasa a plan B.
- Plan Starter de ElevenLabs (6 $/mes, 75 min). Para el piloto de llamadas, Creator.
- Riesgo: Laura es una voz de la biblioteca de un tercero. A medio plazo, voz propia.

Hecho:
- **Paso 1** (`backend/voz_elevenlabs.py`, `tests/test_voz_elevenlabs.py`): un agente
  por negocio generado desde las mismas fuentes que la voz de OpenAI (instrucciones,
  saludo con aviso de IA, tools de cita). ElevenLabs pide cada tool a
  `POST /voice/el/{cliente_id}/tool/{nombre}` con secreto compartido, y se ejecuta
  `voice._voice_dispatch_tool`. Sincronizar: `POST /admin/clientes/{id}/voz-elevenlabs`.

Siguientes pasos:
2. Probar a pedir cita de verdad con Sara sobre `van` (tenant de pruebas de Pablo).
3. Conversaciones al panel: webhook de fin de llamada de ElevenLabs -> `voice_calls`.
4. Telefono: numero espanol (91) en Twilio (bundle regulatorio en tramite) conectado
   con "register call" de ElevenLabs (Twilio sigue siendo nuestro), y el telefono del
   llamante como dato de verificacion en las tools.
5. Widget web con el SDK de ElevenLabs.
6. Parte C (llamadas de captacion) sobre este mismo motor.

---

## 0. Resumen en diez lineas

1. **Lo que mas mueve la aguja no es la voz, es el turno.** Las agencias suenan
   humanas por la latencia (<1 s), por escuchar mientras hablan ("aja", "vale") y
   por no cortar ni quedarse mudas. La voz y el acento van despues.
2. **OpenAI saco GPT-Live-1 el 10-sep-2026**: modelo de voz duplex completo (escucha
   y habla a la vez), 0,8 s de turno frente a 1,4 s de gpt-realtime-2.1, 83,6 % de
   tareas resueltas a la primera frente a 45,7 %, y **0,05 $/min**. Delega las
   herramientas en un backend: nuestras tools de cita sirven tal cual.
3. **Hoy usamos `gpt-realtime` (2025) con la voz `alloy`**. Hay dos generaciones
   mas nuevas y OpenAI recomienda `marin`/`cedar` para naturalidad.
4. **Problema legal HOY:** desde el 2-ago-2026 (Reglamento de IA, art. 50) quien
   habla con una IA tiene que saberlo. Nuestro prompt de voz dice "no digas que
   eres una IA". Se arregla en la fase A0, antes que nada.
5. **La web de Vantelia tiene el widget roto**: todas las paginas piden el tenant
   `Vantelia`, que ya no existe en produccion (404).
6. **Tenemos casi todo para llamar**: Twilio configurado, llamada saliente de IA ya
   hecha (confirmaciones de cita), 467 de 486 negocios de captacion con telefono
   (295 fijos, 171 moviles).
7. **Llamar a negocios es legal con condiciones** (Circular AEPD 1/2023): oferta
   relacionada con su actividad, consultar Lista Robinson (gratis hasta 30.000/ano),
   decir al empezar quien llama, que es comercial y que puede oponerse, y que es una
   IA. El prefijo 400 obligatorio desde el 17-oct-2026 parece solo B2C **(abogado)**.
8. **Orden obligatorio: A antes que C.** La llamada en frio es la demo: si la voz no
   esta a la altura, cada llamada es una mala demo. C solo arranca cuando A pase el
   listón medido (seccion A5).
9. Coste estimado: piloto de 50 llamadas ~8 $; regimen de 20 llamadas/dia ~70 $/mes.
10. Decisiones de Pablo en la seccion 7.

---

## 1. Lo que hay hoy (medido el 23-sep-2026)

| Pieza | Hoy | Donde |
| --- | --- | --- |
| Modelo de voz | `gpt-realtime` (ago-2025) | `settings.VOICE_REALTIME_MODEL` |
| Voz | `alloy` por defecto | `settings.VOICE_OPENAI_VOICE` |
| Turnos | `server_vad`, 650 ms de silencio, umbral 0.72 | `voice._voice_audio_input_config` |
| Transcripcion | `whisper-1`, es | idem |
| Identidad | "No digas que eres una IA", "una persona, no un robot" | `voice._voice_build_instructions` (lineas 1312, 1335, 1346) |
| Telefono | Twilio Media Streams -> puente -> `VoiceCallEngine` | `routers/voice_web.py`, `voice_engine.py` |
| Navegador | WebRTC directo a OpenAI + tools por `/voice/widget/{id}/tool` | `widget/voice.js`, `voice_core.js` |
| Llamada saliente | `voice._voice_place_outbound_call(purpose=)` (hoy: confirmar cita) | `voice.py:478` |
| Vantelia en Vantelia | `metareview` (WhatsApp +31, nombre "Vantelia"), `van` (pruebas). Web con `data-client="Vantelia"` -> **404** | `config.json`, `hostinger_site/*` |
| Twilio | credenciales en `.env`; ningun tenant con numero de voz | |
| Captacion | 486 prospects, 467 con telefono (295 fijos / 171 moviles) | `storage/outreach/outreach.db` |

---

## 2. Parte A: que la voz suene humana

### A.1 Como lo hacen (lo que tienen en comun Retell, Vapi, ElevenLabs, Sesame)

Por orden de impacto:

1. **Latencia de voz a voz por debajo de ~0,8 s**, y estable. A partir de 1,2 s la
   gente lo nota y se frustra. El presupuesto: deteccion de turno 200-400 ms,
   primer audio del modelo 300-500 ms, red y audio el resto.
2. **Turnos por significado, no por silencio.** Un modelo decide si la persona ha
   terminado ("a las... eeh... diez") en vez de esperar X ms callados. Evita cortar
   a mitad de frase y evita los silencios largos.
3. **Duplex completo y backchannels**: "aja", "vale", "mhm" mientras el otro habla,
   sin robarle el turno. Es lo que mas diferencia a una persona de un contestador.
4. **Interrupciones bien llevadas**: callar al instante cuando el otro habla de
   verdad, ignorar toses, ruido o un "si si" de asentimiento, y retomar natural
   ("perdona, dime").
5. **Voz expresiva y acento correcto.** En Espana: castellano, no neutro ni latino.
   Vocabulario de aqui ("vale", "genial", "¿te viene bien?"), nada de "ahorita".
6. **Escribir para el oido**: frases cortas, una idea por turno, numeros hablados
   ("a las diez y media"), marcadores naturales ("a ver", "mira", "pues"), nada de
   listas.
7. **No dejar silencio muerto mientras trabaja**: "dejame que lo mire..." mientras
   consulta la agenda. GPT-Live sigue hablando mientras el backend trabaja.
8. **Ambiente**: Retell anade ruido de oficina muy bajo en llamadas telefonicas;
   una linea en silencio absoluto delata. Opcional, a medir.
9. **Pronunciar bien lo propio**: nombre del negocio, calles, nombres de las
   profesionales (pistas de pronunciacion en el prompt).
10. **Despedirse y colgar como una persona**, sin "¿algo mas?" en bucle.

"Indistinguible" no puede significar esconder que es una IA (art. 50, ver C.1). La
meta es: **te dice que es una IA y aun asi te olvidas a los diez segundos.** En la
llamada de captacion eso es justo el argumento de venta.

### A.2 Opciones de motor

| Opcion | Naturalidad | Encaje con lo nuestro | Coste/min | Veredicto |
| --- | --- | --- | --- | --- |
| Seguir con `gpt-realtime` + ajustes | media | total | ~0,10-0,15 $ | solo como paso A1 |
| `gpt-realtime-2.1` | media-alta (mejor silencio, ruido e interrupciones) | cambiar el nombre del modelo | ~0,10 $ | A1, gratis de probar |
| **`gpt-live-1`** | **alta (duplex, backchannels)** | **tools por delegacion: reusa `_voice_dispatch_tool`** | **0,05 $ + backend** | **objetivo** |
| ElevenLabs Agents | alta, voces castellanas y clonacion | segundo motor entero, otro proveedor | 0,08-0,12 $ | plan B si el acento de GPT-Live falla |
| Sesame CSM / modelo propio | muy alta | infraestructura propia (GPU) | variable | descartado: no compensa |

**Riesgo principal de GPT-Live:** desarrolladores reportan acento frances
irregular. El castellano de Espana **(por verificar)** en el prototipo, voz por voz.

### A.3 Fases

**A0. Cumplir la ley (medio dia, YA).**
- `voice._voice_build_instructions`: fuera "no digas que eres una IA" y "una
  persona, no un robot". El saludo dice que es la asistente virtual del negocio de
  forma natural ("Hola, soy Lucia, la asistente virtual de Peluqueria X, ¿en que te
  ayudo?"). Si preguntan "¿eres un robot?", la verdad, sin drama.
- Lo mismo en el saludo saliente de confirmacion y en la demo.
- Test que falle si el prompt vuelve a prohibirlo y si el primer turno no lo dice.
- Afecta a clientes con voz activa: hoy ninguno la tiene en telefono. Coste cero.

**A1. Mejoras sin cambiar de motor (1-2 dias).**
- Medir la linea base ANTES de tocar nada (A5): 10 llamadas de prueba grabadas.
- Voz `marin` o `cedar` por defecto (config por tenant ya existe: `openai_voice`).
- Modelo `gpt-realtime-2.1` (config por tenant ya existe: `realtime_model`).
- Prompt reescrito para el oido y para Espana (A.1 puntos 5-7 y 9).
- `semantic_vad` como opcion a comparar contra `server_vad` 650 ms.
- Repetir la medicion. Si mejora, se queda aunque luego llegue GPT-Live.

**A2. Prototipo GPT-Live en el navegador (3-4 dias).**
- Sesion GPT-Live por WebRTC con **delegacion de cliente**: el modelo pide la tool,
  el front llama a `/voice/widget/{id}/tool` (ya existe) y devuelve el resultado.
  El motor de reservas NO cambia: una sola forma de crear citas.
- Probar las 12 voces con 5 frases de salon en castellano y elegir con panel ciego.
- Medir latencia, interrupciones y aciertos de tools con los guiones de
  `scripts/qa_voice_realtime_*`.
- Interruptor por tenant `voice.engine = realtime | live` para poder volver atras.
- Primero en el tenant de Vantelia (Parte B), nunca en un cliente.

**A3. GPT-Live por telefono (3-5 dias).**
- Opcion 1 (preferida): mantener el puente de Twilio Media Streams y cambiar el
  otro extremo a GPT-Live por WebSocket. Ventaja: controlamos el audio (ambiente,
  grabacion, cortes) y el `VoiceCallEngine` sigue siendo la fuente unica.
  **(por verificar: formato de audio g711 u-law y nombres de eventos.)**
- Opcion 2: SIP directo (OpenAI admite SIP). Menos piezas, menos control.
- Deteccion de contestador de Twilio (0,0075 $/llamada) para la Parte C.

**A4. Llevarlo a los clientes (cuando A3 aguante una semana en Vantelia).**
- Por tenant, con el interruptor de A2. Primero demos, luego plan Business.
- Actualizar `docs/REQUISITOS_ASISTENTE_VOZ.md` y CLAUDE.md (motor de voz).

**A5. Como se mide (listón para pasar a la Parte C).**
- Latencia de voz a voz por turno, p50 y p90 (de `backend/trazas.py`).
- Cortes indebidos (hablo encima) y silencios > 2 s por llamada.
- Aciertos de herramienta en 20 llamadas guionizadas (crear, cambiar, cancelar).
- Naturalidad 1-5 por un panel de 3-5 personas escuchando grabaciones mezcladas
  (actuales, A1, GPT-Live), sin saber cual es cual.
- **Listón**: p90 < 1,2 s, naturalidad media >= 4, cero fallos de herramienta en 20.

---

## 3. Parte B: Vantelia usa Vantelia

Si vendemos un asistente, el nuestro tiene que ser el mejor escaparate. Y cada
fallo lo vemos nosotros antes que un cliente.

**B0. Arreglar el widget de la web (hoy mismo, tras decision 7.6).**
Todas las paginas de `hostinger_site/` piden `data-client="Vantelia"` y produccion
responde 404: la web comercial lleva un widget muerto. O se crea el tenant o se
apunta la web al que ya existe (`metareview` se llama "Vantelia" y tiene
`allowed_origins` de vantelia.es). Replicar en `site_exports/` y desplegar.

**B1. Contenido del tenant (1 dia, con Pablo).**
- Q&A: precios y planes, que incluye cada uno, prueba gratis, permanencia, como se
  conecta WhatsApp (Coexistence), RGPD, que pasa si falla.
- Objeciones reales de captacion: "ya tengo recepcionista", "mis clientas prefieren
  llamar", "no me fio de una IA", "es caro".
- Servicio reservable: "Demo de 15 minutos con Pablo", en las horas que Pablo diga.
- Tono: tu, cercano, sin emojis en voz.

**B2. Canales.**
- Web: widget con "Habla con Sara" (voz en el widget, ya existe, opt-in).
- WhatsApp: el +31 en Coexistence ya contesta con el asistente de Vantelia.
  Valorar numero espanol.
- Telefono entrante: numero de Twilio (fijo de Madrid) con la agente, que se puede
  poner en la web y en la firma de los correos de captacion.

---

## 4. Parte C: Sara llama a los negocios

### C.1 Marco legal (resumen; **revisar con abogado antes de la primera llamada**)

| Norma | Que exige | Como lo cumplimos |
| --- | --- | --- |
| LGTel art. 66.1.b + Circular AEPD 1/2023 | Llamada comercial solo con consentimiento u otra base. Art. 5: se presume licito con autonomos y profesionales si se les ofrece algo de su actividad (art. 19 LOPDGDD) | Solo negocios, a su numero publico de negocio, ofreciendo algo para su negocio |
| Circular art. 4 | Consultar sistemas de exclusion (Lista Robinson) | API de Adigital antes de cada lote (gratis hasta 30.000/ano) |
| Circular art. 6 | Al empezar: quien llama, finalidad comercial, derecho a oponerse | En la primera frase del guion (C.2) |
| Reglamento de IA art. 50 (desde 2-ago-2026) | Informar de que es una IA | "Soy Sara, una asistente virtual..." |
| Ley 10/2025 de atencion a la clientela + resolucion abril 2026 | Llamadas comerciales desde numeracion 400 desde el 17-oct-2026 | Parece solo B2C. **Si el abogado dice que aplica: numero 400 de un operador espanol por SIP** |
| RGPD | Transcripciones y datos | Transcripcion en `voice_calls`; si se graba audio, decirlo al empezar |

Prudencia adicional, aunque la ley no lo pida:
- **Empezar solo por fijos (295).** Los 171 moviles son a menudo el movil personal
  de una autonoma: mas intrusivo, se deja para despues del piloto.
- Una lista de "no llamar" comun con la de bajas del email.
- Si piden no volver a llamar, se apunta en ese mismo momento.

### C.2 El guion (orientado a objetivos, no frases fijas)

El modelo sigue objetivos; estas frases son el tono, no un texto a recitar.

1. **Apertura (obligatoria, legal):** "Hola, buenos dias. ¿Es la Peluqueria Elidio?
   ... Soy Sara, una asistente virtual, o sea, una inteligencia artificial, de
   Vantelia, en Madrid. Te llamo por un tema comercial, un minuto; y si preferis que
   no os llamemos, me lo dices y no volvemos a llamar. ¿Te pillo bien?"
2. **Si es mal momento:** preguntar cuando llamar y colgar. Nada de insistir.
3. **La demo en la propia llamada:** "Te lo explico rapido: yo soy lo que os
   ofrecemos. Cojo el telefono y el WhatsApp de la peluqueria cuando estais con las
   manos ocupadas: doy citas, las cambio, las cancelo. ¿Quieres probarme? Hazte
   pasar por una clienta y pideme cita." Reserva de verdad en una agenda de demo
   (tenant demo del sector, sin datos reales).
4. **Cierre:** "¿Te mando un correo con un enlace para probarlo con los servicios
   de tu peluqueria?" Pedir el correo, **deletrearlo de vuelta** y confirmar.
5. **Salidas:**
   - "La duena no esta": ¿cuando la pillo?, ¿o te dejo el correo para ella?
   - Contestador (deteccion de Twilio): colgar sin dejar mensaje.
   - "¿Eres un robot?": "Si, soy una IA; justo lo que os ofrecemos."
   - Enfado o "no me llames": disculpa, `no_volver_a_llamar`, despedida.
6. **Duracion objetivo:** 60-120 s. Tope duro 4 min.

### C.3 Como se construye (reutilizando lo que hay)

- **Tenant**: el de Vantelia (Parte B). Las llamadas quedan en `voice_calls` con
  `purpose='captacion'` y se ven en Conversaciones sin hacer nada.
- **Nucleo**: `voice._voice_place_outbound_call` con un `purpose` nuevo que no
  necesita `booking_row`, solo el prospect (telefono, nombre del negocio, sector).
- **Instrucciones**: nuevas, como `_voice_outbound_confirm_instructions`; el sector
  sale de `outreach_templates.sector_copy` (misma fuente que los correos).
- **Tools nuevas** (solo en este modo):
  - `registrar_interes(email, nombre)`: valida, lo anota en el prospect y dispara el
    correo "tras la llamada" (plantilla nueva) con el enlace `/demo/go/{token}`.
    La demo personalizada ya se pregenera (`_outreach_maybe_pregenerate_demo`).
  - `volver_a_llamar(cuando, con_quien)`
  - `no_volver_a_llamar(motivo)`: supresion comun con el email.
  - `finalizar_llamada(resultado)`: ya existe; resultados nuevos: interesado,
    no_ahora, no_interesa, no_llamar, contestador, no_contesta.
- **Datos**: tabla `llamadas` en `outreach.db` (prospect, intento, cuando,
  resultado, duracion, coste, call_sid). Un prospect llamado no recibe cold por
  email la misma semana, y viceversa.
- **Worker**: dentro del piloto automatico de captacion, con sus propias ventanas y
  topes (C.4). Apagado por defecto (`OUTREACH_CALLS_ENABLED`).
- **Panel**: en Captacion, fila de llamadas del dia con resultado y transcripcion, y
  boton "llamar ahora" para probar con nuestro propio movil.

### C.4 Guardarrailes

- Ventana: martes a viernes, 10:00-12:30 y 16:00-18:00 (hora de Madrid). Los
  lunes muchas peluquerias cierran; los sabados estan a tope.
- Piloto: 10 llamadas/dia. Maximo 2 intentos por negocio en 14 dias.
- Nunca: Lista Robinson, suprimidos, prospects que ya respondieron, clientes.
- Cualquier fallo de herramienta o una llamada > 4 min para el worker y avisa.
- Kill switch doble (variable de entorno + interruptor del panel), como el
  piloto de email.

### C.5 Piloto y metricas

Piloto de **50 llamadas a fijos de peluquerias** (dos semanas a 10/dia, 5 dias
laborables), sin tocar a los que estan en mitad de secuencia de email.

| Metrica | Para que |
| --- | --- |
| Contestan | ¿llegamos a alguien? |
| Conversacion > 45 s | ¿nos escuchan? |
| Prueban la demo en la llamada | ¿funciona el "wow"? |
| Dan su correo | conversion principal |
| Abren la demo del correo | interes real |
| Reunion / cliente | lo que importa |
| "No llamar" y quejas | coste reputacional |

Comparar con el email en frio de los mismos sectores. Se decide seguir si sale
mejor por contacto y las quejas son ~0.

### C.6 Costes

| Concepto | Precio |
| --- | --- |
| GPT-Live-1 | 0,05 $/min + backend (texto, centimos) |
| Twilio saliente a fijo | 0,018 $/min (movil 0,049 $) |
| Deteccion de contestador | 0,0075 $/llamada |
| Numero espanol | desde 1,15 $/mes |
| Lista Robinson | 0 € hasta 30.000 consultas/ano |

Llamada media de 2 min ~0,15 $. Piloto de 50 ~8 $. 20/dia en dias laborables
~70 $/mes. Con `gpt-realtime` actual, mas o menos el doble por minuto.

---

## 5. Calendario propuesto

| Semana | Parte A | Parte B | Parte C |
| --- | --- | --- | --- |
| 1 (24-sep) | A0 ley, linea base, A1 | B0 widget, B1 contenido | consulta al abogado |
| 2 (1-oct) | A2 GPT-Live navegador + panel de voces | B2 voz en la web | guion + tools, pruebas llamando a nuestros moviles |
| 3 (8-oct) | A3 telefono, medicion A5 | numero entrante | Lista Robinson, worker, panel |
| 4 (15-oct) | A5 listón superado? | | piloto 50 llamadas (si A5 y el abogado dicen si) |

El 17-oct entra lo del prefijo 400: si el abogado dice que nos aplica, el piloto
espera al numero 400.

---

## 6. Riesgos

- **Acento de GPT-Live en castellano**: si no convence, plan B ElevenLabs (A.2).
- **Modelo recien salido (13 dias)**: cambios de API; por eso el interruptor
  `voice.engine` y el motor actual intacto.
- **Una mala llamada se comenta en el barrio**: empezar poco, escuchar TODAS las
  transcripciones del piloto antes de subir el ritmo.
- **Meta y cuentas**: esto no toca Meta (es telefono), pero la regla de no
  automatizar productos de Meta sigue: nada de WhatsApp saliente en frio.
- **Tiempo de Pablo**: la agenda de demos solo funciona si Pablo puede atenderlas.

---

## 7. Decisiones de Pablo

1. **Abogado** para C.1 (B2B y autonomos, prefijo 400, grabacion): si o no, y quien.
2. **Nombre y voz** de la agente (propuesta: "Sara"), y tu o usted (propuesta: tu).
3. **Grabar audio o solo transcripcion** (propuesta: solo transcripcion al principio).
4. **Horas para demos** de 15 min que la agente puede reservar.
5. **Numero**: fijo de Madrid en Twilio ya, o esperar a un 400.
6. **Tenant de Vantelia**: crear `vantelia` limpio o reutilizar `metareview`.
7. **Presupuesto** mensual para llamadas (piloto ~8 $, regimen ~70 $).

---

## Fuentes

- OpenAI, GPT-Live-1: https://developers.openai.com/api/docs/models/gpt-live-1 ,
  https://developers.openai.com/api/docs/guides/live ,
  https://developers.openai.com/api/docs/guides/live-prompting ,
  anuncio: https://community.openai.com/t/introducing-gpt-live-1-in-the-api/1396471
- OpenAI, gpt-realtime-2.1: https://developers.openai.com/api/docs/models/gpt-realtime-2.1
- OpenAI, gpt-realtime y SIP: https://openai.com/index/introducing-gpt-realtime/
- Guia de produccion Realtime 2026: https://www.forasoft.com/blog/article/openai-realtime-api-voice-agent-production-guide-2026
- Turnos, latencia y backchannels: https://futureagi.com/blog/voice-ai-barge-in-turn-taking-2026/ ,
  https://gradium.ai/content/semantic-vad-voice-agents-turn-detection-2026 ,
  https://dasha.ai/blog/voice-ai-latency
- Retell (ruido de fondo, backchannel): https://docs.retellai.com/build/handle-background-noise
- ElevenLabs Agents: https://elevenlabs.io/pricing/agents
- Sesame: https://www.sesame.com/blog/crossing-the-uncanny-valley-of-voice
- Reglamento de IA, art. 50: https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act
- Circular AEPD 1/2023: https://www.boe.es/buscar/doc.php?id=BOE-A-2023-15071
- Prefijo 400: https://www.lamoncloa.gob.es/serviciosdeprensa/notasprensa/transformacion-digital-y-funcion-publica/paginas/2026/160426-prefijo-400-llamadas-comerciales.aspx ,
  https://www.sinologic.net/en/2026-04/prefix-400-for-commercial-calls-in-spain-requirements-deadlines-and-how-it-affects-users-and-operators-boe-2026.html
- Lista Robinson (empresas): https://www.listarobinson.es/empresas
- Twilio, precios en Espana: https://www.twilio.com/en-us/voice/pricing/es
