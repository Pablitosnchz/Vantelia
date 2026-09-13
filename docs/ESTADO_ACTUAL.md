# Estado actual de Vantelia

**La memoria compartida entre los agentes que trabajan en este repo.** La lee
quien empieza una tarea y la actualiza quien la cierra. Lo que no esté aquí, el
otro agente no lo sabe: cada uno tiene su propia memoria y no se ven entre sí.

Última actualización: 13-sep-2026, Astra (suite de formularios y condiciones aceptadas;
no implica cambios en producción).

Los dos agentes no comparten memoria. Lo que uno sabe del otro sale de este
fichero, de `git log` y del buzón de `scripts/sincronia.py` (peticiones de
revisión y avisos, que llegan solos a la sesión del otro): Pablo no hace de
mensajero.

## Cómo se trabaja ahora

- **Astra coordina e implementa la consolidación** (encargo vigente de Pablo).
- **Claude auxilia con revisiones, mediciones y piezas encargadas** en ramas propias. Despliegue solo por orden de Pablo.
- **Pablo decide.** Reglas completas en `AGENTS.md`.
- **¿Estáis sincronizados?** → https://app.vantelia.es/sincronia (semáforo, solo
  admin). Pablo no tiene que decir nada: los hooks de los dos agentes los ponen al
  día solos al empezar y con cada mensaje suyo, y el agente le cuenta lo nuevo.
- **Astra termina → Claude revisa solo.** Astra pide revisión, la tarea programada
  «Vantelia revisor» pasa los tests en una copia aparte y lanza la revisión de
  Claude, y la respuesta llega a la sesión de Astra, que se lo cuenta a Pablo.
  Pablo solo dice «despliega», a cualquiera de los dos.
- **Si a uno se le acaban los tokens**, el otro se pone al día solo y sigue en la
  MISMA rama.
- **No solo revisar: trabajan juntos.** Astra le pregunta a Claude
  (`--pedir-ayuda`) o le encarga trabajo en paralelo (`--encargar astra claude`,
  lo hace en su rama `claude/encargo-…`), y Claude a ella (`--encargar claude
  astra`). Todo llega solo a la sesión del otro.

## En curso

Quien tiene el testigo lo actualiza cada vez que cambia (no solo al cerrar). La
página de sincronía lo enseña tal cual.

- **Testigo:** Claude, agente principal desde el 13-sep (decisión de Pablo). Astra sin créditos hasta el 19-sep 11:24; sus copias de trabajo no se tocan.
- **Tarea:** cerrar el crítico `dice-que-si-y-acaba-en-cita` sobre el candidato y preparar la entrega a Alicia.
- **Rama:** `claude/candidato` en E:/Vantelia (único árbol con credenciales para medir), HEAD `762800a`, descendiente de `astra/condiciones-confirmadas` 6c3ad4f (que contiene todas las ramas de Astra). Suite completa 2473 verdes en be6bec9; banco 42/43 en 782a53f.
- **Decisión de Alicia confirmada (13-sep):** a quien no sabe qué alisado quiere se le ofrece la cita «Diagnóstico y presupuesto». Se declara como regla de orientación, no se deduce de su Q&A.
- **Siguiente (Claude):** medir el crítico ≥6 tiradas con la regla en copia (en curso); arreglar la trampa de familias (una regla escrita «alisado» no casa con «Keratina premium»); suite + banco + humo; segundo negocio; cambio del portal a mitad de conversación; informe de aceptación; orden de despliegue de Pablo.

Relevo anterior de Astra (histórico, sustituido por lo de arriba):

- **Testigo:** Astra.
- **Tarea:** suite exacta de formularios 2cb8a029 iniciada; en rama hija, términos efectivos aceptados y arnés que observe transporte/efectos sin anticipar autorización del producto.
- **Rama:** astra/condiciones-confirmadas, E:/Vantelia-astra-condiciones, hija de 2cb8a029. E:/Vantelia-astra-formularios queda congelado mientras se mide; no editar ese árbol ni repetir pruebas allí.
- **Siguiente:** gestion_implementacion prepara contrato versionado compartido entre resumen, núcleo, guardado y checkout; evidencia_real elimina dependencia de estado productivo en captura/acciones y demuestra compatibilidad de transporte e IDs anteriores sin HTTP. Astra contrasta diseños/diffs y mantiene relevo. Suite exacta 2cb8a029 iniciada a las 03:00:44.987 +02:00 (redondeado a ms), sesión 56124; formularios-suite.result.json y .log externos. Una lectura de metadata, sin sondeos de progreso. Formulario/arnés nuevos aún en diseño; no hay nuevos verdes. Registro: docs/REGISTRO_CONSOLIDACION.md.
- **Espera a:** revisión exacta de 7ab7775 solicitada automáticamente tras 2297 passed, 1 skipped (duración 18 min 55 s; fin 13-sep 01:04 Europe/Madrid). Claude sin cuota hasta las 04:00 Europe/Madrid; calendario pendiente. Banco real Alicia/otro, recordatorios, reconciliación y resto de gestión no están aceptados. Sin push ni despliegue.

