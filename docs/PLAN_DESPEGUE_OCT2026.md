# Plan de despegue · octubre 2026 → enero 2027

Escrito el 04-oct-2026 (Claude, a petición de Pablo). Objetivo: pasar de "producto potente sin
clientes que paguen" a **5 clientes de pago en 90 días**. Se revisa cada lunes (apartado 9).

---

## 1. Diagnóstico (datos de producción, 04-oct)

| Dato | Valor |
| --- | --- |
| Correos fríos desde agosto | ~1.100 → **0 interesados** (los 2 únicos interesados por correo, mayo-junio, llevaban su demo) |
| Llamadas automáticas de Sara (7 días) | 128 → **2 leads reales** (Dental Navarro, IGIN), los dos **clínicas** |
| Clientes firmados | **Cap Rocat** (llegó solo; 400 € + 1.290 €/año; en pruebas) |
| Piloto | **Alicia**: plan Pro sin cobro, **WhatsApp sin conectar, 0 citas del asistente, última conversación el 08-sep** |
| Competencia en España | Recepcionista.com 29 €/mes, Clara Assistant 49,95 €, Sofía IA (Clinicbot) 55 €, BECAI 799 € pago único. Rango 49-300 €/mes |

**Conclusión:** el producto tiene más que la competencia (agenda propia, WhatsApp sin cambiar de
número, voz natural, tiempos de espera de los packs, reglas por palabra clave). Lo que falla es
la **distribución** y la **confianza**: nadie lo prueba porque probarlo cuesta trabajo y no hay
casos de éxito que enseñar. **Este plan no añade funciones sueltas: quita fricción a la prueba y
genera prueba social.**

## 2. Objetivo y métricas

| Métrica | Hoy | 30 días | 90 días |
| --- | --- | --- | --- |
| Clientes de pago | 0 (Cap Rocat en prueba) | 2 (Cap Rocat + Alicia) | **5** |
| Ingresos recurrentes al mes (MRR) | 0 € | ~240 € | ≥ 600 € |
| Leads reales al mes (piden demo o llamada) | ~2 | 6 | 15 |
| Pruebas activas a la vez | 1 | 3 | 5 |
| Coste de captar un cliente | — | < 2 meses de cuota | < 2 meses de cuota |

Fuente de cada cifra: panel "Plan de escala" (tablas `growth_*`) + panel de Captación. Sin
dato registrado no se da por hecho.

## 3. Decisiones que necesita Pablo (bloquean fases)

| # | Decisión | Recomendación | Bloquea |
| --- | --- | --- | --- |
| D1 | Llamadas automáticas en frío de Sara: ¿pausar? (Astra, 29-sep: la AEPD exige consentimiento previo para llamadas comerciales automatizadas, art. 66.1.a LGTel) | **Pausar** y pasar Sara a atender llamadas que ENTRAN (fase 3) | Fase 1 |
| D2 | Foco en **clínicas** (dental, estética, fertilidad) en vez de peluquerías | Sí | Fase 1 |
| D3 | Oferta: 14 días gratis + garantía ("si no recupera X citas al mes, no pagas") | Sí, con X = 5 | Fase 3 |
| D4 | Alicia: ¿cuándo empieza a pagar y qué falta para que lo use? | Activarla ya y cobrar desde la conexión | Fase 0 |
| D5 | Precio del producto de la fase 3 | 79 €/mes solo voz; 129 €/mes voz + WhatsApp | Fase 3 |

## 4. Fase 0 · Esta semana (05-11 oct): lo que ya está en juego

| Tarea | Quién | Hecho cuando |
| --- | --- | --- |
| 0.1 **Activar a Alicia**: llamada con ella para conectar su WhatsApp (Coexistence), revisar que el widget está en su web y acordar desde cuándo paga | Pablo (Claude prepara guion y enlace de alta) | WhatsApp conectado + primera cita del asistente |
| 0.2 **Cap Rocat**: tras su día de pruebas, correo de conexión de WhatsApp y videollamada; al conectar, `scripts/cuota_anual_stripe.py suscribir` | Pablo + Claude | Número en vivo y prueba de 10 días en marcha |
| 0.3 **Leads Dental Navarro e IGIN**: si no responden en 3 días laborables, un segundo correo corto (Claude lo prepara); regenerar demo si caduca | Claude prepara, Pablo aprueba | Respuesta o cierre |
| 0.4 **3.er trimestre** (303 y 130) antes del 20-oct | Pablo con datos, Claude prepara casillas | Presentado |
| 0.5 **D1**: decisión sobre las llamadas automáticas | Pablo | Decidido |
| 0.6 Clínica Dental Tuces (Tarragona) pidió que se le llamara: correo con demo | Claude | Enviado |

## 5. Fase 1 · Semanas 1-2: foco en clínicas y prueba social

1. **Correo frío con demo** (rama `claude/correo-segun-sara`, 386 líneas, tests incluidos): revisión
   de Astra → despliegue. Cambios: el frío lleva la demo hecha con la web del negocio, no escribe
   a quien llama Sara, y a quien Sara no consigue contactar le llega un correo con su demo.
2. **Segmentar** el autopiloto de captación: objetivos solo de clínicas dentales, estética
   avanzada y fertilidad en Madrid y alrededores. Peluquerías en pausa (salvo recomendaciones).
3. **"Llama a Sara y compruébalo"** en cada correo y en la web: el 91 lo coge Sara (ya funciona),
   así el prospecto oye el producto sin pedir nada. Medir llamadas entrantes al 91.
4. **Landing por sector** en vantelia.es: `/clinicas-dentales/` con audio, demo y precio
   (hostinger_site + site_exports + sitemap).
