# Contrato compartido del agente de Vantelia

Decisión de Pablo, 12-sep-2026. Aplicable a Astra, Claude y futuras sesiones.
Es la dirección obligatoria de la consolidación; no afirma que el código actual
ya la cumpla. El plan y su evidencia viven en `PLAN_CONSOLIDACION_IA.md`.

## Una responsabilidad por decisión

- El modelo interpreta y redacta. Puede proponer acciones, pero no dar por
  ejecutada una operación ni decidir restricciones del negocio.
- El estado conserva gestión, datos verificados, propuestas y confirmaciones.
  Ofrecer, aceptar, rechazar y ejecutar son hechos distintos. Una alternativa
  aceptada sustituye la anterior; no se vuelve a exigir su técnica o talla.
- Las políticas pertenecen al tenant. Ninguna condición por nombre de negocio,
  tono de peluquería o requisito de Alicia se convierte en regla general.
- El núcleo compartido valida y ejecuta. Disponibilidad, creación, cancelación
  y reprogramación usan las mismas fuentes de horarios, duración y ocupación.
- Los canales adaptan entrada y salida; no mantienen motores de decisión propios.

## El portal es la fuente del negocio

- Q&A contiene respuestas informativas y permite gestionar las reglas del negocio
  en esa misma sección. Se reutilizan los datos y endpoints existentes.
- Una respuesta libre no se convierte silenciosamente en una restricción
  ejecutable: la regla muestra su alcance, condición, acción y estado de activación.
- Horarios, vacaciones, bloqueos, profesionales, servicios y precios se leen de
  sus fuentes operativas del portal. Q&A no mantiene copias autoritativas de ellos.
- Guardar o desactivar una regla, cambiar un servicio o introducir vacaciones debe
  afectar a la siguiente consulta pertinente. Invalidar cachés por tenant y
  revalidar propuestas antiguas antes de confirmar; no prometer un dato obsoleto.
- Si la configuración es contradictoria, mostrar qué hay que corregir. No decidir
  precedencias por el orden accidental de instrucciones en un prompt.
- Las restricciones de integridad y acceso del núcleo no son anulables por Q&A.

## Cómo modificar el agente

1. Escribir el caso concreto y localizar el dueño de la decisión.
2. Corregir esa decisión en su capa. No añadir otro interceptor que reconozca
   frases de la respuesta para cambiar la intención o el servicio.
3. Si se sustituye un mecanismo, retirar el camino duplicado en la misma fase
   cuando los casos que cubría estén protegidos por pruebas de comportamiento.
4. No convertir un fallo del proveedor en éxito. No registrar una respuesta como
   enviada antes de la aceptación del canal. Los recordatorios requieren control
   de duplicación y trazabilidad del resultado.
5. Toda política particular necesita una prueba positiva en su tenant y otra que
   compruebe su ausencia en un negocio distinto. Probar cambios desde el portal,
   también durante una conversación existente.
6. Pruebas deterministas primero; mediciones del modelo después, en copia aislada,
   con fechas y huecos válidos, sin ocultar reintentos. No prometer perfección.

## Coordinación y coste

Astra diseña e implementa el plan autorizado; Claude aporta contexto,
revisión, datos saneados y mediciones reales. Claude implementa solo piezas que
Astra le encargue explícitamente. Antes de editar en paralelo se asignan archivos y
ramas. `ESTADO_ACTUAL.md` registra el testigo y siguiente paso. Ambos leen este
contrato antes de tocar decisiones conversacionales o políticas del negocio.

Leer solo el contexto necesario, cerrar fases pequeñas y guardar commits con
evidencia. No releer el repositorio ni consultar periódicamente suites en curso.
Usar su finalización o comprobar el resultado al retomar trabajo dependiente.
Las autorizaciones de despliegue y acceso a secretos siguen las reglas existentes.

### Un encargo, un ejecutor (incidente del 19-sep)

`--encargar astra claude` despierta un ejecutor automático en otra copia. Si la
sesión principal de Claude también lee ese encargo, no debe implementarlo otra
vez. Con una sesión principal activa y trabajo acordado, usar `--avisar` para el
reparto directo; reservar `--encargar` para la ejecución automática. Registrar
quién tiene el trabajo, su rama y la siguiente entrega en «En curso».

El 19-sep el mismo encargo produjo `3c646b0` y `93416aa`: se compararon y se
conservó una sola implementación, con las pruebas más completas, sin borrar la
otra rama. No repetir esa duplicación de trabajo ni suites. Una revisión manual
del candidato debe referirse a su SHA y a la evidencia de la suite ya terminada;
repetir pruebas solo para verificar un hallazgo o por cambios posteriores.
