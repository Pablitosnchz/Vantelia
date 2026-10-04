# Plan de captación: 5 clientes de pago

Escrito el 05-oct-2026 (Claude, a petición de Pablo). Complementa a
[PLAN_DESPEGUE_OCT2026.md](PLAN_DESPEGUE_OCT2026.md): aquel ordena el negocio; este, **solo cómo
conseguir clientes**. Restricción de Pablo: **gastar lo mínimo** (canales gratuitos primero).

---

## 1. Qué nos dicen los datos (captación, 05-oct)

| Canal | Volumen | Resultado |
| --- | --- | --- |
| Correo frío (cold + 3 seguimientos) | 534 negocios, 1.853 envíos | 342 abren (64 %, inflado por Apple), **35 hacen clic (6,5 %)**, 7 responden, 20 con intención de respuesta. **0 clientes** |
| Demos generadas al abrir | 32 | **2** las usaron |
| Sara llamando en frío | ~170 llamadas | **2 leads reales** (Dental Navarro, IGIN), los dos clínicas |
| Entrante (vienen solos) | — | **Cap Rocat** (cliente firmado) |
| Por sector (correo) | | **Fisioterapia, el mejor**: 51 contactados, 3 clics, 3 respuestas. Clínicas dentales: abren pero no hacen clic. Peluquerías: casi nada |

**Lectura:**
1. El correo se abre pero **no da motivos para actuar**: el clic hacia la demo es demasiado pedir.
2. **El teléfono funciona mejor que el correo** con las clínicas, pero las llamadas automáticas
   tienen riesgo legal (decisión D1 del plan de despegue).
3. **Hay una bolsa sin trabajar**: 19 "engaged", 35 que hicieron clic, 20 con intención de
   responder. Nadie les ha escrito a mano.
4. Los clientes que hay llegaron **por confianza** (vinieron solos o por relación), no por volumen.

## 2. El embudo que necesitamos

Para cerrar 5 clientes, con lo que se ve en el sector (de cada 4-5 demos guiadas sale ~1 cliente):

```
~120 contactos con interés  →  ~25 conversaciones  →  ~12 demos guiadas  →  5 clientes
```

Una **demo guiada** = 15 minutos (videollamada o en persona) en la que el dueño ve SU asistente
contestando con SUS datos. Es el paso que hoy no estamos dando: mandamos la demo y esperamos.

## 3. Los canales, por prioridad

### A. Calentar lo que ya tenemos (coste 0, empieza ya) ⭐⭐⭐

| Acción | Detalle | Quién |
| --- | --- | --- |
| A1. Leads de Sara | Dental Navarro e IGIN (correo enviado el 04-oct): segundo toque a los 3 días laborables; Clínica Dental Tuces: correo con demo | Claude prepara, Pablo aprueba |
| A2. La bolsa de interesados | Filtrar los ~60 que hicieron clic, respondieron o tienen intención de responder y son del público objetivo (clínicas, fisio, estética, spa; fuera consultoras IT, notarías, etc.). Correo **personal y corto**, uno a uno, con su demo y pidiendo 15 minutos | Claude redacta uno por uno, Pablo envía |
| A3. Cap Rocat y Alicia | Al terminar la prueba de Cap Rocat: testimonio y "¿conoces a otro hotel?". Alicia: activarla primero (plan de despegue, fase 0) | Pablo |

Objetivo: **5-8 conversaciones y 2-3 demos guiadas** en 2 semanas.

### B. Correo frío rediseñado (coste 0) ⭐⭐⭐

1. **Solo el público que responde**: fisioterapia, clínicas de estética, dentales, spa y
   fertilidad, en Madrid y alrededores. Fuera peluquerías (de momento) y sectores sin citas.
2. **Pedir una respuesta, no un clic**: el CTA pasa de "mira tu demo" a "¿te la enseño en 15
   minutos?" o "responde SÍ y te mando el audio de tu recepcionista contestando". Responder cuesta
   menos que hacer clic y llega al buzón como conversación.
3. **Prueba que se oye**: "Llama ahora al 91 993 43 21 y habla con Sara": el producto se
   demuestra solo, sin formularios. Medir las llamadas que entran.
4. **La demo con su web, ya generada** (rama `claude/correo-segun-sara`, lista y con tests):
   revisión de Astra → despliegue.
5. **Prueba A/B de un solo cambio cada vez** (los asuntos ya tienen A/B): primero el CTA de
   respuesta frente al de clic. Mínimo 100 envíos por variante antes de decidir.

Objetivo: pasar del 6,5 % de clic a **≥ 3 % de respuestas positivas**.

### C. En persona en el corredor del Henares y Madrid (coste: transporte) ⭐⭐⭐

Es lo más eficaz con pymes locales y lo menos usado. Pablo vive en Torrejón.

- **Ruta semanal**: 10-15 clínicas, fisios y centros de estética por mañana (Torrejón, Alcalá,
  Coslada, San Fernando, Madrid este). Entrar a una hora tranquila, pedir 2 minutos con la
  responsable y enseñar **su** demo en el móvil (preparada la víspera con su web: Claude genera la
  lista y las demos).
