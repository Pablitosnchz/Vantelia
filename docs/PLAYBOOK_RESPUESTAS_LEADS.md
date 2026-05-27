# Playbook de respuestas a leads warm

Plantillas para responder a prospects que ya contactaron via outreach
y muestran intencion. Lenguaje simple, sin jerga tecnica. Tono humano,
breve.

---

## Caso 1: Lead pregunta por precios (sin haber probado el bot)

Contexto: respondio al email cold preguntando precios/costes/suscripcion.
NO ha entrado a crear el bot todavia.

Objetivo:
1. Dar precios claros sin tecnicismos.
2. Empujar a que cree el bot el mismo (autoservicio, 2 min).
3. Pedir feedback de uso (aunque sea Free).
4. Ofrecer codigo descuento personalizado.

### Pasos

1. **Crear codigo descuento Stripe** (ver seccion "Codigos descuento" abajo).
   Nombre sugerido: `{NEGOCIO}1MES` (ej: `NOOK1MES`, `BAVIERA1MES`).
2. **Enviar email** con plantilla "Pregunta precios" abajo.
3. **Marcar prospect** como `replied` en panel admin captacion.
4. **Apuntar follow-up** llamada en 3-4 dias si silencio.

### Plantilla "Pregunta precios"

```
Hola,

Te lo explico corto:

- Gratis — 0€. 50 mensajes al mes.
- Starter — 19€/mes. 1.000 mensajes al mes.
- Pro — 49€/mes. 5.000 mensajes al mes + reservas + chat en vivo.
- Business — 149€/mes. 25.000 mensajes + WhatsApp.

Sin permanencia, cancelas cuando quieras.

Como estamos arrancando, te regalo un mes entero gratis del plan que
elijas con este codigo: {CODIGO} (lo pones al pagar).

Antes que nada, lo mejor es que entres y lo crees tu mismo en 2 minutos,
gratis y sin tarjeta:

https://app.vantelia.es/acceso?signup=1

El bot aprende solo leyendo tu web ({WEB_LEAD}). Cuando lo tengas, lo
pruebas y me dices que te parece — si responde bien, si le falta algo,
si te gusta el tono. Cualquier opinion me sirve.

Si te atascas en algo, escribeme a cualquier hora (info@vantelia.es o
+34 675 802 001), te ayudo en el momento.

Pablo
```

Sustituir `{CODIGO}` por el codigo Stripe y `{WEB_LEAD}` por el dominio
del lead (ej: `thenookmadrid.com`).

---

## Caso 2: Lead ya probo el bot y pregunta dudas tecnicas

Pendiente — completar cuando llegue primer caso.

---

## Caso 3: Lead pide demo personalizada

Pendiente — completar cuando llegue primer caso.

---

## Codigos descuento Stripe (proceso)

Sistema: Stripe coupons + promotion codes. Vantelia ya acepta promotion
codes en checkout (`allow_promotion_codes=true` por defecto). El cliente
solo escribe el codigo al pagar y se aplica.

### Crear codigo personalizado (1 mes gratis)

Variables: `SK` = `STRIPE_SECRET_KEY` del `.env`. `NEGOCIO` = ej. `NOOK`.
Codigo final = `{NEGOCIO}1MES`.

**Paso 1**: crear coupon (descuento 100% un solo pago).

```bash
SK=$(grep "^STRIPE_SECRET_KEY=" .env | cut -d= -f2-)
curl -s https://api.stripe.com/v1/coupons -u "${SK}:" \
  -d "percent_off=100" \
  -d "duration=once" \
  -d "max_redemptions=1" \
  -d "name=NEGOCIO - 1 mes gratis"
```

Anotar el `id` que devuelve (ej: `BB4TKADY`).

**Paso 2**: crear promotion_code amigable enlazado al coupon.

```bash
curl -s -X POST https://api.stripe.com/v1/promotion_codes -u "${SK}:" \
  -H "Stripe-Version: 2023-10-16" \
  -d "coupon=ID_DEL_COUPON" \
  -d "code=NEGOCIO1MES" \
  -d "max_redemptions=1"
```

El header `Stripe-Version: 2023-10-16` es obligatorio (sin el, Stripe
rechaza el parametro `coupon` con `parameter_unknown`).

### Variantes utiles

- **3 meses gratis**: `duration=repeating` + `duration_in_months=3`.
- **50% off para siempre**: `percent_off=50` + `duration=forever`.
- **Cantidad fija** (ej. 19€ off): `amount_off=1900` + `currency=eur`.
- **Sin limite redemption**: omitir `max_redemptions`.
- **Caducidad**: anadir `redeem_by=<unix_timestamp>` en el coupon.

### Verificar codigo activo

```bash
SK=$(grep "^STRIPE_SECRET_KEY=" .env | cut -d= -f2-)
curl -s "https://api.stripe.com/v1/promotion_codes?code=NOOK1MES" -u "${SK}:" -G \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',[{}])[0])"
```

### Codigos ya emitidos

| Codigo      | Coupon ID  | Negocio              | Descuento     | Uso  | Fecha       |
|-------------|------------|----------------------|---------------|------|-------------|
| NOOK1MES    | BB4TKADY   | The Nook Madrid      | 100% 1 pago   | 1/1  | 2026-05-27  |

Mantener esta tabla actualizada al emitir codigos nuevos para auditoria.

---

## Reglas generales tono

- **Sin jerga**: no usar "widget", "RAG", "endpoint", "embedding", "API".
- **Equivalentes**: "el bot que pones en tu web", "lee tu web sola",
  "se conecta con WhatsApp".
- **Frases cortas**. Maximo 2 lineas por parrafo.
- **CTA unica**: 1 sola accion por email (entrar a crearlo, o llamar,
  o responder con fecha — no las 3 a la vez salvo casos muy claros).
- **Sin firma pesada** en respuestas. Solo "Pablo" + telefono. Firma
  completa solo en cold/fu1/fu2.
- **Soporte 24h**: mencionarlo cuando ayude (lead nervioso, ticket
  potencial). No spammear en cada email.