5. **Testimonios**: Cap Rocat al terminar su prueba (hotel de lujo = mucha credibilidad); Alicia
   cuando lo use. Formato: 2-3 frases + dato ("X consultas atendidas fuera de horario").

**Hecho cuando:** correo desplegado, landing publicada, primer testimonio pedido.

## 6. Fase 2 · Semanas 2-4: informe de resultados para cada cliente

Por qué: retiene, justifica la cuota y fabrica casos de éxito sin pedírselos al cliente.

- **Qué**: email automático semanal (lunes) y resumen mensual al dueño del negocio: conversaciones
  atendidas (web, WhatsApp, voz), cuántas fuera de horario, citas creadas por el asistente e
  importe estimado (precio del catálogo), preguntas más repetidas y conversaciones que pidieron
  una persona.
- **De dónde sale**: `chat_sessions`, `voice_calls`, `bookings` (source ≠ portal_manual/demo_seed),
  catálogo de servicios. Todo existe; sin modelo de IA, coste 0.
- **Dónde**: `backend/informes_cliente.py` + el worker de recordatorios (como reseñas y avisos),
  opt-out por negocio (`config['informe']`), plantilla de email por `emailing._send_client_email`.
- **Pruebas**: tests de cálculo (horario del negocio, citas por canal, importe), idempotencia (un
  informe por semana) y aislamiento entre negocios.
- **Primer uso**: Cap Rocat y Alicia. El de Cap Rocat al final de la prueba, como argumento para la
  cuota anual.

**Hecho cuando:** los dos clientes reciben su primer informe.

## 7. Fase 3 · Semanas 3-8: "Solo las llamadas que no coges" (producto de entrada)

**La idea:** el negocio no cambia nada. Activa en su línea el **desvío de llamadas si no contesta o
comunica** hacia un número de Vantelia, y la asistente de voz atiende solo esas llamadas: informa,
da la cita en su agenda y le avisa. Las pymes pierden entre el 20 % y el 40 % de las llamadas, y el
85 % de quien no es atendido no vuelve a llamar.

**Por qué ahora:** quita casi toda la fricción (no hay que conectar WhatsApp ni tocar la web), el
valor se mide desde el día 1 ("47 llamadas que habrías perdido") y es inbound: **cero riesgo legal**,
a diferencia de las llamadas en frío.

**Qué existe ya:** Sara atiende el 91 por SIP (Zadarma → puente Asterisk `sara-puente` →
ElevenLabs); cada negocio tiene ya un agente de voz de teléfono generado de sus fuentes
(`voz_elevenlabs`), con tools reales de agenda (`voice._voice_dispatch_tool`); transcripciones
en Conversaciones.

**Qué falta (técnico):**
1. **Un número de Zadarma por cliente** (+34 geográfico de su provincia) y, en el puente, enrutar
   por número marcado (DID) al agente del negocio en vez de siempre a Sara. Tabla
   número → `cliente_id` en `config['voice']`.
2. **Variables de la llamada desviada**: quien llama (`system__caller_id`) para verificar citas y
   avisar al negocio.
3. **Aviso al negocio** en cada llamada atendida (email/WhatsApp con resumen y si hay cita), y
   en el informe semanal (fase 2).
4. **Guía de desvío por operador** (Movistar, Vodafone, Orange, Digi, centralitas) en el alta:
   desvío si no contesta y si comunica, con prueba guiada.
5. **Panel**: tarjeta "Llamadas atendidas" en el portal del cliente.

**Coste por cliente a medir en el piloto:** número de Zadarma (pocos €/mes) + minutos de
ElevenLabs y modelo de lenguaje (orientativo: ~0,10 €/min). El precio (D5) tiene que dejar
margen con 300 min/mes.

**Piloto:** 2 negocios con interés previo (Dental Navarro / IGIN si responden, o un cliente de
Alicia/Cap Rocat) durante 14 días, gratis, a cambio de testimonio y datos.

**Riesgos:** calidad de audio por SIP (ya medido con Sara), que el desvío no se configure bien
(guía + prueba guiada), coste por minuto con negocios de mucho volumen (tope en el plan),
confusión del paciente al oír una IA (decir que es la asistente virtual de la clínica, art. 50
del Reglamento de IA).

**Hecho cuando:** 2 pilotos en marcha con sus informes y un precio validado.

## 8. Fase 4 · Semanas 6-12: multiplicar

- **Recomendaciones**: cada cliente que traiga otro, un mes gratis (para los dos).
- **Agencias de marketing de clínicas** (2-3 pruebas): comisión recurrente del 20-30 % o marca
  blanca (el panel ya es multi-negocio). Primero una agencia, y solo si cierra clientes se sigue.
- **Repetir lo que funcione** según las métricas del apartado 2.

## 9. Ritmo y seguimiento

- **Lunes**: revisión de 15 min con las cifras del apartado 2 (panel Plan de escala + Captación).
  Claude prepara el resumen, Pablo decide.
- **Cada fase** se cierra con su "hecho cuando"; si no se cumple en plazo, se revisa antes de
  abrir la siguiente.
- Desarrollo como siempre: Claude implementa con tests, Astra revisa, y se despliega solo con
  la suite completa en verde.

## 10. Lo que NO hacemos en estos 90 días

- Funciones nuevas que no estén en este plan (el producto ya va por delante de las ventas).
- Más canales de captación a la vez: primero correo con demo + "llama a Sara" + landing.
- Bajar precios para competir con los de 29 €: competir en resultados (informe y garantía), no
  en precio.
- Llamadas comerciales automatizadas sin resolver D1.
