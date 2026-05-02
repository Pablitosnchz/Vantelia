# Manual del cliente Vantelia

Bienvenido. Este manual te guia desde tu primer acceso hasta tener el asistente IA funcionando en tu web y en WhatsApp.

Soporte: soporte@vantelia.es

---

## 1. Que es Vantelia

Vantelia es una plataforma SaaS que crea un asistente de IA personalizado para tu negocio. Funciona en:

- Widget de chat embebido en tu web.
- Tu numero de WhatsApp Business.
- Email transaccional cuando agenda citas.

El asistente responde a tus clientes 24/7, agenda citas en tu calendario, deriva al equipo humano cuando no sabe y aprende de la informacion que tu nos das.

---

## 2. Acceso al portal

Tras contratar recibiras por email:

- URL del portal: `https://app.vantelia.es/portal`.
- Email + contrasena temporal.

Primer login:

1. Entras en la URL.
2. Login con email y contrasena.
3. Cambia la contrasena en la primera entrada (panel > Mi cuenta > Cambiar contrasena).

---

## 3. Configurar el cerebro del asistente

El "cerebro" es la informacion sobre tu negocio que la IA usa para responder.

### 3.1 Donde editar

Portal > seccion **Cerebro** (o `info.txt`).

### 3.2 Estructura recomendada

```
===== INFORMACION DE [TU EMPRESA] =====

DATOS GENERALES:
- Nombre: [empresa]
- Tipo de negocio: [sector]
- Descripcion: [una frase clara]
- Eslogan: [opcional]

UBICACION Y HORARIOS:
- Direccion: [calle, ciudad]
- Horario: [L-V 09:00-18:00]
- Dias cerrados: [domingos, festivos]

SERVICIOS:
- [Servicio 1]: [descripcion + precio si procede]
- [Servicio 2]: ...

EQUIPO:
- [Profesional 1] - [especialidad]
- ...

POLITICAS:
- Cancelaciones: [plazo]
- Devoluciones: [condiciones]
- Garantia: [...]

PREGUNTAS FRECUENTES:
1. [Pregunta]
   Respuesta: [...]

CONTACTO:
- Telefono: [...]
- Email: [...]
- Web: [...]
```

### 3.3 Reglas claves

- Cuanto mas detalle, mejor responde la IA.
- No dejes campos vacios o "no especificado": la IA evitara responder sobre eso.
- Tras editar, pulsa **Guardar** y luego **Reindexar** (o se hace automatico si lo tienes activo).
- Cambios en el cerebro se reflejan en 1-2 minutos.

---

## 4. Configurar empleados y agenda

Solo si tu plan incluye reservas online.

### 4.1 Empleados

Portal > **Equipo / Empleados**. Para cada profesional:

- Nombre visible al cliente.
- Color (ayuda a distinguirlos en agenda).
- Servicios que ofrece (opcional, si filtras por profesional).
- Horario propio: dia inicio, dia fin, dias cerrados.
- Activo / inactivo.

### 4.2 Servicios

Portal > **Servicios**. Para cada servicio:

- Nombre.
- Descripcion corta.
- Duracion.
- Precio (opcional, visible al cliente si lo configuras).

### 4.3 Bloqueos manuales

Portal > **Agenda > Bloqueos**:

- Vacaciones equipo, dia entero o tramo concreto.
- Reuniones internas.
- Mantenimiento.

Aparecen como motivos cuando el cliente intenta reservar (ej: "🚫 Bloqueado: Vacaciones equipo").

---

## 5. Instalar el widget en tu web

### 5.1 Snippet basico

Pega antes de cerrar el `</body>` de tu web:

```html
<script
  src="https://app.vantelia.es/widget/widget.min.js"
  data-api="https://app.vantelia.es"
  data-client="TU_CLIENTE_ID"
  data-position="right"></script>
```

`TU_CLIENTE_ID` te lo damos al alta.

### 5.2 Personalizacion

Desde el portal puedes cambiar:

- Color principal del widget.
- Avatar (icono o logo).
- Mensaje de bienvenida.
- Posicion (right / left).

Cambios visibles en 1-2 minutos sin reinstalar.

### 5.3 Probar la instalacion

Visita tu web. Pulsa el icono del chat. Deberia abrir y saludar con tu mensaje configurado.

Si no aparece:

- Revisa que el script esta antes del `</body>`.
- Revisa la consola del navegador (F12 > Console) por errores.
- Avisa a soporte@vantelia.es.

---

## 6. Conectar WhatsApp

Solo en planes Pro y Empresa.

### 6.1 Que necesitas tu (cliente)

- Un numero de telefono que **NO** este en WhatsApp normal ni Business app. Si lo esta, desinstalar y borrar la cuenta antes.
- Cuenta gratuita de Meta Business Manager: https://business.facebook.com.

### 6.2 Pasos

1. Te pediremos por email acceso temporal a tu Meta Business Manager.
2. Asociamos tu **WhatsApp Business Account** a la app Vantelia.
3. Verificas tu numero por SMS o llamada cuando Meta lo pida.
4. Aceptas con un click que Vantelia gestione tu WABA.
5. Desde ese momento, los mensajes que reciba tu numero los responde tu asistente IA.

Tiempo total: 10-15 minutos.

### 6.3 Que puede hacer la IA en WhatsApp

