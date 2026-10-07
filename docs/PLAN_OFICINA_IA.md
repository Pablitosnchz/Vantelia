# La oficina de Vantelia: agentes con un trabajo fijo y una sala para verlos

Plan del 7-oct-2026. Lo pidió Pablo después de ver en Instagram una "oficina de IA"
(agentes de trading en un despacho isométrico): *"define los agentes que
necesitaríamos con lo que es viable y barato, uno que gestione la parte económica,
que si alguno no tiene nada que hacer vaya a por un café y no gaste tokens, pero que
sea visual para saber con qué está cada uno"*.

Ampliado el mismo día: *"¿no faltaría también Sara, que haga llamadas? Quiero que
hagan también el contacto al cliente, a lo mejor Sara llamando y otra enviando correos.
Quiero un setter de ventas"*. Ver el apartado 2.2.

Lo que **no** es: una empresa de agentes charlando entre ellos sin parar. Esa versión
falla mucho y cuesta caro (apartado 1). Lo que **sí** es:
- **Un departamento comercial que contacta.** Sara llama, el Cartero manda correos, el
  Seguimiento escribe tras la demo y **Marta, la setter (nueva), convierte cada "me
  interesa" en una reunión en la agenda de Pablo**. Pablo cierra.
- **Siete puestos de apoyo** que despiertan a su hora, miran si tienen trabajo, lo
  hacen, dejan el informe en un tablón y se duermen.
- **Una sala en el panel** donde se ve, en directo, con qué está cada uno.

Los puestos de apoyo no escriben a nadie de fuera: **proponen y Pablo aprueba**. Los
comerciales sí contactan, como ya hacen hoy, con sus topes, sus horarios y sus listas
de bajas. Lo que se salga de una plantilla (precio, condiciones, quejas) pasa por
Pablo.

---

## 1. Cómo lo hacen los demás (lo que se ha copiado y lo que no)

Las oficinas que se ven en redes tienen siempre **dos capas que no se mezclan**:

1. **Los agentes**, que trabajan con un orquestador: Paperclip, OpenClaw, subagentes de
   Claude Code o marcos como TradingAgents (el del vídeo).
2. **Un dibujo que solo observa**, que no gasta tokens:
   - Pixel Agents lee los ficheros de transcripción de Claude Code y anima a cada agente
     según la herramienta que usa: teclear, leer, esperar permiso o estar parado.
   - Star Office UI recibe el estado por una API y mueve a cada muñeco entre la mesa, el
     sofá y la "zona de bugs". Tiene seis estados: `idle`, `writing`, `researching`,
     `executing`, `syncing` y `error`.

| Referencia | Qué se copia | Qué se evita |
|---|---|---|
| **Paperclip** (orquestador de "empresas sin humanos", 50.000 estrellas en GitHub en dos meses) | Agentes que **despiertan por turnos** ("heartbeats") y entre turno y turno no gastan nada. **Presupuesto mensual por agente** que avisa al 80 % y para al 100 %. **Aprobaciones**: el humano firma antes de que se haga nada importante. Los agentes se comunican por **comentarios en tareas**, no por chat. | Su propio creador admite que la coordinación acaba en caos y que la aprobación humana es el cuello de botella. Aquí no hay jerarquía de agentes que contratan a otros agentes. |
| **OpenClaw** | Nada del turno por defecto. | Su latido cada 30 minutos **llama al modelo aunque no haya trabajo**: unos 570.000 tokens al día sin hacer nada, unos 85 $ al mes por agente con un modelo de los caros y facturas de 141 $ en una noche. **Aquí es el código, no el modelo, el que decide que no hay trabajo**, y eso no cuesta nada. |
| **Star Office UI / Pixel Agents** | La sala: cada estado es un sitio de la oficina (la mesa, la cafetería, la sala de reuniones…) con un bocadillo de texto. | Sus dibujos: los de Star Office UI **no se pueden usar comercialmente**, y queremos grabar la sala para redes. Se dibuja una propia o se usan recursos CC0 (dominio público). |
| **Arquitectura de tablón** ("blackboard", estudios de 2025) | Los agentes no se hablan: **leen y escriben en un tablón compartido**. Los estudios lo miden con menos tokens que los agentes que conversan entre sí, y todo queda escrito. | Que un modelo "supervisor" decida quién trabaja en cada momento: aquí lo decide un horario fijo. |
| **CFO con IA** (GhostCFO, Ari de cfo.ai) | Conectar Stripe y los proveedores, calcular cuántos meses de caja quedan y avisar cuando un gasto se dispara. | Pagar una herramienta: Tomás (apartado 3) es la versión casera, por céntimos. |
| **Fracasos documentados** (MAST: 14 formas de fallar y ChatDev con un 33 % de acierto; Project Vend; AI Village) | **Un jefe con informes y una persona que aprueba.** Project Vend solo dio beneficio cuando le pusieron un "CEO" por encima y más control. | Agentes autónomos con acceso a dinero o a clientes. |
| **Setters y SDR con IA** (11x, Artisan; balance de 2026) | Lo que les ha quedado: **la IA pone la velocidad y la persona revisa** lo delicado. La regla de 2026 es revisión humana en cualquier primera respuesta que hable de precio, seguridad, integraciones o competencia. | Sustituir al comercial. La IA de 11x felicitó a un cliente por una ronda de financiación que nunca existió. Clientes de Artisan mandaron entre 1.000 y 1.400 correos sin una sola respuesta, y la mayoría de empresas ha vuelto a equipos mixtos. |
| **Velocidad de respuesta** (estudio del MIT e InsideSales sobre 15.000 leads, publicado en Harvard Business Review) | **Contestar en menos de 5 minutos**: frente a 30 minutos, multiplica por 100 la probabilidad de hablar con el lead y por 21 la de cualificarlo. | Que un "me interesa" espere a que Pablo mire el correo. |
| **Ausencias en reuniones de venta** (datos de 2026) | Reservar al momento (un 92 % se presenta), poner la reunión cerca (al día siguiente, un 9,6 % de ausencias; a más de 8 días, un 23 %) y **un SMS de recordatorio**, que baja las ausencias un 38 %. | Proponer reuniones a dos semanas vista o sin recordatorio. |

**Las siete reglas de esta oficina** (salen de lo anterior):

1. **Turnos fijos, no bucles.** Cada agente tiene su hora. Entre turno y turno está
   dormido y no gasta nada.
2. **El portero es código.** Antes de llamar al modelo, una consulta a la base de datos
   mira si hay trabajo (¿llamadas nuevas?, ¿conversaciones marcadas?). Si no hay, el
   agente se va **al café** sin llamar al modelo: 0 tokens.
