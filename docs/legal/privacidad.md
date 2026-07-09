# Politica de privacidad

Ultima actualizacion: 2 de mayo de 2026.

Esta politica describe como Vantelia trata los datos personales en su plataforma (`https://www.vantelia.es` y `https://app.vantelia.es`). Plantilla operativa; debe revisarse con asesoria legal antes de publicarse como version definitiva.

---

## 1. Responsable del tratamiento

- **Vantelia** (razon social y CIF a completar antes de la version final).
- Domicilio social: Calle Garabay.
- Email: privacidad@vantelia.es
- Web: https://www.vantelia.es
- Contacto soporte: soporte@vantelia.es

---

## 2. Cuando Vantelia actua como Responsable y cuando como Encargado

- **Responsable**: cuando trata datos de personas que se comunican directamente con Vantelia (formulario de consultas en `vantelia.es`, contratacion del servicio, soporte, marketing propio).
- **Encargado del Tratamiento**: cuando trata datos de los clientes finales de las empresas que han contratado Vantelia (mensajes al asistente IA, reservas, conversaciones WhatsApp del cliente B2B). En estos casos, el Responsable es la empresa cliente y la relacion se rige por el **Acuerdo de Encargado de Tratamiento (DPA)**.

Si quieres ejercer derechos sobre datos tratados a traves de un asistente Vantelia integrado en la web o WhatsApp de una empresa, escribe primero a esa empresa. Vantelia colabora con ella en la respuesta.

---

## 3. Datos que podemos tratar

Como Responsable:

- Datos identificativos y de contacto: nombre, email, telefono, empresa.
- Datos de la cuenta del portal: usuario, contrasena cifrada, rol, ultima conexion.
- Datos de facturacion: razon social, CIF, direccion fiscal, metodo de pago (gestionado por Stripe; Vantelia no almacena el numero completo de tarjeta).
- Datos de soporte: mensajes intercambiados.
- Datos tecnicos: IP, identificadores de sesion, user agent.

Como Encargado, en nombre del cliente B2B:

- Datos identificativos y de contacto del cliente final.
- Contenido de las conversaciones con el asistente.
- Datos de cita: fecha, hora, servicio, profesional, notas.
- Metadatos de WhatsApp.
- Datos tecnicos de conexion.

---

## 4. Finalidades

- Prestar y mantener el servicio contratado.
- Atender consultas comerciales.
- Gestionar la facturacion y el cobro.
- Cumplir obligaciones legales (fiscales, contables).
- Garantizar la seguridad de la plataforma.
- Mejorar el servicio mediante metricas anonimizadas.

No usamos los datos para tomar decisiones automatizadas con efectos juridicos sobre las personas. No vendemos los datos a terceros.

---

## 5. Base juridica

- **Ejecucion de contrato** o medidas precontractuales: para prestar el servicio a clientes y atender consultas.
- **Cumplimiento legal**: facturacion, contabilidad, seguridad.
- **Interes legitimo**: prevencion de fraude, seguridad, mejora del servicio mediante datos anonimizados.
- **Consentimiento**: comunicaciones comerciales, cookies no esenciales.

---

## 6. Conservacion

- Datos de cuenta y facturacion: durante la vigencia del servicio + plazos legales tributarios (6 anos).
- Conversaciones del asistente: durante la vigencia del servicio para el cliente B2B; tras finalizacion, segun clausula 11 del DPA (devolucion o supresion en 30 dias).
- Datos de consultas comerciales no contratadas: maximo 12 meses.
- Logs tecnicos: maximo 90 dias salvo investigacion de incidente.
- Copias de seguridad: rotacion configurada; se elimina dentro del ciclo de retencion del backup.

---

## 7. Destinatarios y subencargados

Vantelia comparte datos solo con proveedores estrictamente necesarios:

- **OpenAI Ireland Ltd.** — modelo de IA (UE/EE.UU. bajo Data Privacy Framework).
- **Hostinger International Ltd.** — hosting y email transaccional (UE).
- **Meta Platforms Ireland Ltd.** — WhatsApp Cloud API (UE/EE.UU. bajo DPF).
- **Google Ireland Ltd.** — envio de correos via Gmail API, solo cuando el cliente conecta voluntariamente su cuenta de Google (UE/EE.UU. con clausulas contractuales tipo).
- **Stripe Payments Europe Ltd.** — pasarela de pago (UE).