QA visual exacta de de3d6d0 terminada: **exit 0**, 02:36:26–02:37:51 Europe/Madrid,
SHA y árbol limpios antes/después. Instrumento externo verifica 37 marcas de
15 min, tres interiores entre horas, alineación con la columna y horas visibles;
recorrido completo y duración persistida de 45 min. Capturas y resultado en
C:/Users/pabli/.codex/vantelia-coordination/portal-ledger.*. Google Fonts se
sustituyó por CSS vacío para impedir red externa: tipografía de sistema.

La captura reveló etiqueta de catálogo «20 min» sobre bloque/BD de 45 min.
23139ca corrige la etiqueta reutilizando cdDur y preserva precio/ausencia de
datos; regresión Node roja antes y verde después. Una nueva QA exacta sobre
2cb8a029 pasó el 13-sep 03:05:16–03:06:56 Europe/Madrid (exit 0, árbol/SHA
limpios antes/después): etiqueta «45 min» coincide con BD45 y conserva precio
18 €. También pasa geometría de 37 ticks/10 horas (8 visibles) y recorrido
completo. Artefactos portal-formularios.* externos; Fonts bloqueado con CSS
vacío y tipografía de sistema. Este resultado acredita el arreglo en 2cb8a029,
no en la captura anterior de de3d6d0. No se repite ninguna de esas QA verdes.

Arnés 2533fe9 revisado: `botones-explicitos-v1` exige una acción estructurada y un ID
realmente emitido por el builder productivo para esa clienta/tenant y propuesta
vigente. El texto libre nunca pulsa. 23 dirigidos verdes a las 02:49:33
(37,45 s); rojo causal del ID legacy y dos rojos de diccionario/cuarto botón
descartado antes del arreglo. Aceptación de transporte simulada, sin modelo ni
Meta reales; los informes de otra versión no se comparan. El caso crítico del
banco real todavía no acredita el efecto final en agenda; queda pendiente medir
antes/después con la misma versión del instrumento.

Límite de medida confirmado por lectura: CapturaEnvios.opciones depende de
reserva.leer_confirmacion_reserva y filtra estado ofrecida/IDs del protocolo
actual. Un botón realmente emitido pero ya obsoleto se detiene en el arnés,
sin probar el rechazo del producto; una baseline sin esa API tampoco está
soportada. La comparación histórica no queda demostrada solo por compartir
versión del instrumento. Siguiente: transportar la acción explícita emitida y
dejar al producto validar su autorización, comprobando después agenda/estado;
conservar aislamiento de destinatario y no deducir clicks del texto.

Cinco fixtures heredadas guardadas en 891a730 y revisadas OK: 38 passed a las 02:55:28, frente a siete
rojos y un control previamente verde. Usan huecos reales del tenant y mantienen
los validadores; el caso sin fianza exige además que exista resumen. No se
repitieron dirigidos durante la revisión; la suite de formularios se lanzó
después sobre 2cb8a029, todavía sin resultado consultado.

Siguiente riesgo identificado por lectura, aún sin reproducción ejecutada:
la propuesta y la huella de creación no sellan duración/precio/fianza/política.
Un cambio de catálogo entre resumen y botón puede conservar la identidad del
resumen y ejecutar condiciones nuevas. Preparar regresión sintética y cotejar
los términos efectivos en la preparación compartida antes de ejecutar; no
añadir cálculos paralelos ni dar este caso preexistente por resuelto con el
formulario. La revisión del formulario cierra disponibilidad y profesional
resuelto: 66 dirigidos verdes en 92,44 s; cinco fixtures heredadas ya adaptadas
y revisadas en 891a730. Suite exacta 2cb8a029 iniciada según el relevo superior;
todavía sin resultado consultado, sin medición real.

Última suite exacta de3d6d00e22e6f089055a1370c23fe9831205c8d terminada a las
**02:52:00.149448 +02:00**, exit 1: **2401 passed, 1 skipped, 1 failed**, sin
xfail. El único fallo exige incluir notice_deliveries en docs/ARQUITECTURA.md
(test_mapa_del_codigo_no_miente.py:125). Coordinación verificó resultado/log;
no se pidió revisión formal ni se declara verde. Se corrige el mapa en esta
rama hija, sin tocar el SHA congelado ni repetir la suite completa. Los verdes
dirigidos del hijo no son una suite completa. Corrección documental validada:
5 tests del mapa verdes (3,03 s), log externo mapa-notice-deliveries-verde.log.
Suite anterior: 2235d25, fin
13-sep **02:15:01 Europe/Madrid**, exit 1:
**2347 passed, 1 skipped, 1 xfailed y 2 fallos de cancelación**. Coordinación
verificó el resultado a las 02:16 en
C:/Users/pabli/.codex/vantelia-coordination/gestion-suite.result.json y su .log.
No sigue ejecutándose ni se pidió revisión automática de ese candidato.
Los dos rojos se reprodujeron a las 02:25:27: exigían cancelar al código/botón del
recordatorio sin aceptar propuesta. ca8e626 captura y acepta el ID real, mantiene
la cita confirmada hasta entonces y conserva las comprobaciones finales.
34 dirigidos verdes a las 02:27:09 (32,06 s), sin cambio de código productivo.
El verde de 7ab7775 pertenece al antecesor, en integrado-wa-suite.result.json.
El seguimiento cada 30 minutos está actualizado para retomar el último relevo y
anotar avances con hora. No implica actividad continua entre ejecuciones.

ff59b06 de astra/recordatorios-fiables ya está integrado. Su worktree se reutiliza
ahora en astra/entregas-recordatorios, sin modificar ni borrar aquella rama. Se ha
reproducido concurrencia de recordatorios (xfail estricto en 2235d25). El xfail se
retira únicamente en el hijo en desarrollo, donde la reclamación pasa dirigida;
esto no cambia el resultado del candidato anterior ni acredita una suite nueva.
El nuevo bloque no debe repetir envíos de resultado incierto ni introducir otra
autoridad conversacional. La generación debe cambiar al reprogramar, también si
la cita vuelve a su horario inicial; una fila de cita existente no acredita envío.

Validación dirigida nueva (selecciones solapadas): cancelación, último cierre 57
verdes, con regresiones rojas de cambio de cita, resultado perdido, menú y salto
al agente tras atención humana. Banco, último cierre 14 verdes, con guard de ruta,
persistencia por intento y casos no medidos. Recordatorios: 31 verdes y un xfail
de duplicación pendiente. QA navegador completa exit 0 sobre árbol de trabajo;
no es evidencia del modelo/Meta ni atribución a un SHA estable. Detalles y límites
en docs/ACEPTACION_CANDIDATO_IA.md. Estas selecciones preceden a la suite roja y
no sustituyen su resultado.

Trabajo posterior revisado o en revisión (selecciones solapadas): transporte
c1db689, 29 pruebas propias y 56 relacionadas verdes, aceptación HTTP distinta de
entrega al teléfono. Ledger: 66 dirigidas y 2 de plantilla previas, cierre final
de 16 verdes en 54,28 s (02:23:57) y revisión local OK. Aceptación y evento del
tope se guardan en una transacción; caída posterior recupera sin reenviar ni
perder el contador. Guardado en b5fa459; pendiente validar el candidato integrado.
Copia/informe 09aebfc: 6 rojas iniciales, 5 nuevas de sidecars/normalización y
27 dirigidas verdes finales, revisión independiente OK. Protege DB/WAL/SHM antes
de escribir y conserva el origen mediante apertura de solo lectura.

Límites del ledger: no reconcilia operativamente un resultado incierto, no reserva
el cupo global entre citas diferentes y no elimina la ventana de cambio tras la
última relectura y durante la red. El fallback interno de email sigue fuera de
esta pieza. Aceptación del proveedor no equivale a entrega al teléfono.

## Notas históricas (el bloque En curso prevalece)

QA visual independiente de 7ab7775 (13-sep 01:22): parcial, exit 1 por un supuesto
de fecha del instrumento. Tras corregir solo el arranque NLTK en el lanzador,
se recorren acceso, servicios/centros, Ventas, Informes y responsive; Nueva cita
espera huecos del domingo cerrado antes de avanzar al lunes. Arrastre y
persistencia de duración: NO MEDIDOS. No es un verde ni una regresión de producto
acreditada. Evidencia en ACEPTACION_CANDIDATO_IA.md y REGISTRO_CONSOLIDACION.md.