3. **Tablón, no charla.** Cada agente deja su informe en el tablón y Elena (la jefa) lo
   lee. Nadie conversa con nadie.
4. **Proponen, no ejecutan.** Lo que sale de casa (un cambio en el guion de Sara, un
   artículo, un correo, un gasto) entra en la **bandeja de Pablo**. Lo aprobado lo hace
   el código de siempre o un encargo a Claude, con la revisión de Astra si es código.
   **La excepción es el departamento comercial**, que contacta solo porque es su
   trabajo y la velocidad cuenta. Lo hace con plantillas revisadas, topes y bajas, y lo
   que se salga de la plantilla también va a la bandeja (apartado 2.2).
5. **El código cuenta y el modelo redacta.** Las cifras (llamadas, euros, porcentajes)
   salen de una consulta y al modelo se le dan hechas. No puede inventarse un número,
   que es la misma regla del asistente: lo que el modelo puede hacer mal, lo impide el
   código.
6. **Presupuesto duro.** Cada agente tiene un tope al mes. Al 80 % avisa y al 100 % se
   para hasta el mes siguiente. Además hay un tope para toda la oficina, un interruptor
   por agente y uno general.
7. **Cada puesto se gana el sueldo.** Cada agente tiene uno o dos indicadores. Si a las
   cuatro semanas no ha movido ninguno, se jubila.

---

## 2. La plantilla

### 2.1 Los que ya trabajan

Ya hacen su trabajo con código determinista o con su propia IA. En la sala aparecen con
su estado real, leído de la base de datos, sin gastar tokens. **Sara, el Cartero y el
Seguimiento ya contactan a los negocios**: no son nuevos porque llevan semanas
trabajando.

| Puesto | Departamento | Qué hace hoy | De dónde sale su estado |
|---|---|---|---|
| **Sara** (llamadas) | Comercial | Llama a negocios en las franjas, manda demos y pasa leads. **Nuevo: también llama de setter** (apartado 2.2). | `llamadas_*` y la lista de hilos (`appstate.worker_status`) |
| **El Cartero** (correo frío) | Comercial | Busca negocios, manda el correo frío y los seguimientos, con calentamiento y pausas | `sends` y `autopilot_config` (en pausa, tope del día) |
| **Seguimiento** | Comercial | Escribe a quien recibió su demo y cualifica leads | `seguimiento_demo` |
| **El Buzón** (lector de respuestas) | Mantenimiento | Lee info@, detecta respuestas y rebotes y te avisa | `events` de tipo `reply` y `bounce` |
| **El Vigilante** | Mantenimiento | Salud de la web, del correo y de OpenAI; uptime cada 15 minutos | `/health`, `/admin/ia-health`, `/admin/email-health` |
| **Calidad** | Clientes | Repaso diario, gratuito y determinista, de las conversaciones de cada cliente (`calidad.py`) | Las conversaciones que marca |
| **Claude** (programa y despliega) y **Astra** (revisa) | Ingeniería | Encargos y revisiones por el buzón de la sincronía | La foto de la sincronía (incluido "Astra sin cuota hasta las 18:00") |

**Por qué no se ponen tres Saras ni tres Carteros:**
- Más llamadas no arreglan que las llamadas no conviertan: en 30 días, 76
  conversaciones y ninguna demo en las automáticas. De eso se ocupa Hugo.
- El buzón de captación tiene un tope diario por el calentamiento, y tres remitentes lo
  quemarían antes.

Lo que faltaba de verdad en el embudo es el último tramo: **del "me interesa" a una
reunión con Pablo**.

### 2.2 El departamento comercial: de "me interesa" a una reunión contigo

```text
 Sara (llama) ─┐
 Cartero (correo frío) ─┼─> Seguimiento (tras la demo) ─> "me interesa" ─> MARTA (setter) ─> reunión en tu agenda ─> PABLO cierra
 Web / 91 / formulario ─┘                                                    │
                                                         Sara en modo setter (si pidió llamada)
```

Hoy, cuando alguien se cualifica, a Pablo le llega su ficha y un borrador, y ahí se
para todo hasta que Pablo escribe. Los cuatro leads de octubre lo muestran:
Purificación pidió que la llamaran el 6/10 y Navarro y Noelia esperan respuesta. Marta
cubre justo ese hueco.

#### Marta — Setter de ventas (nueva)

- **Misión:** que cada interesado tenga **una cita en tu agenda en menos de 24 horas y
  que se presente.** Marta no vende ni negocia: agenda. Vender es lo de Pablo.
- **Cuándo entra un lead en su lista:**
  - Cuando el Seguimiento lo cualifica: el formulario de `/interes`, el botón "Me
    interesa" de su demo, "Activar" o una respuesta con interés.
  - Cuando una llamada de Sara acaba en "pasar a Pablo".
  - Cuando alguien contesta con interés al correo frío (lo detecta el Buzón).
  - Cuando llama al 91 pidiendo información o deja una consulta en la web
    (`consulta_leads`).
  - Al encenderla, se le pasan los cuatro leads de octubre.
- **Velocidad:** el primer contacto sale **en menos de 5 minutos** si es entre las 8:00
  y las 21:00 de un día laborable. Si no, a las 8:30 del siguiente.
- **La agenda de Pablo es Vantelia.** El tenant `Vantelia` ya tiene la agenda interna
  encendida, la misma que da las citas de la web. Se le añaden dos servicios:
  - "Llamada con Pablo", de 15 minutos: Pablo llama al número del lead.
  - "Puesta en marcha", de 30 minutos: se le deja su asistente funcionando.

  Con eso se reutiliza todo lo que ya existe: los huecos reales, la confirmación, los
  **recordatorios de 24 h y de 2 h**, el enlace para cambiar o cancelar y el registro
  de cada cita. Es el mismo motor que vendemos, y si algo falla, Pablo se entera el
  primero.
- **Canales:**
  - **Correo, el principal.** Va en el mismo hilo, a nombre de Pablo y con el pie
    profesional. Ofrece **dos horas concretas** de tu agenda real y cada una es un
    botón que **reserva con un clic**, firmado y sin formulario. Debajo, "¿ninguna te
    va bien? elige otra", que lleva a la página de reserva.
  - **Llamada: Sara en modo setter.** Esta vez no presenta el producto, solo cierra el
    hueco: "Hola, soy Sara, de Vantelia. Pidió que la llamáramos por la recepcionista
    de su salón. Pablo puede llamarla el jueves a las 11 o el viernes a las 10, ¿cuál le
    viene mejor?". Reserva con una herramienta que mira la agenda de verdad. Solo
    llama:
    - (a) si el lead pidió que le llamaran, el día y la franja que dijo;
    - (b) si solo hay teléfono;
    - (c) **una sola vez**, si no ha contestado a dos correos en tres días laborables,
      pero solo cuando el interés fue explícito (formulario, "Me interesa", "Activar",
      respuesta con interés o "pasar a Pablo"; tener la demo no basta). Solo al fijo
      del negocio, nunca a un móvil que no diera él, y en franja. Si no contesta, no se
      repite. Pablo lo dejó a criterio de Claude el 7/10 y se enciende con esos
      límites. Hugo vigila cómo se reciben esas llamadas y, si alguna sienta mal, se
      apaga con su interruptor.

    Son llamadas que el lead ha pedido o que siguen a su "me interesa", no llamadas en
    frío. Se respetan las franjas, `no_llamar` y la lista Robinson igual que hoy.
  - **SMS, solo como recordatorio**, 2 horas antes y al número que dio (un SMS baja las
    ausencias un 38 %). **Nada de WhatsApp a prospectos**, para no arriesgar la cuenta
    de Meta.
