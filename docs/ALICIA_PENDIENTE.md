# Alicia Rincón Estilistas: lo pedido, lo hecho y lo que falta

Estado a 20-ago-2026. Tenant `alicia_rincon_estilistas`.

Este documento existe porque sus peticiones llegan por WhatsApp a lo largo del
día y se pierden. Cuando algo se cierra, se borra de aquí.

---

## Hecho

### Los tiempos de espera — confirmado por teléfono el 19-ago

Ella lo aclaró en llamada: en la hoja **Servicios** está el tiempo que tarda
**ella en hacer** el servicio; el **tiempo de exposición** de la hoja *Packs* es
el rato que tiene **libre para atender a otra clienta**. (El "No" que había dicho
antes por WhatsApp fue un error suyo.)

Cuadra con sus números: el pack de mechas extra largo son 240 min de trabajo +
155 de espera = 6,6 h, y ella decía "6 o 7 horas".

Un servicio deja de ser un bloque y pasa a ser `activo → espera → activo`. Los
tramos se guardan en `services.gap_json`, se copian a la cita al reservar
(`bookings.gap_json`) y `agenda._booked_intervals` —fuente única de "qué está
ocupado"— devuelve solo los tramos activos. **Sin tramos, todo se comporta igual
que antes**, así que ningún otro cliente cambia.

Sus packs liberan **3,1 h de media** por cita. Con dos packs al día son más de 6
horas de agenda que antes se perdían.

### Lo demás

- **Franjas horarias en WhatsApp.** Antes se mandaban los 10 primeros huecos del
  día: de 10:00 a 14:30. Ninguna clienta veía las tardes.
- **Sin hueco → que llamen**, con su teléfono en el mensaje.
- **Orden del equipo**: Alicia, Lorena, Conchi, Lucía, Jose.
- **El paso de la agenda se aplica a todo el equipo.** Puso "citas de 15 minutos"
  en Horarios, lo cogió la agenda general y sus tres profesionales se quedaron en
  30: como la disponibilidad se calcula por profesional, sus clientas seguían
  viendo huecos de media hora.

---

## Listo, falta aplicarlo a su tenant

Probado importando su Excel en una base de datos aparte: **191 servicios** (186
activos), 11 categorías, 37 con tramos de espera.

- **Importar el catálogo** con packs, tramos, categorías y precios.
- **Señal**: 42 de 73 salen solas de sus filas FIANZA.
- **Precios ocultos** en mechas, balayage, grey, landing, extensiones y cambios
  de color (**82 servicios**). Se hace poniendo el precio a "consultar", que el
  sistema ya soporta en todos los canales: cero código.
- **Quién puede hacer cada servicio**: su columna "Operario" (12 solo Alicia, 48
  las tres, 72 todos). Hoy no está configurado, así que el sistema **puede
  ofrecer a Conchi para algo que solo hace Alicia**. Se aplica con
  `employees.service_ids_json`.
- **Altas de Lucía y Jose** (falta su horario).

---

## Pendiente de código

- **Alisados**: si piden cita, se coge preguntando el largo. La foto solo se pide
  si quieren **presupuesto** previo; entonces se responde que el salón contacta,
  se calla el asistente y se avisa al equipo. Ese aviso al negocio **no existe
  todavía** y sin él la foto se queda esperando a que alguien mire el panel.
- **Extensiones**: nunca precio, siempre cita de diagnóstico presencial.
- **Ofrecer la cita de diagnóstico de 15 min** al preguntar precio de las
  familias de arriba. El servicio ya existe en su catálogo (15 min, gratis).

---

## Preguntas abiertas

1. **Faltan dos filas FIANZA.** Su tabla tiene extensiones (100 €) y
   "mechas-alisados-decoloraciones-balayage-permanente" (50 €), pero por WhatsApp
   añadió **grey blending y cambios de color**: 10 servicios se quedarían sin
   señal. Mejor que las añada ella a su Excel que meterlo a fuego en el código.
2. **"RECOGIDO"**, paso del pack de maquillaje, no existe en su hoja de
   servicios. Es el único de los 41 packs que no casa.
3. **"Pack grey blending largo" sale de 8,8 h** (5,4 trabajando + 3,4 esperando).
   Es el más largo de todos, conviene confirmarlo.
4. **"Jazz"** no aparece en su tabla. ¿Cómo se llama?
5. Los packs de **Elumen** (corto, medio, largo, extra largo) están duplicados.
6. La cita de diagnóstico, ¿la puede dar cualquiera de las tres?

**Ya resuelto**: las extensiones sí llevan señal, y de **100 €** — está en su
propio Excel, no hacía falta preguntarlo.

---

## Descartado, y por qué

**Repartir un servicio entre dos profesionales** cuando no hay hueco para una
sola ("si no hay 90 minutos de una, pero sí 45 de dos"). Depende de cómo vaya la
mañana y de si el trabajo se puede partir: lo sabe el equipo, no el sistema.
Automatizarlo mal encaja citas imposibles. Ese caso lo cubre la salida por
teléfono, que ella misma propuso.

Su columna "Operario" **no** expresa eso: dice quién está capacitada para cada
servicio, que es otra cosa (y esa sí se va a aplicar).

---

## Para poder entregarle la demo completa

**Stripe a medias**: su cuenta figura conectada pero sin `charges_enabled`, así
que los servicios con señal **se reservan sin cobrarla**. Es el único bloqueante
que no depende de ella ni de nosotros, sino de terminar el alta con sus datos
fiscales.
