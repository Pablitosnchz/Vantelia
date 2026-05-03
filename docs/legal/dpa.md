# Acuerdo de Encargado de Tratamiento (DPA)

**Anexo al Contrato de prestacion de servicios SaaS de Vantelia**

Plantilla operativa. Debe revisarse con asesoria legal antes de firmar version definitiva.

Ultima actualizacion: 2 de mayo de 2026.

---

## 1. Partes

- **Responsable del Tratamiento**: el Cliente que contrata el servicio Vantelia.
- **Encargado del Tratamiento**: Vantelia (domicilio social: Calle Garabay; razon social y CIF completos en el Contrato SaaS).

---

## 2. Objeto y alcance

Vantelia tratara datos personales por cuenta del Cliente exclusivamente para prestar el servicio contratado:

- Operar el asistente de IA con la informacion del Cliente.
- Atender consultas de los clientes finales del Cliente a traves del widget web y de WhatsApp.
- Gestionar reservas, recordatorios y comunicaciones transaccionales.
- Almacenar el historial de conversaciones para auditoria y mejora del servicio.

---

## 3. Categorias de interesados

- Personal del Cliente con acceso al portal Vantelia.
- Clientes finales del Cliente que interactuan con el asistente (web, WhatsApp, formularios de cita).

---

## 4. Categorias de datos

- Datos identificativos: nombre, email, telefono.
- Datos de contacto y agenda: fecha y hora de cita, servicio solicitado, profesional asignado, notas.
- Contenido de las conversaciones con el asistente.
- Datos tecnicos: IP, identificadores de sesion, user agent.
- Metadatos de WhatsApp (numero, identificadores Meta, estado de entrega).

Vantelia **no tratara** categorias especiales del articulo 9 RGPD (salud, ideologia, datos biometricos, etc.) salvo acuerdo escrito previo y activacion de medidas adicionales.

---

## 5. Duracion

El tratamiento se realizara durante la vigencia del Contrato SaaS. A su finalizacion, Vantelia procedera segun la clausula 11.

---

## 6. Obligaciones de Vantelia (Encargado)

a) Tratar los datos solo segun instrucciones documentadas del Cliente o las recogidas en este DPA.

b) Garantizar que las personas autorizadas a tratar los datos se comprometen a la confidencialidad o estan sujetas a obligacion legal de confidencialidad.

c) Aplicar las medidas tecnicas y organizativas adecuadas (seccion 9 de este DPA).

d) Asistir al Cliente en la respuesta a solicitudes de ejercicio de derechos por interesados (acceso, rectificacion, supresion, oposicion, limitacion, portabilidad).

e) Asistir al Cliente en el cumplimiento de los articulos 32 a 36 del RGPD (seguridad, notificacion de brechas, evaluacion de impacto).

f) Notificar al Cliente cualquier brecha de seguridad sin dilacion indebida y, en cualquier caso, en menos de 72h desde la deteccion.

g) Poner a disposicion del Cliente la informacion necesaria para demostrar el cumplimiento del articulo 28 RGPD y permitir auditorias razonables.

h) Devolver o suprimir los datos al final del servicio segun la clausula 11.

i) No comunicar datos a terceros salvo a los subencargados autorizados (clausula 8) o por obligacion legal.

---

## 7. Obligaciones del Cliente (Responsable)

a) Determinar las finalidades y medios del tratamiento.

b) Disponer de la base juridica adecuada y de las autorizaciones necesarias de los interesados (consentimiento, ejecucion de contrato, interes legitimo, etc.).

c) Informar a sus interesados de que sus datos seran tratados por Vantelia como Encargado.

d) No subir al cerebro del asistente datos especialmente sensibles sin acuerdo previo.

e) Atender las solicitudes de derechos de sus interesados; Vantelia colabora pero el responsable es el Cliente.

---

## 8. Subencargados

El Cliente autoriza expresamente a Vantelia a contar con los siguientes subencargados, necesarios para prestar el servicio:

| Subencargado | Servicio | Pais / region |
|---|---|---|
| OpenAI Ireland Ltd. | Modelo de IA | UE / EE.UU. (DPF) |
| Hostinger International Ltd. | Hosting VPS | UE |
| Meta Platforms Ireland Ltd. | WhatsApp Cloud API | UE / EE.UU. (DPF) |
| Stripe Payments Europe Ltd. | Pasarela de pago | UE |
| Hostinger SMTP / proveedor SMTP | Email transaccional | UE |

Cualquier alta o cambio de subencargado se comunicara al Cliente con al menos 15 dias de antelacion. El Cliente podra oponerse fundadamente; en caso de no acuerdo, podra rescindir el contrato sin penalizacion.

---

## 9. Medidas tecnicas y organizativas

Vantelia aplica al menos las siguientes medidas:

- Cifrado en transito (TLS 1.2+).
- Acceso al panel mediante usuario y contrasena con politica de robustez y bloqueo tras intentos fallidos.
- Roles diferenciados (admin vs operador) y principio de minimo privilegio.
- Tokens de sesion firmados, expiracion automatica.
- Validacion de origen y de firma en webhooks (HMAC SHA-256 para WhatsApp y Stripe).
- Copias de seguridad diarias automatizadas, con retencion configurada.
- Registro de auditoria de acciones criticas (creacion, cambio y cancelacion de citas, accesos admin).
- Aislamiento por cliente: cada cliente tiene su propio cerebro, indices y filtrado por `cliente_id` en todas las consultas.
- Servidor en infraestructura europea con HTTPS obligatorio.
- Politica de actualizacion regular de dependencias y revision de vulnerabilidades.

Las medidas se revisaran periodicamente y se reforzaran segun el estado de la tecnica y los riesgos.

---

## 10. Transferencias internacionales

OpenAI y Meta tratan datos en EE.UU. al amparo del **EU-US Data Privacy Framework**, certificacion validada por la Comision Europea. En caso de revocacion del DPF, Vantelia adoptara mecanismos alternativos (clausulas contractuales tipo, evaluaciones de transferencia) o sustituira al subencargado.

---

## 11. Final del tratamiento

A la finalizacion del Contrato SaaS, a eleccion del Cliente comunicada por escrito en los 15 dias posteriores:

a) **Devolucion**: Vantelia exporta los datos del Cliente en formato estandar (JSON o CSV) y los envia al Cliente.

b) **Supresion**: Vantelia elimina los datos en los 30 dias siguientes, incluyendo copias de seguridad rotadas. Excepcion: registros que la ley obligue a conservar (facturacion, tributario), que se mantendran bloqueados durante el plazo legal.

Si el Cliente no responde en los 15 dias, se aplicara por defecto la opcion de supresion.

---

## 12. Auditoria

El Cliente podra solicitar evidencias razonables del cumplimiento del DPA mediante cuestionarios o informes. Auditorias en sitio solo en caso justificado, con preaviso de 30 dias y a cargo del Cliente, salvo que se descubra incumplimiento grave imputable a Vantelia.

---

## 13. Responsabilidad

Cada parte respondera de las sanciones que le correspondan por su propio incumplimiento. La responsabilidad agregada sigue lo establecido en la clausula 10 del Contrato SaaS.

---

## 14. Vigencia

Este DPA entra en vigor con la firma del Contrato SaaS y se mantiene durante toda la prestacion del servicio.

---

## 15. Contacto del Encargado

Email: privacidad@vantelia.es
Web: https://www.vantelia.es

---

**Firmas**

Por el Cliente (Responsable):
Nombre: ________________________  Fecha: __________  Firma:

Por Vantelia (Encargado):
Nombre: ________________________  Fecha: __________  Firma:
