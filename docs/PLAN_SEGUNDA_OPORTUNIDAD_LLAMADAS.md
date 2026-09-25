# Plan: segunda oportunidad tras una llamada de Sara

Idea de Pablo (25-sep-2026): a quien no se quedo con el interes en la llamada,
escribirle despues con un mensaje personalizado para su tipo de negocio y volver a
intentarlo. Acordado: **solo a quien no dijo que no**.

## Objetivo

Recuperar las llamadas que se perdieron por el momento, no por el producto: el
negocio que colgo a los pocos segundos o estaba con una clienta recibe **un unico
correo**, personalizado para su sector y con **su propia demo**. Nunca se escribe a
quien rechazo.

## Quien lo recibe (lo decide el CODIGO, no el prompt)

| Como acabo la llamada | Correo |
| --- | --- |
| Colgo al principio, sin escuchar | Si |
| "Ahora no puedo" / ocupado, sin decir que no | Si |
| Interesado (ya recibio la informacion) | No |
| Pidio que le llamemos otro dia | No (lo gestiona Pablo) |
| "No me interesa" | **Nunca** |
| "No me llameis" | **Nunca**, y se da de baja tambien del email |
| No contesto o salto el buzon | No: no oyo nada; lo reintenta el lanzador |

Condiciones ademas del desenlace: tiene email; no esta en bajas, ni ha respondido,
ni es cliente, ni esta descartado; no ha recibido un correo nuestro en los ultimos
3 dias; y **como mucho una segunda oportunidad por negocio, para siempre**.

## Fases

### 0. Antes de nada (bloquea todo lo demas)

- Arreglar los hallazgos de Astra sobre el lanzador y la rotacion de cuentas
  (revisiones del 24-sep: Robinson con respuesta incompleta, condiciones que no se
  revalidan antes de marcar, reintentos tras una conversacion, rotacion que da por
  buena una cuenta sin agentes, errores sin censurar).
- Numero 91 (bundle de Twilio: hay que reenviarlo) para probarlo en real.

### 1. Saber como acabo cada llamada

Hoy solo se apunta interesado / volver a llamar / no llamar. Hace falta distinguir
"colgo sin escuchar" de "dijo que no".

- **Clasificacion al terminar la llamada**, en la propia agente de ElevenLabs
  (recogida de datos del agente): `desenlace` (interesado, volver_a_llamar,
  rechazo, ocupado_sin_rechazo, colgo_al_principio, buzon, persona_equivocada) y
  `escucho_la_demo` (si/no). Verificar la forma exacta de la API al implementarlo.
- **Recepcion**: aviso de fin de llamada de ElevenLabs a
  `POST /voice/el-captacion/fin` (firmado), que guarda desenlace, duracion y resumen
  en `llamadas_voz`. Respaldo: una pasada periodica que lee la conversacion por su
  `conversation_id` si el aviso no llego. Coordinar con el encargo de Astra
  (aviso de fin de llamada -> Conversaciones).
- Lo que apunten las herramientas (interesado, no llamar, volver a llamar) **manda
  sobre la clasificacion**.

### 2. Reglas de envio

- Funcion unica `segunda_oportunidad.elegibles()` con la tabla de arriba, testeada
  caso por caso.
- "No me llameis" pasa a ser baja de TODOS los canales: se anade a la lista de
  supresion de email.
- Cuando: el mismo dia si la llamada fue por la manana, y si no, el siguiente dia
  laborable a media manana. Nunca en fin de semana.
- Una marca por negocio (`segunda_oportunidad_enviada`) impide el segundo envio.

### 3. El correo

- Corto, en nombre de Pablo, por el mismo canal que la captacion por email (Brevo),
  con el pie legal, el enlace de baja y `List-Unsubscribe`.
- Tono: no pregunta "que te parecio" (muchos no llegaron a oir la demo). Esquema:
  "Hace un rato te llamo Sara, nuestra asistente con IA. Te pillamos en mal
  momento. Asi atenderia el telefono de {negocio}: [su demo]". Gancho distinto por
  sector (peluqueria, clinica dental, fisioterapia, estetica, barberia...),
  reutilizando los ganchos por nicho de la captacion por email.
- Enlace: su demo ya generada (`/demo/go/...`), con seguimiento de aperturas y
  clics como el resto de correos.
- Se registra en `sends` con etapa `llamada`, asi la secuencia de emails lo ve y no
  manda otro en los dias siguientes.
- SMS: solo si fue a un movil (llamadas manuales); el lanzador solo llama a fijos.

### 4. Medir

- Panel "Llamadas": columna con el desenlace y estado de la segunda oportunidad
  (enviada / abierta / clic en la demo / respondio).
- La cifra que importa: de cada 100 segundas oportunidades, cuantas pinchan su demo
  y cuantas responden. Si tras las primeras 50 no pincha casi nadie, se replantea el
  texto antes de seguir.

## Pruebas

- Tests de la tabla de elegibilidad (cada fila, incluidas las de "nunca").
- Que "no me llameis" deja al negocio fuera tambien del email.
- Que nunca sale un segundo correo al mismo negocio, ni en fin de semana, ni con un
  correo nuestro en los ultimos 3 dias.
- Prueba real con el telefono de Pablo: colgar a los pocos segundos y recibir el
  correo; decir "no me interesa" y no recibir nada.

## Legal

- El correo a empresas sigue el mismo criterio que la captacion por email actual
  (interes legitimo, pie con razon social, finalidad y baja inmediata). La Lista
  Robinson cubre las llamadas; el correo lleva su propia baja.
- Un solo mensaje por negocio y nunca tras un "no": es lo que evita que parezca
  acoso y lo que reduce el riesgo de reclamacion.

## Esfuerzo estimado

- Fase 0: hallazgos de Astra, medio dia.
- Fase 1: un dia, incluida la verificacion de la API de ElevenLabs.
- Fases 2 y 3: un dia.
- Fase 4: medio dia.

Probarlo en real necesita el numero 91.