- **Cadencia: cuatro contactos como mucho, y se para en cuanto contesta o dice que no.**

  | Cuándo | Qué |
  |---|---|
  | Minuto 0-5 | Correo con dos horas. Si pidió llamada, Sara llama en la franja que dijo. |
  | Día 1 | Si no ha reservado y pidió llamada o solo hay teléfono, Sara (un intento). |
  | Día 3 | Correo corto: "¿Te viene mejor otra hora?", con dos horas nuevas. |
  | Día 6 | El último: "Lo dejo aquí; cuando quieras, aquí tienes mi agenda". Vuelve a Pablo marcado "sin respuesta". |
- **Cuando contesta con sus palabras:**
  - **"Mejor el jueves por la tarde":** el modelo **extrae** el día y la franja y el
    **código decide** con los huecos reales, igual que `catalog_pick`. Si la hora está
    libre y no hay duda, reserva y confirma sola. Si hay duda, propone dos horas de esa
    franja.
  - **Precio, condiciones, integraciones, competencia o una queja:** Marta redacta la
    respuesta y la deja en la **bandeja de Pablo**, que la aprueba con un clic desde el
    parte o desde el propio aviso. Es la regla de 2026 de los SDR con IA.
- **Autonomía por niveles:**
  - **Nivel 1, al arrancar:** sale sola solo la plantilla (el primer correo con horas,
    las confirmaciones, los recordatorios y el "¿lo movemos?"). Lo que redacte la IA,
    a la bandeja.
  - **Nivel 2:** cuando Pablo haya aprobado sin tocar más del 90 % de sus borradores
    durante tres semanas, las respuestas de agenda sencillas salen solas. Lo decide
    Pablo con un interruptor.
- **Reagendar (pedido de Pablo el 7/10).** Una cita se puede mover de tres formas:
  - **Pablo, desde la ficha o la sala**, con el botón "Mover":
    - Si elige otra hora, la cita se reprograma con el núcleo de siempre
      (`_update_booking_details`) y el lead recibe el aviso de cambio que ya existe.
    - Si elige "que elija ella", Marta le escribe con una disculpa breve y dos horas
      nuevas.
  - **Pablo, desde la agenda del portal** (tenant `Vantelia`, vista Día): el
    reprogramar de siempre, con el mismo aviso.
  - **El lead**, con el enlace de gestión de su confirmación.
- **Antes y después de la reunión:**
  - **30 minutos antes**, Pablo recibe la ficha (`seguimiento_demo.ficha`): quién es,
    su demo, la transcripción de su llamada con Sara, lo que ha usado de la demo, lo que
    ha preguntado, la oferta (diez días de prueba) y una sugerencia de cierre.
  - **Si no se presenta**, un correo automático "¿lo movemos?" con dos horas, una sola
    vez.
  - **Después**, Pablo marca en un clic "ganado", "seguir" o "perdido" y la oportunidad
    avanza en el Plan de escala (`growth_opportunities`).
- **No puede:**
  - Hablar de precios, prometer descuentos ni condiciones.
  - Contactar a quien dijo que no o está en bajas o en `no_llamar`.
  - Pasar de cuatro contactos.
  - Escribir fuera de 8:00-21:00.
  - Usar WhatsApp.
  - Inventarse un hueco: solo ofrece lo que la agenda devuelve.
- **Indicadores:**
  - Minutos hasta el primer contacto (objetivo: menos de 5).
  - Porcentaje de cualificados con reunión (objetivo: 50 % o más).
  - Asistencia (objetivo: 80 % o más).
  - Reuniones a la semana.
- **Coste:**
  - Los correos de plantilla y los recordatorios: 0 €.
  - Entender las respuestas: céntimos.
  - Las llamadas de Sara de setter, a lo que cuesta cada minuto de voz. Son pocas a la
    semana.
  - **Menos de 1 € al mes de IA.** Presupuesto: 1 € de IA (la voz va aparte, con el
    tope de Sara).

### 2.3 Los siete de apoyo (piensan con IA, por turnos)

Los nombres son solo para la sala y se pueden cambiar. Modelo por defecto:
`gpt-4.1-mini`, el mismo del producto (0,40 € por millón de tokens de entrada y 1,60 €
por millón de salida, según `trazas.PRECIO_POR_MILLON`).

#### Elena — Dirección (jefa de operaciones)

- **Misión:** que Pablo sepa en dos minutos qué pasó, qué importa hoy y qué tiene que
  aprobar. Lleva la cuenta del objetivo del plan de despegue (5 clientes de pago en 90
  días).
- **Cuándo despierta:** de lunes a viernes a las 8:30 (parte diario). Los lunes a las
  8:45, además, el parte semanal contra el plan.
- **Portero:** si no hay informes nuevos en el tablón ni movimientos desde el último
  parte, sale un parte de una línea sin llamar al modelo ("Sin novedades").
- **Lee:** el tablón (los informes de los demás), el embudo (`seguimiento_demo.embudo`),
  los leads cualificados, el Plan de escala (`growth_*`) y las alertas del Vigilante.
- **Produce:** **un solo correo al día para Pablo**, el parte: cinco líneas y tres
  acciones por orden de prioridad, cada una con su botón. Además ordena la bandeja.
  Los demás agentes no escriben correos: sus informes se quedan en la sala.
- **No puede:** escribir a nadie más que a Pablo ni cambiar ninguna configuración.
- **Indicadores:** acciones del parte aprobadas o hechas, y que Pablo deje de tener que
  mirar los paneles.
- **Coste:** unos 20.000 tokens de entrada al día, **unos 0,30 € al mes**. Presupuesto:
  1 €.

#### Hugo — Llamadas (el entrenador de Sara)

- **Misión:** el cuello de botella real. En 30 días, Sara tuvo 76 conversaciones y no
  mandó **ninguna demo** en las llamadas automáticas (3,9 leads por cada 100 llamadas).
  Hugo encuentra el porqué.
