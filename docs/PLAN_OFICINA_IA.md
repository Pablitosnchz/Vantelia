# La oficina de Vantelia: agentes con un trabajo fijo y una sala para verlos

Plan del 7-oct-2026. Lo pidió Pablo después de ver en Instagram una "oficina de IA"
(agentes de trading en un despacho isométrico): *"define los agentes que
necesitaríamos con lo que es viable y barato, uno que gestione la parte económica,
que si alguno no tiene nada que hacer vaya a por un café y no gaste tokens, pero que
sea visual para saber con qué está cada uno"*.

Lo que **no** es: una empresa de agentes charlando entre ellos sin parar. Esa versión
falla mucho y cuesta caro (apartado 1). Lo que **sí** es: siete puestos nuevos que
despiertan a su hora, miran si tienen trabajo, lo hacen, dejan el informe en un tablón
y se duermen. Y una sala en el panel donde se ve, en directo, con qué está cada uno.

Nada de esto toca a los clientes ni escribe a nadie de fuera: **los agentes proponen y
Pablo aprueba**.

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

### 2.1 Los que ya trabajan (no cambian; solo se les pone cara)

Ya hacen su trabajo con código determinista o con su propia IA. En la sala aparecen con
su estado real, leído de la base de datos, sin gastar tokens.

| Puesto | Qué hace hoy | De dónde sale su estado |
|---|---|---|
| **Sara** (llamadas) | Llama a negocios en las franjas, manda demos y pasa leads | `llamadas_*` y la lista de hilos (`appstate.worker_status`) |
| **El Cartero** (correo frío) | Busca negocios, manda el correo frío y los seguimientos, con calentamiento y pausas | `sends` y `autopilot_config` (en pausa, tope del día) |
| **Seguimiento** | Escribe a quien recibió su demo y cualifica leads | `seguimiento_demo` |
| **El Buzón** (lector de respuestas) | Lee info@, detecta respuestas y rebotes y te avisa | `events` de tipo `reply` y `bounce` |
| **El Vigilante** | Salud de la web, del correo y de OpenAI; uptime cada 15 minutos | `/health`, `/admin/ia-health`, `/admin/email-health` |
| **Calidad** | Repaso diario, gratuito y determinista, de las conversaciones de cada cliente (`calidad.py`) | Las conversaciones que marca |
| **Claude** (programa y despliega) y **Astra** (revisa) | Encargos y revisiones por el buzón de la sincronía | La foto de la sincronía (incluido "Astra sin cuota hasta las 18:00") |

### 2.2 Los siete nuevos (piensan con IA, por turnos)

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

### 2.3 Lo que cuesta todo

| | Al mes |
|---|---|
| Los siete agentes, por la estimación de arriba | **~2 €** |
| Topes de presupuesto (si todos lo agotan) | 7 € (tope general de la oficina: 5 €) |
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
- Sara: "📞 al teléfono, 23 llamadas hoy" o "fuera de franja".
- El Cartero: "✉ 12 de 30 enviados" o "en pausa hasta el lunes".
- Astra: "☕ sin créditos hasta las 18:00".

### En cada puesto

Al pinchar en un agente: el último informe, el siguiente turno, lo gastado en el mes
frente a su tope, sus indicadores y un interruptor.

**Tu mesa es la bandeja:** las propuestas pendientes, con **Aprobar / Rechazar /
Comentar**. Las rechazadas guardan el motivo, y el agente lo lee en su siguiente turno
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
| **1** | Motor, tablón, bandeja, presupuestos y la sala con **los que ya trabajan** (sin IA nueva). **Tomás**, solo saldos y alertas (sin IA). **Elena**, parte diario. | 2 tardes | Lo más útil desde el primer día: no volver a caerse por saldo y un solo correo por la mañana. Casi no gasta. |
| **2** | **Hugo** (llamadas) y **Lucía** (atención a clientes) | 2 tardes | El cuello de botella (las llamadas no dan demos) y proteger a los clientes de pago con Cap Rocat entrando en vivo. |
| **3** | **Nora** (correo), **Iker** (web y SEO), **Tomás** semanal y fiscal (tarea del PC) | 2 tardes | Mejoran lo que ya funciona. Iker necesita el acceso a Search Console. |
| **4** | **Bruno** (ideas), modo escaparate y dibujo bonito | 1-2 tardes | Cuando los demás ya tengan un mes de informes que leer, y para tener contenido para redes. |

Revisión de cada agente a las cuatro semanas de encenderlo: si no ha movido sus
indicadores, se apaga.

**El 3T no espera a Tomás:** el 303 y el 130 de antes del 20/10 se preparan a mano como
estaba previsto.

## 6. Lo que tiene que dar Pablo

Nada de esto es imprescindible para la fase 1. Sin la clave correspondiente, el agente
lo dice y sigue con lo demás.

- Clave de la **API de Zadarma** (la que hay ahora es solo la del SIP).
- Clave de la **API de Brevo** (ahora solo hay SMTP y el secreto del webhook).
- Clave de **administrador de OpenAI** (`sk-admin-…`), solo para leer el gasto.
- **Search Console:** la propiedad verificada y acceso para una cuenta de servicio
  (para Iker).
- A qué correo va el parte diario (por defecto, el de los avisos de siempre).

## 7. Riesgos

| Riesgo | Freno |
|---|---|
| Más ruido en el correo | Un solo correo al día (el de Elena). Lo demás se queda en la sala. |
| Que se invente cifras | Las cifras las calcula el código. Toda propuesta lleva su evidencia enlazada. |
| Que el gasto se dispare | El portero, el tope por agente, el tope general y un máximo de tokens por turno. |
| Que se cuele un cambio malo | Nada sale sin Pablo. El código pasa por la revisión de Astra y el despliegue tiene vuelta atrás automática. |
| Datos de clientes en un vídeo | El modo escaparate no lleva nombres, y lo vigila un test. |
| Mantenimiento | Un solo motor. Añadir un agente es añadir una entrada a `AGENTES`. |

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
- CFO con IA: [GhostCFO](https://hunted.space/product/ghostcfo) y
  [cfo.ai Ari (SiliconANGLE)](https://siliconangle.com/?p=837986)
- APIs de saldo y gasto: [OpenAI Usage/Costs API](https://community.openai.com/t/introducing-the-usage-api-track-api-usage-and-costs-programmatically/1043058),
  [Zadarma](https://zadarma.com/support/api/) y
  [Brevo get account](https://developers.brevo.com/reference/get-account)
- [Scaled content abuse (PPC Land)](https://ppc.land/scaled-content-abuse/)