Sincronía: retiradas seis peticiones propias de revisión de antecesores verificados
(0b6043f, 550aafe, 6e040e1, 12d2614, 44dddf8, 530ae40) para evitar trabajo
duplicado. Son peticiones sustituidas, no aprobaciones. La revisión
de cf2066d llegó OK el 13-sep; el diagnóstico de demos sigue encargado y sin resultado.
No hay suite completa nueva en ejecución ni revisión solicitada del descendiente
de 4ed33c7: primero deben cerrarse esos fallos. El seguimiento autónomo sigue activo.
El trabajo local de WhatsApp se conserva en su rama propia; no sustituye el diagnóstico
de demos encargado a Claude ni afirma entregas de modelo/Meta reales.

Entrega anterior de Astra: 9b1bfea, creación recuperable de WhatsApp, rama limpia al
cerrar; 66 dirigidos de integración y 23 de cierre verdes (solapados), cuatro rojos
prearreglo y mutación roja de identidad. No se ha pedido revisión formal sin suite
completa. Sin push/despliegue. Contraste posterior de la respuesta de Claude: existe orientación declarada, pero
NO se ha retirado el atajo Q&A cuando falta esa política. El hallazgo sigue vigente
en el candidato actual; no dar esa sustitución por terminada. Sigue sin inventarse
la decisión particular de Alicia entre foto y diagnóstico.

Retirada Q&A implementada (13-sep): se elimina `_hay_que_cogerle_la_valoracion`
y su búsqueda que imponía diagnóstico. La nota solo ayuda a aclarar, sin consultar
Q&A/catálogo ni elegir un servicio. El recorrido declarado conserva propuesta y
aceptación. Tres regresiones de técnica/talla fallan antes del cambio; 102 pruebas
dirigidas verdes (oferta, aceptación, rechazo/obligatoriedad, catálogo, no elegir
por ella, shim). Las pruebas antiguas que imponían diagnóstico pasan a cubrir el
recorrido sin política; las de renuncia se mantienen en el núcleo compartido.
`pyflakes backend/agent.py` y diff limpios. No es una medición con modelo real ni
completa la migración del resto de autoridades. El comportamiento concreto para
Alicia sin elección de servicio sigue requiriendo política acordada.

cf2066d OK no implica integración: quedan mejoras menores de coste del sondeo de
cuenta, aviso visible de identidad desconocida y actualización documental al integrar.
Conservar su revisión y tratarlas sin bloquear el diagnóstico de demos.

Pendientes operativos que no deben perderse: estado de la plantilla de recordatorios
y prueba de envío real; confirmar situación actual con Claude. Última referencia
documental anterior de producción: `aab4d02`, no verificada de nuevo en esta revisión.
Los relatos de medición antiguos de más abajo son históricos; la referencia con
calendario reproducible se distingue arriba y no oculta los reintentos.

Por qué se integró antes de su revisión (Claude): sus 8 tests nuevos fallan 7
contra el código sin el arreglo y pasan con él; pytest completo en verde (2026);
el humo del caso contra una copia de producción no empeora (el fallo original es
poco frecuente: 1 de 4 despliegues el 11-sep). Su worktree tiene cambios sin
commit (`booking.py`, `voice.py` y el test) que no se han tocado.

Validación local de Astra: las tres regresiones iniciales fallaron sin el arreglo;
el control de reserva nueva pasó. Con el arreglo pasan los ocho casos específicos
(incluyen profesional, duración, exclusión propia, primer hueco automático y código
ajeno/inexistente), y una selección de 99 pruebas de voz, agente y compatibilidad.
Esto mide comportamiento determinista, no la tasa de fallos del modelo real.

## Lo último en producción

- **Agenda del panel**: la cita se lee entera (el día se pinta a 2,2 px/min, así
  que una de 15 min muestra nombre completo y servicio); selector de horas por
  franjas con scroll; estirar o acortar arrastrando cualquiera de los dos bordes,
  de 5 en 5, sin avisar a la clienta; el mostrador puede apuntar citas fuera de
  horario (la IA no).
- **Nombre y dos apellidos obligatorios** al crear cita o cliente desde el panel
  (400 desde el backend). Por WhatsApp se piden los apellidos UNA vez.
- **WhatsApp**: el freno de "cita sin pedir" decide por hechos, no por frases; la
  hora se comprueba ANTES de enseñar el resumen; los botones del aviso de cita
  duplicada ya no revientan en Meta; el resumen solo queda en el historial si
  Meta lo aceptó.
