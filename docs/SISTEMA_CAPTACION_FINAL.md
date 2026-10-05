# Sistema de captación: del "te mando la demo" al lead cualificado

Escrito el 05-oct-2026 (Claude, a petición de Pablo): *"quiero los leads ya cualificados para
ponerme a trabajar con ellos; a partir de ahí ya me encargo yo. Prefiero email."*
Código: `backend/seguimiento_demo.py` (motor) y `backend/routers/seguimiento_web.py` (página
`/interes` y panel). Tests: `tests/test_seguimiento_demo.py`.

---

## 1. El problema

Mandábamos la demo y esperábamos. Nadie volvía a escribir a quien la había pedido, y las
señales de interés se quedaban en la base sin que nadie las viera. El 5-oct a las 13:50
Noelia Brown (peluquería, Alcobendas) abrió su demo y pulsó "Activar gratis e instalar",
no terminó el alta y nadie se enteró.

Lo que se sabe de cómo lo hacen los demás (prospección B2B con demo):

- El primer seguimiento es el que más respuestas trae; más de 3 toques ya no suma y quema.
  Tras mandar algo pedido: a las 24-48 h, luego a los 3-5 días, y un cierre ("¿lo dejo?").
- Correo corto, de persona, pidiendo una **respuesta** y no un clic. Los correos con aspecto de
  marketing (botones, tablas) van a Promociones.
- El contenido se adapta a lo que hizo: no se escribe igual a quien probó la demo que a quien
  no la abrió.
- El traspaso al comercial lo dispara una señal clara ("me interesa"), la automatización se
  calla en ese momento y el comercial recibe el historial entero.
- Velocidad: contactar en menos de una hora multiplica por ~7 la probabilidad de cualificar
  (Harvard Business Review, 2011). Por eso el aviso a Pablo sale en el momento.

## 2. El embudo

```
FUENTES                         SEGUIMIENTO AUTOMÁTICO              CUALIFICADO → PABLO
Sara: "sí, mándamela"   ─┐      correo (o SMS) de Pablo, 2-3 toques  "Me interesa" en el correo o en su demo
Formulario de la web    ─┼──►   adaptado a si probó la demo     ──►  respuesta positiva (la lee la IA)
Correo frío + usa demo  ─┘      se para solo con cualquier señal     botón "Activar"/"duda"/"WhatsApp" de su demo
                                                                     Sara: "que me llame Pablo"
```

Al cualificarse: **aviso inmediato a Pablo con la ficha del lead**, oportunidad creada en el
Plan de escala, prospecto en `replied` (sale de toda automatización: correo frío, Sara y
seguimiento) y aparece en el panel *Llamadas → Leads cualificados*.

## 3. Quién entra en el seguimiento (`inscribir`)

| Origen | Cuándo | Canal |
| --- | --- | --- |
| `llamada` | Sara manda la demo (`enviar_informacion`, también por respaldo o en una entrante) | el de la demo: correo, o SMS a un móvil |
| `web` | Alguien genera su demo en vantelia.es/demo (`POST /demo/generate`, demo nueva) | correo |
| `correo` | Un prospecto de la captación por correo **usa** su demo en los últimos 14 días: abre el chat, le escribe o la llama por voz. Solo señales que hace una persona (las da el JavaScript firmado de la página o el servidor), nunca un clic suelto: los antivirus de correo pinchan los enlaces. Solo con el interruptor encendido; al encenderlo entran también quienes la usaron mientras estaba apagado | correo |

Nunca entra: dado de baja, rebotado, que ya respondió, cliente, descartado, "no me llaméis", ni
quien ya tiene un seguimiento terminado por él mismo (cualificado, descartado, parado).

## 4. Los toques

Días laborables (lunes a viernes, sin festivos nacionales), a partir de las 10:30 y entre las
9:00 y las 19:00 de Madrid. Todos los correos son de Pablo, cortos, en el mismo hilo que el
correo que ya recibieron (el de Sara, el frío o el primero del seguimiento), y piden una
**respuesta**. Llevan dos enlaces discretos: "elegir cuándo os la enseño" y "ahora no".

| Origen | Toque 1 | Toque 2 | Toque 3 (cierre) |
| --- | --- | --- | --- |
| `llamada`, `web` | +1 día: "¿pudisteis verla?" (o "¿qué os pareció?" si la probó) | +3: el caso de su sector con el audio de una llamada real | +5: "¿la dejo preparada o lo dejamos aquí?" |
| `correo`, `demo` | 3 h después de usarla: "¿qué te ha parecido?" | — | +4: cierre |
| SMS (móvil sin correo) | +1 día | — | +8: cierre |

Se para solo, antes de cada toque y otra vez justo antes de enviarlo: respuesta, baja, rebote,
"no me interesa", cualificado, "no me llaméis", estado `replied/client/lost/baja/bounced`,
interruptor apagado, pausa automática del buzón de captación o SMTP caído. Tope de 20 correos y
10 SMS al día, con el espaciado global de todos los correos de captación. Un toque se reserva
antes de enviarlo: si el envío queda en duda no se repite (mejor uno de menos que dos).