La lista completa y actualizada se mantiene en el DPA firmado con cada cliente B2B.

No realizamos transferencias internacionales fuera de las cubiertas por el Data Privacy Framework o por clausulas contractuales tipo aprobadas por la Comision Europea.

---

## 7 bis. Datos obtenidos a traves de las APIs de Google (Gmail API)

Vantelia ofrece, de forma opcional, que un cliente conecte su propia cuenta de Google para que el asistente envie en su nombre correos operativos (confirmaciones de reserva, recordatorios, notificaciones). Para ello solicitamos exclusivamente el permiso `https://www.googleapis.com/auth/gmail.send`, que solo permite **enviar** mensajes; no da acceso a leer, modificar ni eliminar el contenido del buzon.

**Que datos de Google tratamos:** la direccion de correo de la cuenta conectada, los tokens de acceso/actualizacion de OAuth (almacenados **cifrados**, Fernet/AES-256) y los datos minimos necesarios para entregar el correo saliente (destinatario, asunto y cuerpo que el propio negocio genera). Puedes desconectar la cuenta en cualquier momento; al hacerlo, Vantelia revoca el token en Google y elimina la copia local.

**Con quien compartimos los datos de Google:** Vantelia **no comparte, transfiere ni divulga** a terceros los datos de usuario de Google obtenidos via Gmail API, salvo lo estrictamente necesario para prestar la propia funcion de envio (transmision del correo a traves de la infraestructura de Google), cuando la ley lo exija o con tu consentimiento explicito. **No** vendemos estos datos, **no** los usamos con fines publicitarios, **no** los empleamos para entrenar modelos de IA y **no** permitimos que personas los lean, salvo en los supuestos que la propia politica de Google autoriza.

**Compromiso de Uso Limitado (Limited Use):** el uso y la transferencia por parte de Vantelia de la informacion recibida de las APIs de Google se ajustaran a la [Politica de Datos de Usuario de los Servicios de la API de Google](https://developers.google.com/terms/api-services-user-data-policy), incluidos sus requisitos de Uso Limitado.

> Vantelia's use and transfer to any other app of information received from Google APIs will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

---

## 8. Derechos

Puedes ejercer los derechos de:

- Acceso a tus datos.
- Rectificacion.
- Supresion ("derecho al olvido").
- Oposicion al tratamiento.
- Limitacion del tratamiento.
- Portabilidad.
- Retirada del consentimiento cuando aplique.

Como ejercerlos:

- Escribe a `privacidad@vantelia.es` indicando el derecho que ejerces y adjuntando documento que acredite tu identidad.
- Plazo de respuesta: maximo 1 mes (prorrogable a 2 meses en casos complejos).
- Tambien puedes reclamar ante la **Agencia Espanola de Proteccion de Datos** (https://www.aepd.es).

---

## 9. Cookies

Cookies tecnicas necesarias para el funcionamiento del portal y del widget. Cookies analiticas y de marketing solo con tu consentimiento. Detalle en `https://www.vantelia.es/legal/cookies/`.

---

## 10. Inteligencia artificial

El asistente puede generar respuestas usando modelos de IA. La calidad de la respuesta depende de la informacion configurada por la empresa cliente. **Las respuestas no deben utilizarse para decisiones criticas sin revision humana**, especialmente en sectores regulados (medico, legal, financiero).

Detalle en `https://www.vantelia.es/legal/ia-responsable/`.

---

## 11. Seguridad

Cifrado en transito, control de acceso por roles, auditoria de acciones, copias diarias, validacion de origen y firma en webhooks externos. Mas detalle en la clausula 9 del DPA.

En caso de brecha de seguridad con riesgo para los derechos de los interesados, la notificaremos a la AEPD en menos de 72h y, cuando proceda, a los afectados.

---

## 12. Cambios

Cualquier cambio relevante se comunicara con al menos 30 dias de antelacion por email a las cuentas activas y en este mismo documento.

---

## 13. Contacto

- privacidad@vantelia.es — proteccion de datos.
- soporte@vantelia.es — incidencias tecnicas.