- **Asistente**: no elige la técnica por la clienta; un "sí" a la cita de
  valoración cuenta; no niega un servicio que existe cuando le dan el nombre
  exacto.
- **Captación**: se borró todo el código que automatizaba productos de Meta
  (DMs de Instagram y WhatsApp Web). No se vuelve a montar: ver `CLAUDE.md`.
- **Sincronía entre agentes** (11-sep, `7fb3823`): https://app.vantelia.es/sincronia
  enseña con un semáforo si Claude y Astra han visto lo último del otro, y lo que
  se dicen entre ellos.
- **Revisión automática** (11-sep, `dbdba26` + `83bbeb6`): cuando Astra pide
  revisión, la tarea programada «Vantelia revisor» pasa los tests en una copia
  aparte y lanza la revisión de Claude sin nadie delante. Probada de verdad con
  `claude -p`: revisión útil y veredicto bien leído.
- **Sin créditos** (11-sep, `3fd5e0b`): si uno se queda sin cuota lo sabe el otro
  solo (a Astra se le lee de su propia sesión de Codex, con la hora de vuelta) y
  sigue él; nada se pierde mientras tanto.
- **Reprogramar a la primera** (11-sep, `5d05457`, en producción `1268e4a`): al
  mover una cita solo se ofrecen horas de SU profesional y que el núcleo acepta
  (antes se ofrecían huecos de otra y el cambio se rechazaba). Lo encontró y
  arregló Astra; lo integró y desplegó Claude.
- **Mensaje ilegible por WhatsApp** (11-sep): el primer "hola" al +31 recién
  conectado llegó de Meta sin texto, y al modelo se le pasaba una instrucción por
  el hueco del texto de la clienta; quedaba en el historial como dicha por ella y
  al mensaje siguiente repetía "no puedo leer mensajes que no estén en formato de
  texto". Ahora se pide que lo repita con una frase fija (también el audio que no
  se oye) y abrir el chat por primera vez (`request_welcome`) cuenta como saludo.
  Los avisos de sistema de Meta (cambio de número) no se contestan.
- **«La primera que tengas» acaba en cita** (11-sep): el código elegía el primer
  hueco (a última hora, hoy a diez minutos vista) mientras el modelo le enseñaba
  horas de otro día, y el nombre no se anotaba hasta `crear_cita`: le repetía la
  lista y se quedaba sin cita. Ahora la hora del código sigue al día que ella lee,
  "me llamo X" se anota al momento (se cierra en ese turno), y el primer hueco de
  hoy deja una hora de margen. En 6 conversaciones contra copia de producción:
  5 reservan con el primer "sí"; en la otra el modelo mezcló el día que
  encabezaba su lista con la hora elegida, la herramienta lo frenó (ninguna cita
  mal cogida) y reservó al siguiente "sí". Para esa mezcla, guardarraíl
  (`reserva.dia_cambiado_con_la_hora_elegida`): si la llamada trae la hora elegida
  con otro día que ella no ha dicho, manda el día que se le propuso. Con él, otras
  6 conversaciones: las 6 al primer "sí" (la mezcla no se repitió; la cubre el
  test).
- **El asistente vuelve a la hora** (11-sep, decisión de Pablo): tras contestar el
  equipo desde WhatsApp Business se calla 1 h desde su último mensaje (antes 2 h;
  por negocio, `whatsapp.silencio_tras_responder_min`). Al volver, un "hola" no
  saca la bienvenida con el menú: lo coge el agente, que conserva lo hablado (su
  historial ya no se corta a la media hora si ha intervenido una persona).
- **"Corte de señora" es "Corte señora"** (11-sep): un "de" de más en el nombre
  que escribe el modelo ya no cambia el servicio. Antes no se encontraba y la
  cita se cogía de 15 min (el paso de la agenda) en vez de 20, con un nombre que
  no existe en el catálogo.
- **Recordatorios por WhatsApp fuera de la ventana de 24 h** (11-sep, `57f6d45`):
  Meta solo deja escribir texto libre 24 h desde el último mensaje de la clienta,
  así que un recordatorio del día antes casi siempre se perdía. Ahora sale como
  plantilla (`vantelia_recordatorio_cita`, transaccional) de la cuenta del propio
  negocio, con los mismos botones «Confirmo» y «Cancelar cita», que ya se
  procesan al pulsarlos. La plantilla la da de alta y consulta el worker; en la
  cuenta del +31 ya está creada y en revisión. Sin plantilla aprobada no sale por
  WhatsApp: el aviso sigue por el siguiente canal y el motivo queda anotado.
  Además, **las citas de demo ya no avisan ni llaman a nadie** (la cuenta de
  revisión de Meta tiene 191 con móviles inventados). Cada plantilla fuera de
  ventana la cobra Meta al negocio, que necesita método de pago allí.