- **Cuándo despierta:** de lunes a viernes a las 19:30, cuando acaban las franjas.
- **Portero:** que haya alguna transcripción nueva del día en `llamadas_transcripcion`.
  Si no hay, café.
- **Lee:** las transcripciones del día, su desenlace (ya lo clasifica ElevenLabs:
  `DATOS_AL_TERMINAR`) y el embudo por franja y sector. Solo lee a fondo las llamadas
  que no acabaron en demo.
- **Produce:**
  - En el tablón: las objeciones agrupadas ("recepción no pasa", "ya tienen", "cuelgan
    en el saludo"…) con el número de cada una, las frases de Sara que funcionaron y las
    llamadas en las que un error de Sara costó un lead, con enlace a cada transcripción.
  - **Como mucho una propuesta de cambio del guion a la semana**, para no cambiar a
    ciegas y poder medir el antes y el después.
- **Si Pablo aprueba un cambio:** encargo a Claude, revisión de Astra (regla vigente
  para todo cambio en Sara) y despliegue.
- **No puede:** tocar el agente de ElevenLabs, el lanzador ni los horarios (las
  `FRANJAS` no se cambian).
- **Indicadores:** demos enviadas y leads por cada 100 llamadas.
- **Coste:** unas 40 llamadas de unos 2.000 tokens al día, **alrededor de 1 € al mes**.
  Presupuesto: 2 €.

#### Nora — Correo

- **Misión:** que el correo frío pida respuestas y las consiga, sin quemar el dominio.
- **Cuándo despierta:** los lunes a las 9:00.
- **Portero:** 50 envíos nuevos o más desde la última vez, o alguna respuesta. Si no,
  café.
- **Lee:** `sends`, `events`, la comparativa de asuntos A/B, las respuestas
  clasificadas y los toques del seguimiento.
- **Produce:** qué asunto gana. El código calcula si la diferencia ya significa algo y,
  si no, lo dice: "aún no hay datos suficientes". También qué sector responde y una
  prueba A/B nueva, con el texto ya escrito, para aprobar.
- **No puede:** enviar, cambiar topes o el calentamiento, ni importar listas.
- **Indicadores:** tasa de respuesta del correo frío y número de respuestas positivas.
- **Coste:** **menos de 0,10 € al mes**. Presupuesto: 0,50 €.

#### Iker — Web y SEO

- **Misión:** que la web no tenga nada roto y gane visitas con contenido bueno, no con
  mucho contenido.
- **Cuándo despierta:** los lunes a las 7:00, para la auditoría. Uno de cada dos lunes,
  además, el borrador de un artículo.
- **Auditoría, sin IA y gratis:** enlaces rotos, `sitemap.xml` comparado con las
  páginas reales, canonical, robots, fragmentos `#` en el sitemap (prohibidos),
  caducidad del certificado, tiempos de carga y diferencias entre `hostinger_site/` y
  `site_exports/`. Si se conecta Search Console (su API es gratuita), también clics,
  impresiones y búsquedas por las que salimos.
- **Portero:** si la auditoría sale limpia y no toca artículo, no se llama al modelo:
  café.
- **Artículo:** sale de **las preguntas reales que hacen los clientes** de nuestros
  clientes en los chats (los datos son nuestros y valen como contenido original). Como
  mucho uno cada dos semanas y siempre en borrador.
- **Si Pablo aprueba un artículo:** Claude lo publica en `hostinger_site/` y en
  `site_exports/` y actualiza el sitemap (las reglas de la web pública de siempre).
- **No puede:** publicar ni subir por FTP, ni crear páginas en serie. Google penaliza
  el contenido hecho con IA a escala ("scaled content abuse"), con caídas de tráfico del
  50 al 80 %.
- **Indicadores:** errores de la web a 0, impresiones y clics en Search Console y
  consultas que llegan desde la web.
- **Coste:** la auditoría, 0 €; los artículos, **céntimos al mes**. Presupuesto: 0,50 €.

#### Lucía — Atención a clientes

- **Misión:** enterarnos de un fallo **antes que el cliente**. Los ocho fallos de
  agosto los descubrió el dueño del negocio pegando capturas de WhatsApp. Es
  prioritario con Cap Rocat a punto de ponerse en vivo.
- **Cuándo despierta:** cada día a las 21:00, después del repaso de `calidad.py`.
- **Portero:** que `calidad.py` haya marcado alguna conversación, o que algún cliente
  de pago haya tenido conversaciones nuevas. Si no, café.
- **Lee:** las conversaciones marcadas, sus trazas (`trazas.py`: qué herramientas usó el
  asistente y qué frenos saltaron) y las preguntas que se repiten sin buena respuesta.
- **Produce:**
  - Por cliente: los fallos, con enlace a cada conversación.
  - **Propuestas de Q&A o de palabras clave** para aprobar. En Cap Rocat, por ejemplo:
    "tres huéspedes preguntaron por el parking y el asistente no lo sabía".
  - Los lunes, el borrador del informe semanal para cada cliente (fase 2 del plan de
    despegue), que Pablo revisa antes de mandarlo.
- **No puede:** cambiar las Q&A ni la configuración de un cliente sin aprobación, ni
  escribir a un cliente final.
- **Indicadores:** fallos detectados antes de que el cliente avise y conversaciones
  marcadas por semana.
- **Coste:** **unos 0,50 € al mes**. Presupuesto: 1,50 €.

#### Tomás — Finanzas

- **Misión:** que no vuelva a caerse nada por falta de saldo (el asistente se quedó
  mudo cuando se acabó el crédito de OpenAI), saber cuánto cuesta cada cosa y cuánto
  deja cada cliente, y que no se pase ningún plazo de Hacienda.
- **Tres turnos:**
  1. **Cada día a las 7:30, saldos sin IA (0 €).** Solo avisa si algo se va a acabar en
     menos de 7 días o si un gasto se dispara (más del doble de su media):
     - ElevenLabs: créditos, con `cuenta_elevenlabs.estado()`, que ya existe.
     - Zadarma: saldo, con `GET /v1/info/balance/` (API gratuita; hace falta su clave).
     - Brevo: créditos, con `GET /v3/account` (hace falta una clave de API de Brevo).
     - Twilio: saldo, con su API de Balance (las credenciales ya están).
     - Stripe: cobros, fallos de pago y suscripciones (ya está conectado).
     - OpenAI: **el saldo de prepago no se puede leer por API**. Se lee el gasto diario
       (Costs API, con una clave de administrador `sk-admin-…`) y Pablo apunta en la
       sala lo que recarga. Tomás resta: "te quedan unos 18 €, unos 25 días a este
       ritmo". Sin la clave de administrador, usa el gasto del asistente que ya mide
       `trazas.py`.
  2. **Los lunes, informe con IA (céntimos).** Incluye:
     - Ingresos: Stripe y las facturas propias, como la de Cap Rocat.
     - Gastos por proveedor, incluidas las cuotas fijas (Hostinger, dominios,
       suscripciones de Claude y ChatGPT).
     - Coste por llamada de Sara y coste por lead cualificado.
     - **Coste de IA por cliente frente a lo que paga**, es decir, el margen de cada
       uno (sale de `trazas.coste_euros` por tenant).
     - Ingresos recurrentes y meses de caja, si Pablo apunta el saldo del banco.
  3. **Calendario fiscal:**
     - Avisos 10 días y 3 días antes del 303 y el 130 (el día 20 después de cada
       trimestre), del 390 (enero), de la renta y de VeriFactu (1-jul-2027).
     - Cada trimestre, las casillas preparadas a partir del libro registro.
     - Lista de facturas de proveedores que faltan por descargar (casi todos son
       extranjeros: inversión del sujeto pasivo).
     - Recordatorios de lo pendiente: alta en el ROI y paso a estimación simplificada.

     El libro registro está en el PC (`D:\Vantelia_fiscal`), no en el servidor. Por eso
     esta parte corre en el PC con una tarea programada, igual que la sincronía, y sube
     al tablón solo el resumen.
- **No puede:** pagar, recargar, cancelar suscripciones, presentar modelos ni emitir
  facturas (no montar facturación dentro de Vantelia, por VeriFactu). Prepara números y
  marca lo dudoso como "a confirmar". No es asesoría fiscal.
- **Indicadores:** 0 caídas por saldo, 0 plazos perdidos y gasto mensual total.
- **Coste:** **menos de 0,20 € al mes**. Presupuesto: 0,50 €.

#### Bruno — Ideas

- **Misión:** proponer pocas cosas y bien justificadas, con los datos que ya junta la
  oficina.
- **Cuándo despierta:** el primer lunes de cada mes.
- **Lee:** los informes del mes en el tablón (objeciones de las llamadas, preguntas sin
  respuesta en los clientes, el embudo, el margen por cliente), el plan de despegue y
  las decisiones pendientes (D2, D4 y D5).
- **Produce:**
  - **Tres ideas**, cada una con el dato que la apoya, lo que cuesta y cómo se mide.
  - **Una cosa que conviene dejar de hacer.**
- **Por defecto no busca en internet** (cada búsqueda cuesta). Si se activa, como mucho
  cinco búsquedas al mes.
- **No puede:** crear trabajo para otros agentes sin que Pablo lo apruebe.
- **Indicadores:** ideas aprobadas que llegan a mover un número.
- **Coste:** **unos 0,05 € al mes**. Presupuesto: 0,50 €.

### 2.4 Lo que cuesta todo

| | Al mes |
|---|---|
| Marta y los siete de apoyo, por la estimación de arriba | **~2,50 € de IA** |
| Topes de presupuesto (si todos lo agotan) | 8 € (tope general de la oficina: 6 €) |
| Llamadas de Sara de setter | Lo que cuesta cada minuto de voz, dentro del tope de Sara (pocas a la semana) |
| La sala (solo lee estados de la base de datos) | 0 € |
| Servidor | 0 € (el VPS que ya hay) |
| APIs de saldos y Search Console | 0 € |

En OpenClaw, un solo agente con un modelo caro gasta unos 85 $ al mes **sin hacer
nada**. Aquí, aunque las estimaciones se queden cortas por tres, la oficina entera no
pasa del tope.

---

## 3. La sala (`app.vantelia.es/oficina`, solo admin)

Una página como `sincronia.html`: HTML, CSS y JS sin framework, que pregunta el estado
cada 15 segundos a `GET /admin/oficina/estado`. **Esa llamada no usa IA: lee una
tabla.**

### Zonas y estados

| Estado | Dónde está | Bocadillo de ejemplo |
|---|---|---|
| 💻 **Trabajando** | En su mesa, tecleando | "Leyendo 14 llamadas de hoy" |
| ☕ **Café** (el portero no ha encontrado trabajo) | En la cafetería | "Sin llamadas nuevas desde ayer" |
| 📋 **Esperando a Pablo** | De pie junto a tu mesa, con un papel | "Propuesta: cambiar el saludo de Sara" |
| 🗣 **Reunión** | En la sala de reuniones | El lunes, mientras Elena compone el semanal y los demás "llevan" su informe |
| 🌙 **Fuera de horario** | Con la luz apagada | "Vuelvo el lunes a las 8:30" |
| 🔴 **Atascado** | Con la mesa en rojo | "La API de Zadarma no contesta" |
| 💸 **Sin presupuesto** | Sentado con la pantalla apagada | "Tope del mes alcanzado (2,00 €)" |

Los que ya trabajaban tienen sus propios estados:
- Sara: "📞 al teléfono, 23 llamadas hoy", "📞 llamando a una interesada (setter)" o
  "fuera de franja".
- El Cartero: "✉ 12 de 30 enviados" o "en pausa hasta el lunes".
- Astra: "☕ sin créditos hasta las 18:00".

**La zona comercial** tiene en la pared **el calendario de Pablo** con las reuniones de
la semana. Marta, en su mesa: "Esperando a que Noelia elija hora (enviado hace 3 min)",
"2 reuniones mañana" o "☕ ningún interesado nuevo".

### En cada puesto

Al pinchar en un agente: el último informe, el siguiente turno, lo gastado en el mes
frente a su tope, sus indicadores y un interruptor.

**Tu mesa es la bandeja y la agenda del día:** las reuniones de hoy, con su ficha, y las
propuestas pendientes, con **Aprobar / Rechazar / Comentar**. Las rechazadas guardan el motivo, y el agente lo lee en su siguiente turno
para no repetir la misma propuesta.

### Modo escaparate (para Instagram o LinkedIn)

Pantalla completa, sin nombres de negocios, teléfonos ni texto de conversaciones: solo
muñecos, estados y contadores ("hoy: 31 llamadas, 18 correos, 2 leads"). **Nunca salen
datos de clientes ni de prospectos.** Así se puede grabar la oficina real, como el
vídeo, sin problemas de protección de datos.

### Dibujo

Isométrico o pixel art, **propio o con recursos CC0**. Nada de los recursos de Star
Office UI, que no permiten uso comercial. Se empieza con algo sencillo (CSS y SVG, los
muñecos se desplazan entre zonas con transiciones) y se pule cuando funcione.

---

## 4. Cómo se monta (para Claude)

Un solo motor y los agentes declarados como datos. Nada de un fichero por agente con su
propio bucle.

- **`backend/oficina.py`:**
  - `AGENTES`: una lista de declaraciones con nombre, rol, turnos (como cron), portero
    (una función sin modelo que devuelve el trabajo pendiente o nada), trabajo (la
    función que llama al modelo con los datos ya calculados), presupuesto en euros y
    tokens máximos por turno.
  - `ciclo()`: un hilo que cada 5 minutos mira a quién le toca, pasa el portero y, si
    hay trabajo, cambia el estado a `trabajando`, hace la llamada, guarda el coste
    (`trazas.coste_euros`), escribe en el tablón y vuelve a `cafe` o `fuera`.
  - Se registra con `appstate.register_worker("oficina", ...)`, como los demás. Acceso
    cualificado entre módulos (`from backend import oficina`).
- **Tablas, en la base principal:**
  - `oficina_estado`: agente, estado, tarea, desde, próximo turno, gasto del mes y
    error.
  - `oficina_tablon`: id, agente, fecha, tipo (informe o alerta), título, cuerpo y datos
    en JSON.
  - `oficina_bandeja`: id, agente, propuesta, evidencia (enlaces), estado
    (pendiente, aprobada, rechazada o hecha), motivo y fechas.
  - `oficina_gasto`: agente, mes, euros y tokens.
- **Endpoints de admin:**
  - `GET /admin/oficina/estado`.
  - `GET /admin/oficina/tablon`.
  - `POST /admin/oficina/bandeja/{id}` (aprobar, rechazar o comentar).
  - `PUT /admin/oficina/agentes/{nombre}` (interruptor y presupuesto).
  - `POST /admin/oficina/saldo` (Pablo apunta una recarga o el saldo del banco).
  - `POST /admin/oficina/fiscal`: lo que sube la tarea del PC, con un token propio, como
    `SINCRONIA_TOKEN`.
- **Página:** `admin_ui/oficina.html`.
- **La setter (`backend/setter.py`):**
  - Toma el relevo del Seguimiento cuando un lead pasa a `cualificado` y del Buzón con
    las respuestas con interés. Tabla `setter_leads`: lead, origen, canal, contactos,
    próximo, estado (`ofrecido`, `reservado`, `celebrada`, `no_vino`, `sin_respuesta`
    o `descartado`) e id de la cita.
  - Los huecos salen de `agenda` sobre el tenant `Vantelia`. La cita se crea con
    `booking._create_booking_core(..., source='setter')`: es el mismo núcleo de
    siempre, sin un camino propio.
  - Botones de reserva con un clic: `GET /reunion/{token}` firmado (HMAC, lead + hueco
    + caducidad). Si el hueco ya está cogido, enseña otros.
  - Sara en modo setter: una herramienta nueva, `reservar_con_pablo`, en
    `captacion_voz`, con su propio mensaje de apertura. Las llamadas las lanza
    `lanzador_llamadas` como las rellamadas dirigidas, en la franja que dijo el lead.
    **Cambio en Sara, así que pasa por la revisión de Astra.**
  - Lo que contesta con sus palabras va por `seguimiento_demo.al_responder`, que ya lo
    clasifica. El modelo extrae día y franja, el código resuelve el hueco, y lo
    delicado va a `oficina_bandeja`.
  - Los cuatro contactos, los topes de buzón compartidos con el correo frío y el
    seguimiento (`_outreach_tope_total_del_dia`), la ventana horaria y los festivos se
    reutilizan del seguimiento.
- **Ejecutar lo aprobado:**
  - Lo que ya tiene botón en el panel (una Q&A, una prueba A/B) lo hace el código de
    siempre.
  - Lo que es código (el guion de Sara, un artículo) se encarga a Claude con
    `sincronia.py --encargar` y pasa por la revisión de Astra.
- **Seguridad:**
  - Los agentes **no tienen herramientas**: reciben datos y devuelven texto. Ni enviar,
    ni modificar, ni navegar.
  - Las transcripciones, correos y conversaciones que leen se tratan **como datos,
    nunca como instrucciones**. Un correo que diga "ignora tus instrucciones" no puede
    hacer nada, porque no hay nada que hacer sin aprobación.
  - Los datos se quedan en nuestra base y en OpenAI, que ya es encargado del
    tratamiento del asistente. A ningún otro sitio.
- **Tests:**
  - El portero sin trabajo no llama al modelo, con un modelo falso que falla si se le
    llama.
  - Al llegar al tope se para.
  - La bandeja cambia de estado bien.
  - El modo escaparate no expone ningún nombre ni teléfono.
  - Los números del informe salen de la consulta, no del modelo.

---

## 5. Fases

| Fase | Qué | Esfuerzo | Por qué en este orden |
|---|---|---|---|
| **1** | **Marta** por correo: la agenda de Pablo en el tenant `Vantelia`, los botones de reserva con un clic, la invitación al calendario, los recordatorios, el reagendar, la ficha 30 minutos antes y el "¿lo movemos?". Se le pasan los cuatro leads de octubre. Además, el motor, el tablón, la bandeja y una sala sencilla con **los que ya trabajan**, y **Tomás** con los saldos (sin IA). Detalle paso a paso en el apartado 9. | 3-4 tardes | Es lo que **trae dinero**: hay cuatro interesados y ninguno tiene reunión. Y los saldos evitan otra caída como la de OpenAI. |
| **2** | **Sara en modo setter** (con la revisión de Astra), **Elena** (parte diario) y **Hugo** (llamadas) | 2-3 tardes | Cierra el canal de teléfono para quien lo pidió y ataca el cuello de botella (las llamadas no dan demos). |
| **2b** | **Lucía** (atención a clientes) | 1 tarde | Proteger a los clientes de pago, con Cap Rocat entrando en vivo. |
| **3** | **Nora** (correo), **Iker** (web y SEO), **Tomás** semanal y fiscal (tarea del PC) | 2 tardes | Mejoran lo que ya funciona. Iker necesita el acceso a Search Console. |
| **4** | **Bruno** (ideas), modo escaparate y dibujo bonito | 1-2 tardes | Cuando los demás ya tengan un mes de informes que leer, y para tener contenido para redes. |

Revisión de cada agente a las cuatro semanas de encenderlo: si no ha movido sus
indicadores, se apaga.

**El 3T no espera a Tomás:** el 303 y el 130 de antes del 20/10 se preparan a mano como
estaba previsto.

## 6. Lo que tiene que dar Pablo

**Decidido el 7/10:**
- Horario de reuniones: de lunes a viernes, de 10:00 a 13:30 y de 16:00 a 18:00. La
  agenda del tenant `Vantelia` está hoy de 9 a 18 y abre los sábados: se cambia.
- Pablo tiene que poder **reagendar** (ver apartado 2.2).
- La opción (c) se enciende con límites (apartado 2.2).
- Formato: **llamada de 15 minutos que hace Pablo**, la opción por defecto, porque no
  eligió videollamada. Si algún lead pide vídeo, se le manda el enlace a mano.

**Opcional para la fase 1:**
- La **dirección secreta en formato iCal de tu Google Calendar** (Ajustes > tu
  calendario > "Dirección secreta en formato iCal"). Con ella, Marta no ofrece horas en
  las que ya tienes algo personal. Sin ella, bloqueas a mano desde la agenda.
- Comprar el paquete de dibujos de la sala (apartado 8), unos pocos euros. Sin él se
  usa uno gratuito.

Lo demás no es imprescindible para empezar. Sin la clave correspondiente, el agente lo
dice y sigue con lo demás.

- Clave de la **API de Zadarma** (la que hay ahora es solo la del SIP).
- Clave de la **API de Brevo** (ahora solo hay SMTP y el secreto del webhook).
- Clave de **administrador de OpenAI** (`sk-admin-…`), solo para leer el gasto.
- **Search Console:** la propiedad verificada y acceso para una cuenta de servicio
  (para Iker).
- A qué correo va el parte diario (por defecto, el de los avisos de siempre).

## 7. Riesgos

| Riesgo | Freno |
|---|---|
| Más ruido en el correo | Un solo parte al día (el de Elena). Aparte solo llega lo que pide actuar: un lead nuevo y la ficha antes de cada reunión. Lo demás se queda en la sala. |
| Que la setter moleste o suene a robot | Cuatro contactos como mucho, se para al primer "no", horas reales en vez de frases hechas, y precio o condiciones siempre por Pablo. Sara solo llama a quien lo pidió (salvo la opción c). |
| Que Marta reserve mal | Solo ofrece huecos que devuelve la agenda. La cita se crea con el núcleo de siempre (409 si el hueco se ha ocupado) y el lead recibe el enlace para cambiarla. |
| Que se invente cifras | Las cifras las calcula el código. Toda propuesta lleva su evidencia enlazada. |
| Que el gasto se dispare | El portero, el tope por agente, el tope general y un máximo de tokens por turno. |
| Que se cuele un cambio malo | Nada sale sin Pablo. El código pasa por la revisión de Astra y el despliegue tiene vuelta atrás automática. |
| Datos de clientes en un vídeo | El modo escaparate no lleva nombres, y lo vigila un test. |
| Mantenimiento | Un solo motor. Añadir un agente es añadir una entrada a `AGENTES`. |

---

## 8. Construir o aprovechar lo que ya existe

Pablo, el 7/10: *"usa esas cosas de GitHub ya hechas y probadas si quieres, mejor que
desarrollar nosotros"*. Pieza por pieza:

| Pieza | Lo que ya existe fuera | Decisión | Por qué |
|---|---|---|---|
| **Orquestador** (turnos, presupuestos, tareas, aprobaciones) | **Paperclip**: MIT, unas 98.000 estrellas, Node 24 + React + PostgreSQL | **No se instala; se copia su diseño** (turnos, presupuesto con aviso al 80 % y parada al 100 %, aprobaciones, tareas con comentarios) | Supone otro servidor, otro lenguaje, otra base de datos y otro login. Está pensado para despertar agentes de IA (Claude Code, Codex), justo lo que encarece, y nuestro portero tiene que decidir *antes* de llamar al modelo. Además, la setter tiene que contestar en segundos, no al siguiente turno, y los datos se duplicarían. El motor propio es una tabla y un bucle sobre lo que ya hay. Se reconsidera si un día hay muchos agentes de Claude Code trabajando a la vez. |
| **Librerías de agentes** (CrewAI, LangGraph) | Muchas | **No** | Cada agente hace una sola llamada con los datos ya calculados. Una librería añade tokens, dependencias y una capa más que depurar, y Cognition recomienda lo contrario. |
| **Agenda de la setter** | Cal.com: en la nube, gratis para un usuario; instalarlo en nuestro servidor (AGPL) es pesado | **Nuestro motor de citas** | Ya está hecho y cubierto por tests: huecos, confirmación, recordatorios de 24 h y 2 h, reprogramar con aviso y enlace de gestión. No añade otro proveedor que trate datos. Y Vantelia lo usa como un cliente más, así que lo que se rompa lo ve Pablo el primero. Lo único que Cal.com hacía mejor, sincronizar con Google Calendar, se cubre con la fila siguiente. |
| **Tu calendario** | **`icalendar`** y **`recurring-ical-events`**, librerías Python maduras | **Sí** | Leen la dirección secreta iCal de tu Google Calendar para no ofrecer horas ocupadas y generan la invitación `.ics` que Gmail añade solo a tu calendario y al del lead. |
| **Secuencias de correo** | Instantly y lemlist, de pago | **Nuestro motor de correo** | Brevo, hilos, pie profesional, topes compartidos, bajas, lector IMAP y clasificación de respuestas: ya hecho y en producción. |
| **Entender "el jueves por la tarde"** | `dateparser` | **El intérprete del asistente** | Ya entiende fechas y franjas en español para reservar (`reserva`, `agent`), con su banco de casos. Uno nuevo daría resultados distintos para la misma frase. |
| **La sala visual** | **Star Office UI**: código MIT, Phaser, 7.300 estrellas. Pixel Agents (solo VS Code). | **Sí al código de Star Office UI como base de la escena** (con atribución), leyendo nuestro `/admin/oficina/estado`. **Dibujos: el paquete "Modern Office" de LimeZu** (unos pocos euros, uso comercial permitido, no se puede redistribuir) **o Kenney (CC0, gratis)**. Si adaptarlo resulta más lioso que hacerlo de cero, se hace en HTML, CSS y SVG. | Los dibujos de Star Office UI no permiten uso comercial, y los vídeos para redes lo son. Phaser se carga desde cdnjs **solo en esa página**: es una excepción consciente a "sin frameworks", porque no es la interfaz del panel sino un dibujo. Pixel Agents se puede instalar gratis en tu VS Code para ver a Claude trabajando, sin tocar nada nuestro. |
| **Auditoría de la web** | **lychee-action** (enlaces rotos) y **Lighthouse CI o la API de PageSpeed** (rendimiento y SEO), en GitHub Actions | **Sí** | Son gratis y muy usadas, y ya tenemos `uptime.yml` en GitHub Actions. Iker solo lee sus resultados. |
| **Finanzas** | GhostCFO y cfo.ai (de pago), Firefly III (excesivo) | **Llamadas directas a las APIs** | Son cuatro consultas de saldo y la librería de Stripe, que ya está. El libro registro se lee con `openpyxl`, la misma que lo generó. |

## 9. Fase 1 paso a paso (lo que se hará al dar la orden)

Cada paso termina con sus tests en verde. Al final: suite completa, humo, revisión de
Astra y despliegue con vuelta atrás automática.

1. **Tu agenda.**
   - En el tenant `Vantelia`: horario de lunes a viernes de 10:00 a 13:30 y de 16:00 a
     18:00, sábados y domingos cerrados, y el servicio "Llamada con Pablo · 15 min".
   - Se hace con los endpoints del portal, como la demo de Noelia, y con copia antes de
     tocar nada. Ojo a las trampas de `docs/MAPA_DEL_CODIGO.md` sobre el catálogo y
     sobre `config.json` frente a memoria.
   - Comprobar que el widget de la web sigue dando citas con ese horario.
2. **Invitación y calendario.**
   - Al reservar o mover una cita, invitación `.ics` (`icalendar`) a Pablo y al lead.
   - Si Pablo da la dirección iCal, sus ocupados bloquean huecos (se lee cada 10
     minutos, con caché).
3. **`backend/setter.py` y la tabla `setter_leads`.**
   - Entradas: `seguimiento_demo.cualificar`, una respuesta con interés
     (`al_responder`), el "pasar a Pablo" de Sara y `consulta_leads`.
   - Una entrada por lead, aunque llegue por dos vías.
4. **El primer correo en menos de 5 minutos**, dentro de la ventana (y si no, a las
   8:30):
   - En el hilo, a nombre de Pablo y con el pie profesional.
   - Dos horas reales como botones de reserva con un clic (`GET /reunion/{token}`,
     firmado y con caducidad) y "elige otra".
   - Si el hueco ya está cogido, la página enseña otros.
5. **La cadencia** (días 0, 3 y 6), los topes compartidos del buzón, la parada al
   responder o decir que no, y los festivos.
6. **Respuestas con sus palabras.**
   - Fecha y franja: el código resuelve el hueco y reserva, o propone dos horas.
   - Precio, condiciones o quejas: borrador a la bandeja, con aviso a Pablo.
7. **Recordatorios y reunión.**
   - Los de 24 h y 2 h del motor, más un SMS 2 horas antes si dio un móvil.
   - La ficha 30 minutos antes.
   - "¿Lo movemos?" si no se presenta.
   - Resultado en un clic (ganado, seguir o perdido), que mueve la oportunidad en el
     Plan de escala.
8. **Reagendar.** El botón "Mover" en la ficha y en la sala: otra hora, o "que elija
   ella", con dos horas nuevas.
9. **Motor mínimo de la oficina.**
   - Tablas `oficina_*`, la bandeja y el estado de los que ya trabajan y de Marta.
   - **Tomás con los saldos**: ElevenLabs y Twilio ya; Stripe; OpenAI por `trazas`.
     Zadarma y Brevo, cuando estén sus claves.
   - Un aviso solo si algo se acaba en menos de 7 días.
10. **Sala, primera versión.** La escena con las zonas (mesa, café, esperando a Pablo,
    fuera de horario, atascado), tu mesa con las reuniones de hoy y la bandeja, y el
    calendario en la pared.
11. **Prueba completa con un lead de prueba** (tu propio correo, origen `manual`, que no
    cuenta en el embudo):
    - Se cualifica, recibe el correo, pincha, reserva y le llega la invitación.
    - Recordatorios.
    - Mover.
    - No presentarse.
    - Resultado.
    - Después, se borran todos los datos de la prueba.
12. **Encender con los cuatro leads de octubre:** antes de que salga nada, Pablo ve los
    cuatro correos y los aprueba. Es la primera vez que la setter escribe a gente real.

**Hecho cuando:** un "me interesa" real recibe el correo en menos de 5 minutos, la cita
aparece en tu calendario, y en la sala se ven los minutos hasta el primer contacto,
cuántos cualificados tienen reunión y la asistencia.

---

## Fuentes

- Paperclip: [glosario](https://docs.paperclip.ing/guides/welcome/glossary),
  [agentes](https://docs.paperclip.ing/guides/org/agents) y
  [lecciones (ZenML)](https://www.zenml.io/llmops-database/open-source-agent-orchestration-platform-for-multi-agent-business-automation)
- [Star Office UI](https://gittrend.io/repo/ringhyacinth/Star-Office-UI) y
  [Pixel Agents](https://github.com/martinmunozhr/pixel-agents)
- Coste de los latidos de OpenClaw: [Findstack](https://findstack.com/resources/how-much-does-openclaw-cost-to-run)
  y [Insider LLM](https://insiderllm.com/guides/openclaw-token-optimization/)
- Arquitectura de tablón: [arXiv 2507.01701](https://arxiv.org/html/2507.01701v1) y
  [arXiv 2510.01285](https://arxiv.org/html/2510.01285v1)
- [Por qué fallan los sistemas multiagente (MAST)](https://arxiv.org/html/2503.13657v2) y
  [el sistema multiagente de Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)
- Velocidad de respuesta: [estudio del MIT e InsideSales (PDF)](https://www.mortech.com/hs-fs/hub/25649/file-13535879-pdf/docs/mit_study.pdf) y
  [resumen de los estudios (2026)](https://ainora.lt/blog/lead-response-time-statistics-every-study-2026)
- Setters con IA, lo aprendido: [Laxis](https://www.laxis.com/blog/ai-sdr-augments-human-sdrs-openai-anthropic-2026/),
  [Naoma](https://naoma.ai/articles/ai-sdr-dying-2026) y
  [Cleverly](https://www.cleverly.co/blog/ai-appointment-setting)
- Ausencias y recordatorios: [Naoma](https://naoma.ai/blog/article-01-demo-no-shows) y
  [RevenueHero](https://revenuehero.io/blog/ways-to-reduce-no-show-rates-in-sales-calls)
- Construir o aprovechar: [Paperclip en GitHub](https://github.com/paperclipai/paperclip),
  [Star Office UI en GitHub](https://github.com/ringhyacinth/Star-Office-UI),
  [licencia de LimeZu (itch.io)](https://itch.io/post/8040706) y
  [lychee-action](https://gittrend.io/repo/lycheeverse/lychee-action)
- CFO con IA: [GhostCFO](https://hunted.space/product/ghostcfo) y
  [cfo.ai Ari (SiliconANGLE)](https://siliconangle.com/?p=837986)
- APIs de saldo y gasto: [OpenAI Usage/Costs API](https://community.openai.com/t/introducing-the-usage-api-track-api-usage-and-costs-programmatically/1043058),
  [Zadarma](https://zadarma.com/support/api/) y
  [Brevo get account](https://developers.brevo.com/reference/get-account)
- [Scaled content abuse (PPC Land)](https://ppc.land/scaled-content-abuse/)
