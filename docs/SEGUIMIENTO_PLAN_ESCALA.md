# Seguimiento del plan de escala desde el panel admin

## Acceso

1. Entra en `https://app.vantelia.es/dashboard`.
2. Abre **Plan de escala** en la navegación principal.
3. El documento `docs/PLAN_ESCALA_AGENCIA_IA.md` sigue siendo la fuente de verdad estratégica.

## Uso diario

### Panel Hoy

Al terminar la jornada, registra únicamente resultados reales:

- prospectos investigados;
- contactos y follow-ups;
- llamadas y respuestas positivas;
- conversaciones, reuniones y propuestas;
- ventas, euros vendidos y recurrencia;
- horas de entrega;
- aprendizaje, bloqueo y próxima acción.

Pulsa **Guardar día**. El registro de la fecha se actualiza si ya existía, por lo
que no puede duplicarse accidentalmente.

Marca también las tareas completadas del calendario inicial. Los objetivos diarios
se muestran como referencia, pero nunca se suman automáticamente como resultados.

### Pipeline

Crea una oportunidad cuando exista una conversación comercial real. Toda
oportunidad activa debe tener:

- empresa;
- oferta y campaña;
- etapa;
- problema;
- valor estimado;
- próxima acción;
- fecha de próxima acción.

El panel destaca oportunidades vencidas o sin próxima acción y conserva el
historial de cambios.

## Uso semanal

1. Abre **Métricas** y revisa 7, 30 y 90 días.
2. Comprueba estados verde, alerta y STOP.
3. Revisa evolución semanal y separación por campaña y oferta.
4. Abre **Revisión semanal**.
5. Pulsa **Generar revisión con datos**.
6. Escribe la decisión semanal y guárdala.

La revisión no inventa conclusiones cuando faltan datos.

## Automatización responsable

El panel muestra prospects, envíos y respuestas detectadas por Captación como
contexto separado. Esas cifras no se suman a contactos, conversaciones o ventas
manuales para evitar confundir actividad automática con resultados reales.

## Cómo puede Codex conocer el estado

Cuando trabajemos sobre crecimiento, Codex debe consultar primero las tablas:

- `growth_daily`;
- `growth_opportunities`;
- `growth_opportunity_audit`;
- `growth_weekly_reviews`;
- `growth_plan_tasks`.

También puede consultar el endpoint protegido `GET /admin/growth/overview` cuando
disponga de una sesión o token administrativo.

Prompt recomendado:

```text
Revisa el estado real del Plan de escala en la base de datos y contrástalo con
docs/PLAN_ESCALA_AGENCIA_IA.md. Dime qué funciona, qué incumplí, el principal
cuello de botella y mis cinco prioridades. No cambies la estrategia sin datos.
```

## Scripts de respaldo

`scripts/scale_tracker.py` queda como herramienta local de respaldo y exportación.
La operación diaria se realiza desde el panel.