- **Dos apellidos por WhatsApp** (11-sep, decisión de Pablo): a una clienta nueva
  se le piden nombre y dos apellidos antes del resumen (freno en `crear_cita` del
  agente y en el flujo con listas, que junta lo que va diciendo; a la tercera se le
  ofrece llamar). A una clienta conocida no se le pide nada.
- **No ofrece una hora que no existe** (12-sep, `e6be556`): tras enseñarle
  09:00-10:00, a un «a las 15» contestaba *«mañana a las 15:00 tengo disponible»*,
  ella decía que sí, y la mentira solo se descubría al crear la cita, tres turnos
  después (la cita imposible NUNCA nació: el hueco se comprueba al crearla). Ahora,
  si ofrece una hora que no está en los huecos que tenemos y no ha mirado la agenda
  en ese turno, se le obliga a mirarla. En las trazas se ve funcionando: contesta
  «las 15:00 no las tengo, tengo estas por la mañana» en el turno bueno.
- **Lo de Astra, verificado e integrado** (12-sep, `aab4d02`): el botón de mover
  cita ya no canta éxito cuando el núcleo rechaza el cambio; el pack de la cita no
  se convierte en el servicio suelto al moverla; a una clienta ya conocida no se le
  vuelven a pedir los apellidos; y una respuesta que Meta rechaza no queda en el
  historial como enviada. Comprobado antes de integrar: sus 5 tests fallan contra
  main sin sus arreglos, suite entera sobre su rama (2082) y sobre la fusión (2116).

## El crítico que no cierra (12-sep, medido de madrugada)

El caso `dice-que-si-y-acaba-en-cita` sigue siendo INTERMITENTE y es lo único rojo
del banco: **42 de 43** contra copia fresca de producción con la config viva.

Lo que se sabe, medido:

- Con el freno de la hora inventada: 4 de 9. La MENTIRA está tapada; lo que falla
  es el cierre. La conversación se atasca porque el servicio sigue sin concretarse
  («no lo tengo claro») y el modelo vuelve a preguntar la técnica en vez de cerrar.
- **El atajo que debería cortar eso lleva desde el 8-sep muerto.**
  `_hay_que_cogerle_la_valoracion` corta a la TERCERA pregunta y coge el
  diagnóstico, pero el contador (`veces_falta`) solo subía si faltaba el MISMO dato
  dos veces seguidas, y el modelo alterna (técnica, largo, técnica): se reiniciaba
  siempre. No saltó ni una vez en 12 conversaciones medidas. Hay un intento de
  arreglo en `claude/hora-sin-mirar` (`_veces_sin_concretar`), **sin validar**: con
  él tampoco llegó a saltar, así que la causa puede ser otra.
- Ampliar el freno de la hora (que frenara también sin huecos sobre la mesa):
  1 de 6. Descartado de momento.

**DOS TRAMPAS DEL INSTRUMENTO, las dos costaron conclusiones falsas esta noche:**

1. Medir desde un worktree NO vale: no tiene `.env`, así que no hay clave de
   OpenAI y todas las conversaciones fallan por lo mismo. Dio un 0 de 4 que no
   medía nada. Los worktrees valen para tests, no para el banco.
2. **El guion del caso dice «manana», y el resultado depende de qué día sea.**
   Medido en la madrugada del sábado al domingo: «mañana» cae en domingo, que el
   salón CIERRA, así que la conversación correcta ya no puede acabar en cita. Peor:
   algunas tiradas «pasaban» porque el modelo reservaba HOY llamándolo «mañana».
   Comparar medidas tomadas a un lado y otro de la medianoche es comparar días
   distintos. Si se toca este caso, medir de día y con «mañana» abierto.

Fragilidad aparte: `tests/test_estirar_la_cita.py` da 11 errores en un worktree
limpio (fixture que reserva y recibe 409) y pasa en `E:/Vantelia`. Depende de
estado local, no es hermético. No es de esta noche: pasa igual en `aab4d02`.

## Bloqueado por fuera del código

