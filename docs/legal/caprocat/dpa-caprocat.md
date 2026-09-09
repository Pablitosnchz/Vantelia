# Anexo · Acuerdo de Encargado del Tratamiento (DPA)

**Anexo inseparable del Contrato de prestación de servicios SaaS entre Vantelia y Hotel Cap Rocat**

Documento preparado para **Hotel Cap Rocat**. Versión para revisión, 4 de septiembre de 2026.

> Pendiente de revisión por asesoría legal antes de la firma.

Acuerdo suscrito conforme al artículo 28 del Reglamento (UE) 2016/679 (RGPD) y a la Ley Orgánica 3/2018 (LOPDGDD).

---

## 1. Partes

- **Responsable del Tratamiento**: el Cliente identificado en la cláusula 1 del Contrato SaaS (Hotel Cap Rocat).
- **Encargado del Tratamiento**: Pablo Sánchez Sánchez, nombre comercial **Vantelia**, NIF 02751906W, domicilio en Calle Garabay S/N, Portal 7, Planta 2, Puerta C, 28850 Torrejón de Ardoz (Madrid), España. Email: info@vantelia.es

---

## 2. Objeto y finalidad

Vantelia tratará datos personales por cuenta del Cliente **exclusivamente** para prestar el servicio contratado:

- Operar el asistente de IA sobre el canal de WhatsApp del hotel con la información que el Cliente aporte.
- Atender las consultas que los huéspedes y potenciales huéspedes envíen a ese número.
- Conservar el historial de esas conversaciones para que el equipo del hotel pueda consultarlo, intervenir en ellas y auditarlas.

Vantelia **no** utiliza los datos del Cliente ni de sus huéspedes para ninguna finalidad propia, ni para entrenar modelos de inteligencia artificial, ni los cede a terceros distintos de los subencargados de la cláusula 8.

---

## 3. Categorías de interesados

- Personal del hotel con acceso al panel de Vantelia.
- Huéspedes y potenciales huéspedes que escriben al WhatsApp del hotel.

---

## 4. Categorías de datos tratados

- **Datos identificativos y de contacto**: nombre facilitado en la conversación, número de teléfono desde el que escriben y, si lo aportan, email.
- **Contenido de las conversaciones** mantenidas con el asistente o con el equipo del hotel a través del panel.
- **Datos de la cuenta del panel**: nombre, email y credenciales del personal del hotel.

**No se tratan**, dado el alcance contratado: datos de pago, datos de reserva procedentes del PMS del hotel, ni grabaciones de voz.

El Cliente se compromete a no introducir en el asistente datos de categorías especiales del artículo 9 del RGPD (salud, entre otros) sin acuerdo escrito previo.

---

## 5. Duración

El tratamiento se mantiene mientras esté vigente el Contrato SaaS. A su finalización se aplica la cláusula 11.

---

## 6. Obligaciones de Vantelia (Encargado)

a) Tratar los datos únicamente siguiendo instrucciones documentadas del Cliente. Este DPA y el Contrato constituyen esas instrucciones.

b) Informar al Cliente si, a su juicio, una instrucción infringe el RGPD.

c) Garantizar que las personas autorizadas a tratar los datos se han comprometido a la confidencialidad.

d) Aplicar las medidas técnicas y organizativas de la cláusula 9.

e) No incorporar subencargados distintos de los de la cláusula 8 sin informar al Cliente con **30 días de antelación**, plazo en el que el Cliente podrá oponerse y, si la oposición no puede resolverse, resolver el Contrato sin penalización.

f) Asistir al Cliente en la respuesta a las solicitudes de derechos de los interesados (acceso, rectificación, supresión, oposición, limitación y portabilidad).

g) Asistir al Cliente en las evaluaciones de impacto y consultas previas que procedan.

h) Notificar al Cliente cualquier violación de la seguridad de los datos **sin demora indebida y, en todo caso, en menos de 72 horas** desde que tenga conocimiento, con la información necesaria para que el Cliente cumpla su propia obligación de notificación.

i) Poner a disposición del Cliente la información necesaria para demostrar el cumplimiento de este acuerdo.

j) A la finalización, devolver o suprimir los datos según la cláusula 11.

---

## 7. Obligaciones del Cliente (Responsable)

a) Determinar las finalidades y los medios del tratamiento.

b) Disponer de la base jurídica adecuada para el tratamiento de los datos de sus huéspedes.

c) **Informar a los interesados** de que la atención por WhatsApp se presta mediante un asistente automatizado operado por un encargado externo, y de la existencia de un historial de conversaciones. Vantelia puede facilitar un texto tipo para su política de privacidad y para un mensaje de aviso en el propio canal.

d) No introducir en el asistente datos de categorías especiales sin acuerdo previo.

e) Atender las solicitudes de derechos de sus huéspedes. Vantelia colabora, pero el responsable es el Cliente.

f) Mantener la confidencialidad de las credenciales del panel.

---

## 8. Subencargados autorizados

El Cliente autoriza expresamente a los siguientes subencargados, necesarios para prestar el servicio contratado:

| Subencargado | Servicio que presta | Ubicación del tratamiento |
|---|---|---|
| Hostinger International Ltd. | Alojamiento del servidor y de la base de datos | **Unión Europea (Francia)** |
| OpenAI Ireland Ltd. | Modelo de lenguaje que genera las respuestas | UE / EE. UU. (EU-US Data Privacy Framework) |
| Meta Platforms Ireland Ltd. | WhatsApp Cloud API (transporte de los mensajes) | UE / EE. UU. (EU-US Data Privacy Framework) |
| Proveedor de correo transaccional (Hostinger) | Avisos del panel y recuperación de contraseña | Unión Europea |

No intervienen pasarelas de pago ni proveedores de telefonía, por no estar contratados esos módulos.

**Nota sobre WhatsApp.** El canal es de Meta y la relación del hotel con Meta es directa e independiente de este acuerdo. Los mensajes existen además en la aplicación de WhatsApp Business del propio hotel (modo Coexistence), fuera del ámbito de control de Vantelia.

---

## 9. Medidas técnicas y organizativas

- Cifrado en tránsito (TLS 1.2 o superior) y HTTPS obligatorio.
- Servidor alojado en infraestructura europea (Francia).
- Acceso al panel con usuario y contraseña, política de robustez y bloqueo tras intentos fallidos.
- Roles diferenciados y permisos por acción, con principio de mínimo privilegio.
- Tokens de sesión firmados y con expiración automática.
- Validación de firma HMAC SHA-256 en los webhooks entrantes de WhatsApp; se rechaza todo mensaje no firmado.
- Credenciales de terceros almacenadas cifradas.
- **Aislamiento por cliente**: cada cliente dispone de su propia base de conocimiento y todas las consultas se filtran por su identificador. Ningún otro cliente de Vantelia puede acceder a sus datos.
- Copias de seguridad diarias automatizadas, con retención y verificación.
- Registro de auditoría de las acciones críticas y de los accesos administrativos.
- Actualización regular de dependencias y revisión de vulnerabilidades.

Las medidas se revisan periódicamente y se refuerzan conforme al estado de la técnica y a los riesgos.

---

## 10. Transferencias internacionales

OpenAI y Meta pueden tratar datos en EE. UU. al amparo del **EU-US Data Privacy Framework**, decisión de adecuación de la Comisión Europea. Si esa decisión fuera revocada o anulada, Vantelia adoptará mecanismos alternativos (cláusulas contractuales tipo y evaluación de impacto de la transferencia) o sustituirá al subencargado afectado, informando al Cliente.

---

## 11. Solicitudes de autoridades públicas

Vantelia no comunica datos personales a autoridades públicas salvo obligación legal exigible. Ante una solicitud: comprueba su legalidad y la competencia de quien la emite; la impugna o pide aclaración si carece de base suficiente; entrega **únicamente** el dato concreto exigido para el periodo exigido, nunca volcados completos; documenta por escrito cada solicitud y su respuesta; y avisa al Cliente sin demora, salvo prohibición legal expresa.

A la fecha de esta versión, Vantelia **no ha recibido ni atendido** ninguna solicitud de este tipo.

---

## 12. Conservación y final del tratamiento

Durante la vigencia del contrato, las conversaciones y los datos asociados se conservan para que el hotel pueda consultarlos. El Cliente puede solicitar en cualquier momento la supresión de conversaciones concretas o de todo el histórico.

A la finalización del Contrato, y según lo que el Cliente comunique por escrito en los 15 días siguientes:

a) **Devolución**: Vantelia exporta los datos en formato estándar (JSON o CSV) y los entrega al Cliente.

b) **Supresión**: Vantelia elimina los datos en los 30 días siguientes, incluidas las copias de seguridad conforme se rotan. Se exceptúan los registros que la ley obligue a conservar (facturación y obligaciones tributarias), que quedarán bloqueados durante el plazo legal.

Si el Cliente no se pronuncia en esos 15 días, se aplicará por defecto la supresión.

---

## 13. Auditoría

El Cliente podrá solicitar evidencias razonables del cumplimiento de este acuerdo mediante cuestionarios o informes. Las auditorías presenciales requerirán causa justificada, preaviso de 30 días y correrán a cargo del Cliente, salvo que se acredite un incumplimiento grave imputable a Vantelia.

---

## 14. Responsabilidad

Cada parte responde de las sanciones derivadas de su propio incumplimiento. La responsabilidad agregada se rige por la cláusula 12 del Contrato SaaS.

---

## 15. Vigencia

Este DPA entra en vigor con la firma del Contrato SaaS y se mantiene mientras dure la prestación del servicio.

---

## 16. Contacto

Encargado: Vantelia · info@vantelia.es

---

**Firmas**

Por el Cliente (Responsable del Tratamiento)

Nombre: ________________________  Cargo: ________________  Fecha: __________

Firma:


Por Vantelia (Encargado del Tratamiento)

Nombre: Pablo Sánchez Sánchez  Fecha: __________

Firma:
