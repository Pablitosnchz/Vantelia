# Funcionalidades de Vantelia

Vantelia es una plataforma para crear asistentes de IA personalizados para empresas, integrarlos en sus webs y convertir conversaciones en oportunidades reales: citas, leads, recomendaciones, diagnósticos, presupuestos iniciales y seguimiento comercial.

## 1. Asistente IA para la web

Cada empresa puede tener su propio asistente embebido en la web mediante un snippet.

Funcionalidades principales:

- Responde preguntas sobre la empresa, servicios, horarios, ubicación, precios y condiciones.
- Usa un cerebro propio por cliente basado en `info.txt`.
- Mantiene el tono, límites e instrucciones definidos para cada negocio.
- Controla dominios autorizados para evitar uso indebido del widget.
- Puede mostrar un formulario de cita cuando detecta intención de reservar.
- Se adapta visualmente a la marca: nombre, color, icono y bienvenida.

## 2. Diagnóstico Inteligente

La IA puede actuar como guía inicial para entender el caso del usuario.

Ejemplos:

- Una clínica puede orientar sobre qué tratamiento podría encajar.
- Una agencia puede detectar qué automatización necesita una empresa.
- Una academia puede recomendar qué curso se ajusta al objetivo del alumno.

La IA hace preguntas, resume el caso y propone el siguiente paso sin inventar información ni sustituir revisión humana cuando sea necesaria.

## 3. Recomendador de Servicios

El asistente ayuda al usuario a elegir entre los servicios disponibles.

Puede preguntar por:

- Objetivo.
- Urgencia.
- Presupuesto aproximado.
- Situación actual.
- Preferencias.

Después recomienda el servicio más adecuado, explica por qué encaja y ofrece alternativas.

## 4. Calculadora / Estimador

La IA puede ayudar a estimar precio, alcance, tiempo o complejidad cuando la información del cliente lo permita.

Ejemplos:

- Estimar una reforma según metros y materiales.
- Orientar sobre el alcance de una automatización.
- Explicar rangos de precio si están documentados.
- Pedir datos pendientes para preparar un presupuesto.

Si no hay precios documentados, la IA lo indica y deriva al equipo humano.

## 5. Comparador de Opciones

El asistente puede comparar servicios, planes, tratamientos o alternativas.

Ejemplos:

- Servicio básico vs premium.
- Tratamiento A vs tratamiento B.
- Automatización puntual vs mantenimiento mensual.
- Curso intensivo vs curso regular.

La comparación puede incluir objetivo, ventajas, limitaciones, coste aproximado, plazo y recomendación final.

## 6. Agenda y Reservas

Vantelia permite solicitar y gestionar citas desde el propio widget.

Incluye:

- Formulario de cita integrado en el chat.
- Selección de servicio.
- Selección de profesional si hay varios.
- Disponibilidad por día y hora.
- Bloqueo de horarios ocupados.
- Confirmación de cita.
- Enlace seguro para gestionar la cita.
- Cancelación y reprogramación.
- Historial de reservas.

Proveedores soportados:

- Agenda interna de Vantelia.
- Webhooks hacia herramientas externas.

## 7. Guardado de Conversaciones

Las conversaciones del chat pueden quedar guardadas por cliente.

Se registra:

- Cliente.
- Sesión.
- Mensajes del usuario.
- Respuestas de la IA.
- Intención detectada.
- Fecha y hora.
- Origen de la conversación.

Esto permite revisar dudas frecuentes, detectar oportunidades y entender qué buscan los visitantes de cada web.

## 8. WhatsApp IA

La misma IA del widget puede estar disponible tambien en WhatsApp.

Incluye:

- Webhook compatible con WhatsApp Cloud API.
- Asociacion de cada numero de WhatsApp a un `cliente_id`.
- Uso del mismo cerebro RAG del cliente.
- Guardado de conversaciones en el mismo historial.
- Deteccion de intenciones: diagnostico, recomendacion, estimacion, comparacion y cita.
- Respuesta automatica por WhatsApp al usuario final.
- Soporte para token global o token por cliente mediante variables de entorno.
- Firma `X-Hub-Signature-256` verificable si se configura `WHATSAPP_APP_SECRET`.

Si el usuario pide cita por WhatsApp, la IA responde y puede enviar el enlace publico del cliente para completar el formulario cuando sea necesario.

## 9. Portal Cliente

Cada empresa cliente puede acceder a su propio portal.

Desde el portal puede:

- Ver próximas citas.
- Consultar historial.
- Cancelar o reprogramar reservas.
- Gestionar agenda, horarios y bloqueos.
- Gestionar profesionales.
- Revisar y editar configuración básica del asistente.
- Editar el cerebro del asistente.
- Cambiar contraseña y datos de acceso.

El cliente solo ve la información de su propia empresa.

## 10. Panel Administrador

Vantelia cuenta con un panel interno para administrar toda la plataforma.

Permite:

- Crear y editar clientes.
- Configurar nombre, color, bienvenida, dominios y contacto.
- Activar WhatsApp para cada cliente.
- Gestionar el cerebro de cada asistente.
- Reindexar el contenido IA.
- Ver clientes activos.
- Gestionar usuarios del portal.
- Revisar reservas.
- Cancelar, reprogramar o reenviar emails de citas.
- Consultar timelines de auditoría.
- Ejecutar recordatorios.
- Acceder a demos compartibles por cliente.
- Obtener snippets de instalación.

## 11. Alta Express de Clientes

El sistema puede generar un primer cliente a partir de una web corporativa.

El flujo:

1. Se introduce la URL del negocio.
2. Vantelia analiza páginas públicas.
3. Genera un cerebro inicial estructurado.
4. Propone nombre, bienvenida y configuración base.
5. Guarda el cliente.
6. Reindexa la información.
7. Deja lista una demo y un snippet de instalación.

Es una forma rápida de crear asistentes personalizados para empresas.

## 12. Emails y Recordatorios

La plataforma puede enviar comunicaciones operativas.

Incluye:

- Confirmación de cita.
- Cancelación.
- Reprogramación.
- Recordatorio 24h.
- Recordatorio 2h.
- Recuperación de contraseña.
- Reenvío manual desde el panel.
- Plantillas configurables por cliente.

## 13. Seguridad y Control

Vantelia incluye varias medidas básicas de control.

- Sesiones para portal y administrador.
- Roles de administrador y cliente.
- Token técnico para endpoints admin.
- Cookies `httponly`.
- Control de dominios autorizados.
- Rate limit en chat y reservas.
- Tokens seguros para gestionar citas.
- Separación de datos por cliente.

## 14. Operación y Despliegue

El proyecto está preparado para operación en VPS.

Incluye:

- Dockerfile.
- Docker Compose para Hostinger VPS.
- Script de despliegue.
- Healthcheck avanzado.
- Script de backup.
- Documentación de administración.
- Documentación legal base.
- Tests mínimos de seguridad y smoke.

## 14. Qué Puede Vender Vantelia

Vantelia puede ofrecer a empresas:

- Asistentes IA personalizados para web.
- Chatbots con RAG por cliente.
- Diagnósticos inteligentes.
- Recomendadores de servicios.
- Estimadores o calculadoras comerciales.
- Comparadores de opciones.
- Agenda online inteligente.
- Automatización de reservas.
- Portal privado para clientes.
- Panel de administración para la agencia.
- Alta rápida de nuevos asistentes.
- Seguimiento de conversaciones y oportunidades.

En resumen: Vantelia no es solo un chatbot. Es una plataforma para convertir la web de una empresa en un canal de atención, cualificación y captación automatizada con IA.
