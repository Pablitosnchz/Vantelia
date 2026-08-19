# Alicia Rincón Estilistas: lo pedido, lo hecho y lo que falta

Estado a 19-ago-2026. Tenant `alicia_rincon_estilistas`.

Este documento existe porque las peticiones llegan por WhatsApp a lo largo del
día y se pierden. Cuando algo se cierra, se borra de aquí.

---

## Hecho y desplegado

- **Franjas horarias en WhatsApp.** Antes solo se veían los 10 primeros huecos
  del día: de 10:00 a 14:30. Ninguna clienta veía las tardes.
- **Sin hueco → que llamen.** El mensaje incluye su teléfono para que el salón
  cuadre lo que el sistema no puede.
- **Orden del equipo**: Alicia, Lorena, Conchi, Lucía, Jose.
- Catálogo de 183 servicios en 11 categorías, 3 profesionales, horarios reales.
- Señal de 50 € en los 53 alisados.

---

## Bloqueado esperando a Alicia

### 1. Los tiempos de espera (lo de más valor)

Un pack de mechas dura 6-7 h, pero **entre pasos la profesional está libre** y
puede atender a otra clienta. Hoy se bloquea el rango entero.

**Cómo va a venir el dato** (acordado con ella el 19-ago): en la hoja
*Servicios*, el tiempo que tarda en **hacer** el servicio; en la hoja *Packs*,
los tiempos de exposición, entendidos como **rato libre para atender a otra**.

Ella avisó de algo que su tabla aún no expresa: *"en un servicio de esos hay
varios tiempos de espera entremedias, no uno solo"*. Pendiente de aclarar en una
llamada.

**Diseño previsto**: un servicio deja de ser un bloque y pasa a ser una secuencia
`activo → espera → activo`. Acotado a un punto: los tramos de espera se guardan
en la cita y `agenda._booked_intervals` —fuente única de "qué está ocupado"— los
descuenta. Vacío = comportamiento actual, así que ningún otro cliente cambia.

**OJO, problema vivo**: los packs están cargados con la duración equivocada. El
importador tomó el "tiempo de exposición" **en lugar de** la duración del
servicio, así que el pack de mechas extra largo figura con 3,6 h cuando ella dice
que son 6-7. Mientras siga así, se le pueden encajar citas encima de un pack.

### 2. La agenda en tramos de 15 minutos

Va después de lo anterior. Es configuración (`slot_minutes`), pero solo tiene
sentido con los huecos de espera liberados.

### 3. Excel nuevo

Lo va a rehacer con el criterio de arriba. Cuando llegue: **16 packs de alta**
(ácido láctico bio premium ×4, color raíz y elumen ×4, elumen ×4, matiz ×4) y
**7 a desactivar** (no borrar: pueden tener citas).

---

## Listo para ejecutar en cuanto llegue el Excel

- **Señal** en ~30 servicios más: todo grey blending (11, ninguno la tiene hoy),
  el resto de mechas (9), cambios de color (6) y decoloraciones (2).
- **Precios ocultos** en mechas, balayage, grey, landing, extensiones y cambios
  de color (91 servicios). Se hace poniendo el precio a "consultar", que el
  sistema ya soporta en todos los canales: cero código.
- **Cita de diagnóstico de 15 min**, gratis y sin compromiso, ofrecida cuando
  pregunten precio de esas familias. El servicio ya existe en su catálogo.
- **Alisados**: si piden cita, se coge preguntando el largo. La foto solo se pide
  si quieren **presupuesto** previo; entonces se responde que el salón contacta,
  se calla el asistente y se avisa al equipo.
- **Extensiones**: nunca precio, siempre cita de diagnóstico presencial.
- **Altas de Lucía y Jose** (falta su horario).

---

## Preguntas abiertas

1. **"Jazz"** no aparece en su tabla. ¿Cómo se llama el servicio?
2. Los packs de **Elumen** (corto, medio, largo, extra largo) están duplicados.
3. Los packs no llevan precio: sale de sumar los pasos. En los de **ácido láctico
   y keratina premium** algún paso va sin precio y quedan "a consultar".
4. **"Grey blending corto" figura con 300 minutos** (5 h). ¿Correcto?
5. **Extensiones**: ¿llevan señal? No las nombró en esa lista.
6. La cita de diagnóstico, ¿la puede dar cualquiera de las tres?

---

## Descartado, y por qué

**Repartir un servicio entre dos profesionales** cuando no hay hueco para una
sola ("si no hay 90 minutos de una, pero sí 45 de dos"). Depende de cómo vaya la
mañana y de si el trabajo se puede partir: lo sabe el equipo, no el sistema.
Automatizarlo mal encaja citas imposibles. Ese caso lo cubre la salida por
teléfono, que ella misma propuso.

---

## Para poder entregarle la demo completa

**Stripe a medias**: su cuenta figura conectada pero sin `charges_enabled`, así
que los servicios con señal **se reservan sin cobrarla**. Es el único bloqueante
que no depende de ella ni de nosotros, sino de terminar el alta con sus datos
fiscales.