- **Coexistence: DESBLOQUEADO (11-sep).** Meta aprobó la revisión de la app y
  Pablo la publicó. El +31 97006546256 de Vantelia funciona en Coexistence (WA
  Business en su móvil + asistente a la vez) y contesta con el **asistente de
  Vantelia** (tenant `metareview`, "Clara"). Estuvo unas horas con el de Alicia y se
  deshizo a petición de Pablo: su pestaña WhatsApp está limpia para que conecte el
  suyo. Si alguien contesta desde WA Business, el asistente se calla 1 h desde su
  último mensaje en ese chat (vuelve solo, sin saludar de nuevo y sabiendo lo
  hablado; o «Devolver al asistente» en Conversaciones).
- **Avisos de cita de Alicia: hoy no sale ninguno.** En el bloque que usa el motor
  (`booking.message_template_channels`) tiene el email apagado y solo WhatsApp, y
  WhatsApp no está conectado. Cuando conecte su número empezarán las
  confirmaciones por WhatsApp; los recordatorios de 24 h casi nunca saldrán hasta
  que haya plantillas (`docs/PLAN_RECORDATORIOS_WHATSAPP.md`).
- El alta self-service de WhatsApp sigue limitada al tenant de pruebas
  `metareview` (variable `WHATSAPP_ES_TENANTS`). Conectar el número PROPIO de
  Alicia pasa por añadirla ahí (ver decisión 1).
- **Stripe de Alicia**: cuenta conectada pero `charges_enabled=0`,
  `payouts_enabled=0`, `details_submitted=0` (sin cambios desde el 27-ago). Los
  servicios con señal **se reservan sin cobrarla**. Se retoma después de Meta.

## Piloto de Alicia: comprobado en producción (11-sep)

Leído de la BD de producción, no de los documentos de agosto. Sustituye a las
"preguntas abiertas" de `docs/ALICIA_PENDIENTE.md` donde choquen.

- **Señal**: 53 servicios activos la llevan. **Ninguno de menos de 50 €** (hay 91
  activos por debajo, todos sin señal). La pregunta de agosto sigue igual: es
  decisión de Alicia, no un fallo.
- **Grey blending**: los sueltos de 75/90/105/120 min están desactivados; queda
  activo "Grey blending corto-med" (90 min, 48 €). Packs: corto 370 min, medio
  440, **largo 530, extra largo 495**. Que el largo dure más que el extra largo
  hay que preguntárselo a ella (en agosto ya se vio que el "largo" usa pasos de
  extra largo).
- **Recogidos**: existen y están activos (medio recogido 20 min, con postizo 30,
  recogido con postizo 40, pack maquillaje y recogido 170, pack maquillaje y
  medio recogido 215). No se han revisado los pasos internos de los packs.
- **Equipo**: Alicia tiene **0 servicios asignados a propósito**: lista vacía =
  los hace todos (`agenda._services_for_employee`), y así los servicios nuevos le
  entran solos. No "arreglarlo" poniéndole una lista. Lorena 190, Conchi 193,
  Lucía 108, Jose 108.
- Sin comprobar todavía: horario real de Lucía y Jose, y si Alicia ha probado la
  última versión.

## Decisiones pendientes de Pablo

1. **Alicia con su propio número: LISTO para que lo conecte** (11-sep, comprobado
   en producción). Le sale el botón «Conectar mi WhatsApp» en la pestaña WhatsApp
   de su portal (`WHATSAPP_ES_TENANTS=metareview,alicia_rincon_estilistas` en el
   `.env` del VPS). Al conectar, su configuración pasa sola al número nuevo. Es la
   prueba de que el alta vale para una empresa que no es la nuestra. Después,
   vigilar sus avisos (ver «Avisos de cita de Alicia» arriba) y el punto 2.
2. **Siguiente gran tarea: recordatorios por WhatsApp** (plantillas de Meta). Plan
   para ejecutar tal cual en `docs/PLAN_RECORDATORIOS_WHATSAPP.md`.
3. Decidido (11-sep): **dos apellidos obligatorios** en el panel y también por
   WhatsApp a las clientas nuevas; a las conocidas no se les pide nada.
4. **Anotado para más adelante** (Pablo, 11-sep: "con el resto ya seguiremos"):
   - `scripts/tiktok_autosend.py`: misma clase de riesgo que las automatizaciones
     de Meta que se borraron; ¿se retira?
   - Rotar `WHATSAPP_APP_SECRET` (se imprimió en claro el 9-sep): lo lleva Pablo.
   - Stripe de Alicia sin activar: Pablo se lo pide a ella.
   - Preguntar a Alicia: grey blending "largo" (530 min) dura más que el "extra
     largo" (495); horario real de Lucía y Jose.
   - El formulario de reserva dentro de WhatsApp (Flows) está en borrador y en la
     WABA de Vantelia: en números de otros negocios no sale (sigue por mensajes).
   - Aviso al negocio de un mensaje normal (hoy solo cuando piden persona) y push.
   - Esfuerzo de razonamiento de Astra (con `xhigh` gasta la cuota en una hora).