- Saludar y mostrar menu interactivo (lista clicable).
- Agendar citas paso a paso (servicio > profesional > fecha > hora > nombre > email > confirmacion).
- Mostrar disponibilidad de los proximos 7 dias.
- Responder preguntas frecuentes, dudas sobre servicios, precios, horarios.
- Recomendar servicios, comparar opciones, estimar precio.
- Derivar al equipo humano cuando no sabe.

### 6.4 Costes

Meta cobra por conversacion iniciada (centimos por conversacion segun pais). Vantelia te lo factura aparte o incluye un volumen segun plan. Detalle en tu contrato.

---

## 7. Gestion de citas en el portal

### 7.1 Ver citas

Portal > **Citas**:

- Filtros por fecha, profesional, estado.
- Vista lista o calendario.
- Buscar por nombre o telefono.

### 7.2 Estados de cita

- **Pendiente**: recien creada, sin confirmar manual.
- **Confirmada**: lista para celebrarse.
- **Cancelada**: cliente o tu cancelasteis.
- **Reprogramada**: se cambio fecha u hora.

### 7.3 Acciones

- Confirmar manualmente.
- Cancelar (con o sin email al cliente).
- Reprogramar (mover a otro hueco).
- Anadir notas internas.
- Ver auditoria (quien hizo que cuando).

### 7.4 Recordatorios automaticos

- Email 24h antes.
- Email 2h antes.
- Configurables desde el portal (activar/desactivar).

---

## 8. Conversaciones del asistente

Portal > **Chats**:

- Lista de conversaciones (web y WhatsApp).
- Filtros por canal, fecha, intencion (cita, FAQ, recomendacion).
- Ver historico completo de cada conversacion.
- Detectar patrones: que preguntan mas, que la IA no responde bien.

Sirve para mejorar tu `info.txt` con las preguntas reales que te hacen.

---

## 9. Email transaccional

Vantelia envia automaticamente desde `noreply@vantelia.es` (o tu dominio si lo configuraste):

- Confirmacion de cita al cliente final.
- Recordatorio 24h y 2h antes.
- Notificacion de cancelacion.
- Notificacion de reprogramacion.

Las plantillas se pueden personalizar desde el portal (logo, colores, texto).

---

## 10. Plan, facturacion, limites

### 10.1 Donde ver tu plan

Portal > **Mi cuenta > Suscripcion**:

- Plan activo.
- Conversaciones consumidas este mes.
- Citas creadas este mes.
- Limites del plan.
- Fecha proximo cobro.

### 10.2 Cambiar de plan

- Subir de plan: efecto inmediato.
- Bajar de plan: efecto el siguiente ciclo de facturacion.
- Cancelar: el servicio sigue activo hasta el final del periodo pagado, despues se desactiva.

### 10.3 Facturas

Portal > **Mi cuenta > Facturas**: descarga PDF.

---

## 11. Seguridad y privacidad

### 11.1 Quien ve tus datos

- Solo tu equipo (los usuarios que tu crees en el portal).
- Vantelia (soporte) accede unicamente para resolver incidencias bajo tu peticion.
- OpenAI procesa los mensajes para generar respuestas. No los usa para entrenar (cuenta enterprise).

### 11.2 Datos sensibles

- No subas al `info.txt` historiales medicos, datos bancarios, contrasenas o documentos firmados.
- Para datos sensibles del cliente final, derivar al equipo humano.

### 11.3 RGPD

- Firmamos contigo un Acuerdo de Encargado de Tratamiento (DPA) al alta.
- Tus clientes finales pueden ejercer derechos ARSULIPO escribiendo a tu email.

---

## 12. Buenas practicas

### 12.1 Para que la IA responda mejor

- Mantén `info.txt` actualizado. Cambios de precios, horarios, equipo: editar al instante.
- Anade preguntas frecuentes reales que te hacen.
- Especifica casos limite: "Si pregunta por X, responde Y".

### 12.2 Errores comunes

- Olvidar reindexar tras editar `info.txt`.
- No tener empleados activos (la IA dira "sin huecos").
- `closed_weekdays` mal configurado (la IA cierra dias que en realidad abres).
- Tener huecos completamente bloqueados sin motivo (mejor poner motivo claro: "vacaciones", "formacion").

### 12.3 Cuando avisar a soporte

- Caida del servicio (chat no responde >5 min).
- Bug en booking (cita guardada con datos raros).
- Cambios estructurales (mover dominio, cambiar pasarela cobro).
- Cuando quieras integrar Google Calendar o Calendly.

---

## 13. Contacto soporte

- Email: soporte@vantelia.es
- Horario: L-V 09:00-18:00.
- Tiempo respuesta: <24h habiles.
- Urgencias (caida total): respuesta <2h habiles.

---

## 14. Glosario

- **Cliente**: tu empresa, contratante de Vantelia.
- **Cliente final**: persona que escribe al asistente desde tu web o WhatsApp.
- **Cerebro / info.txt**: documento con la informacion de tu negocio que la IA usa.
- **Reindexar**: regenerar el indice vectorial tras editar el cerebro.
- **WABA**: WhatsApp Business Account, tu cuenta de WhatsApp empresarial en Meta.
- **Phone Number ID**: identificador interno de Meta para tu numero de WhatsApp.
- **Manage token**: enlace privado que recibe el cliente final para gestionar su cita.