- **Gancho**: "¿Cuántas llamadas se os escapan cuando estáis con un paciente? Mire, esta es su
  recepcionista contestando ahora mismo con sus horarios y servicios".
- **Seguimiento**: correo esa misma tarde con la demo y el enlace para probarlo.

Objetivo: **20 visitas a la semana → 4-6 demos guiadas**.

### D. Eventos sectoriales en Madrid (coste: entrada) ⭐⭐

| Evento | Fecha | Por qué |
| --- | --- | --- |
| VI Congreso de Fisioterapia de la Región Europea (AEF), IFEMA Palacio Municipal | **5-6 nov 2026** | ~1.800 fisios; el sector que mejor responde. Ir de visitante, con demo en el móvil y tarjetas |
| LOOK Madrid (estética, peluquería), IFEMA | **13-15 nov 2026** | Dueños de centros de estética y spas. Visitante |

Preparación: lista de expositores y asistentes que encajan, 10 demos preparadas de antemano,
tarjeta con un QR a "habla con tu recepcionista IA" (el 91 de Sara).

### E. Socios que traen clientes (coste: comisión) ⭐⭐ (a medio plazo)

- **Agencias de marketing de clínicas**: ya hay 11 agencias en la base de captación (3 hicieron
  clic). Oferta: 20 % recurrente por cliente que traigan, o marca blanca con su logo (el panel ya
  es multi-negocio).
- **Recomendaciones de clientes**: un mes gratis para el que recomienda y para el nuevo.
- Más adelante: asociaciones o colegios profesionales (fisioterapeutas de Madrid), con una charla
  o un artículo sobre "llamadas perdidas".

### F. LinkedIn (coste 0, lento) ⭐

Perfil de Pablo como "el de las recepcionistas IA para clínicas": 1 publicación por semana con un
audio o caso real. Conexiones manuales con dueños de clínicas y agencias. Es un apoyo a A-E, no
un canal principal.

### Lo que NO hacemos (y por qué)

- **Anuncios de Google o Meta**: el clic cuesta 1-5 € en España y sin casos de éxito convierte
  mal. Solo cuando haya 2-3 clientes con testimonio, y con una prueba de ≤ 100 €.
- **Kit Digital**: no hay convocatorias abiertas para nuevos bonos en 2026. Vigilar por si se
  abre una (para hacerse agente digitalizador).
- **Automatizar Instagram o WhatsApp**: riesgo de perder la cuenta de Meta de la que depende el
  producto (lección del 9-sep).
- **Llamadas en frío automáticas** sin resolver la decisión D1.

## 4. La oferta (igual en todos los canales)

- **Demo guiada de 15 minutos** con SU asistente ya montado: es el paso que cierra.
- **Prueba de 14 días sin coste ni permanencia**, montada por nosotros.
- **Garantía** (decisión D3): si en el primer mes no recupera al menos 5 citas, no paga.
- **Precio**: el de la web. No bajar a 29 € para competir: se compite en resultados.

## 5. Calendario

| Semana | Foco | Entregables |
| --- | --- | --- |
| 1 (6-12 oct) | A + preparar B y C | Segundos toques a leads, 60 correos personales a la bolsa, rama `correo-segun-sara` revisada y desplegada, lista de 40 clínicas o fisios locales con sus demos |
| 2 (13-19 oct) | C + B | Primera ruta en persona (20 visitas), nuevo correo frío (CTA de respuesta) a fisio y estética |
| 3-4 (20 oct - 2 nov) | C + B + E | Dos rutas más; contacto con 3 agencias; preparar congreso de fisio |
| 5-6 (3-16 nov) | D | Congreso de Fisioterapia (5-6 nov) y LOOK (13-15 nov) con demos preparadas; seguimiento a todos los contactos en 48 h |
| 7-12 (nov - dic) | Repetir lo que funcione | Doblar el canal que más demos guiadas dé; cerrar pruebas → clientes |

## 6. Métricas (cada lunes)

| Métrica | Objetivo semanal |
| --- | --- |
| Contactos con interés nuevos (respuesta, visita o evento) | 10-15 |
| Demos guiadas hechas | 2-3 |
| Pruebas activas | sumar 1 cada 1-2 semanas |
| Clientes de pago | 5 en 12 semanas |

Se apuntan en el panel **Plan de escala** (oportunidades y su estado). Lo que no esté apuntado
no cuenta. Si un canal no da ninguna demo guiada en 3 semanas, se deja.

## 7. Qué hace cada uno

- **Claude**: listas de prospectos, demos preparadas, borradores personales, despliegues,
  métricas del lunes, materiales (página de clínicas, tarjeta con QR, guion de visita).
- **Pablo**: aprobar y enviar los correos personales, visitas, eventos, demos guiadas y cierres.
- **Astra**: revisión de los cambios de código antes de desplegarlos.