5. Hecho (11-sep): Pablo aprobó en Codex los hooks de Astra (`~/.codex/hooks.json`,
   desde la terminal: la app de escritorio no tiene `/hooks`).

## Frágil, a vigilar

- El humo da por bueno lo que llega a la agenda, no cómo llega: `corte-acaba-en-cita`
  "pasaba" 6 de 6 con la clienta viendo la lista de horas dos veces, gracias al
  "sí, confirmo" de sobra del guion. Arreglado el fallo (ver «Lo último»), el
  instrumento sigue sin verlo: leer las conversaciones, no solo el veredicto.
- En el catálogo de Alicia conviven "Corte señora" (20 min) y "Corte de señora"
  (15 min), y el asistente coge uno u otro. Preguntarle cuál vale.
- Cualquier sitio donde una lista de frases decide qué quiere decir la clienta.
- La frontera con Meta: un payload mal formado corta la conversación sin error
  visible para nadie; solo sale en los logs del servidor.
- Los fallos de estas semanas NO los encontraron los tests ni el banco: los
  encontró Pablo usando el producto como una clienta. Probar a mano la
  conversación entera sigue siendo imprescindible.


Corrección adicional del 13-sep (validada con pruebas dirigidas): mencionar diagnóstico para
rechazarlo activaba `_pide_la_valoracion`, que además borraba el servicio acumulado.
Se reutiliza el detector compartido de renuncia distinguiendo negativa explícita
de preferencia por reservar directamente. «Quiero diagnóstico directamente» sigue
siendo una petición. La obligatoriedad puede impedir contratar el tratamiento sin
valoración, pero no transforma una negativa en aceptación de cita. Cuatro pruebas
rojas antes del cambio; 77 dirigidos verdes, pyflakes de los módulos tocados y diff limpios. No se modifica
configuración de negocio ni se añade una lista de frases en el canal.


Relevo tras este bloque: retirada Q&A en d42e964 y negativa explícita en su
siguiente commit. No hay suite propia ejecutándose ni revisión formal solicitada.
Claude conserva su encargo; diagnóstico de demos sin entrega recibida al cerrar.
La siguiente puerta de validación del conjunto es resolver esos fallos y pasar
una suite completa, después revisión exacta y banco comparable. Quedan trabajo
independiente de reconciliación/outbox y migración de confirmaciones de gestión;
no confundir estos dos arreglos con haber terminado toda la arquitectura.


Integración 13-sep: 52acab5 une ee939c8 con el candidato moderno; no añade el segundo
validador de retirada ni vuelve a botones genéricos. Nuevo cierre del estado:
`anotar_resultado` invalida selección, duración, profesional, hora y resumen tras
rechazo de crear el servicio vigente. Conserva nombre/fecha y no borra una cita
terminada ni la selección al consultar otra alternativa. Prueba roja antes del
arreglo; 61 dirigidos verdes. Aviso WhatsApp con envío rechazado no se registra.
La nota de Claude sobre widget ya estaba cubierta por da0ca70 y se volvió a probar.

Cola depurada: retirados encargos propios 6bbb04 y 8a476e ya implementados en
antecesor da0ca70. No son aprobaciones. Diagnóstico 04d9a4 reasignado a Astra antes
de lanzarlo aquí; Claude conserva el calendario activo, sin interrumpir su proceso.


Demos, diagnóstico cerrado el 13-sep: el fichero aislado dio 21 verdes. Orden
reducido (demo inicial -> módulo de agenda que recarga backend -> cinco casos)
reprodujo EXACTAMENTE los cinco fallos, con dos controles verdes. No es horario ni
regresión demostrada del agente: la API de fixture de sesión apuntaba a módulos
antiguos, mientras importaciones locales desde outreach usaban el backend nuevo;
se mezclaban registros de demos y los monkeypatch no alcanzaban el constructor.
Fixture api_module local al módulo de demos crea un runtime coherente. El mismo
orden, con TODO el fichero de demos después, da 23 verdes. Solo se modifica el
instrumento; no se toca outreach ni se rebajan las comprobaciones. Suite completa
es la siguiente puerta, seguida de revisión exacta; las métricas reales no se dan
por medidas.