Si aún la está usando, el "¿qué te ha parecido?" espera a 3 horas después de la última vez. Antes
del primer correo con el enlace se adelanta su demo (caducan a los 7 días), para que abra al momento.

Mientras un negocio está en seguimiento, la secuencia de correo frío no le escribe y Sara no le
llama.

## 5. La página "¿Te ha gustado?" (`/interes/{token}`)

El enlace de los correos y SMS. El botón "Me interesa" de cada demo lleva al mismo formulario
(`/interes/demo/{cliente_id}`). Sin JavaScript, de móvil.

- **Sí**: nombre, cómo prefiere (teléfono, videollamada o correo), cuándo (los 3 siguientes días
  laborables, mañana o tarde, o "cuando sea"), teléfono, correo y "¿algo que quieras
  preguntar?". Al enviarlo: cualificado.
- **Ahora no**: por qué (ya tenemos algo, no es buen momento, no lo necesitamos, precio, otro).
  Al enviarlo: descartado, baja de correo y de llamadas. "No os volvemos a escribir".
- Abrir la página no cuenta ni escribe nada: los antivirus abren los enlaces. Solo cuenta enviar
  el formulario (POST). Token firmado (HMAC con `OUTREACH_TRACKING_SECRET`), límite por IP y campo
  trampa para bots.
- Los botones de la demo ("Activar gratis", "Tengo una duda", "WhatsApp") también cualifican, leídos
  de la base cada 10 minutos. Una señal de antes de que Pablo lo descartara no lo reabre; una nueva,
  sí.

## 6. La ficha que recibe Pablo

Asunto: `🔥 Lead cualificado: {negocio} — {cómo y cuándo}`. Contiene:

1. Qué ha pedido y cómo se cualificó (formulario, respuesta, botón de la demo, Sara).
2. Contacto: persona, teléfono (`tel:`), correo, web, ciudad, sector.
3. La llamada de Sara: cuándo, con quién habló, resumen y notas.
4. Qué hizo con la demo: veces que la abrió, si le escribió (con sus primeras preguntas), si la
   llamó por voz, botones que pulsó, última actividad. Se guarda mientras la demo existe (las
   demos caducan a los 7 días).
5. Siguiente paso: un **borrador de correo listo** (enlace `mailto:` con el texto ya escrito),
   el plan que le encaja y tres ideas para la conversación.

A las 24 h, si la oportunidad sigue sin tocar en el Plan de escala, **un** recordatorio.

## 7. Respuestas por correo

El lector IMAP ya detecta las respuestas (`info@vantelia.es`) y avisaba a Pablo. Ahora los
correos de Sara con la demo y los del seguimiento quedan en `sends` con su Message-ID, así que
también se detecta quien contesta a esos. Si el negocio está en seguimiento, la IA clasifica la
respuesta (`interesado`, `pregunta`, `no_interesado`, `fuera_de_oficina`, `otro`): interés o
pregunta = cualificado y ficha; el resto, el aviso de siempre con la ficha y la clasificación.
Sin clave de OpenAI, todo lo que no sea un "no" claro cuenta como pregunta (mejor un aviso de más).

## 8. El panel (Llamadas de Sara)

- Interruptor **Seguimiento tras la demo** (apagado de serie; las inscripciones se apuntan igual).
- **Leads cualificados**: quién, cómo y cuándo quiere, por dónde se cualificó, su ficha.
- **Embudo** de los últimos 30 días: llamadas con una persona → demos mandadas → la abrieron →
  la probaron → cualificados → clientes, con el porcentaje de cada paso y **leads por cada 100
  llamadas** (la métrica que pidió Pablo: conversiones por llamada).
- **En seguimiento**: toque en el que van, el siguiente, qué han hecho con la demo; parar,
  cualificar a mano o ver la ficha.

## 9. Lo que NO hace (y por qué)

- **No vuelve a llamar** tras la demo: Pablo prefiere correo (5-oct). Si algún día se quiere,
  hace falta pedir permiso en la primera llamada.
- **No reserva en una agenda**: el negocio `vantelia` tiene la agenda apagada y encenderla
  cambiaría el asistente de la web. Se recoge cuándo le viene bien y Pablo confirma.
- **No escribe a quien probó la demo hace más de 30 días**: ese "¿qué te pareció?" ya no cuadra.
  La bolsa antigua es la acción A2 del plan de captación (correos personales).
- **No toca Instagram ni WhatsApp de forma automática** (regla del 9-sep).

## 10. Operación

- Encender o apagar: panel *Llamadas → Seguimiento tras la demo*, o
  `PUT /admin/captacion/seguimiento/config {"activo": true}`.
- Ver los correos tal cual salen: `GET /admin/captacion/seguimiento/vista-previa`.
- Vuelta a mano: `POST /admin/captacion/seguimiento/ronda` (señales y recordatorios en el momento;
  los correos salen en segundo plano, con el espaciado de siempre).
- El hilo corre cada 10 minutos (`seguimiento_demo.arrancar`, registrado en `backend/main.py`).
