# Caza de fallos: el prompt que me doy a mí mismo

Pablo lo dijo así: *"cuando te digo un fallo suelen salir más"*. Tiene razón, y la
razón es concreta: los fallos de este repo **no son sucesos aislados, son clases**.
Cuando uno aparece, sus hermanos ya estaban ahí — nadie había ido a buscarlos.

Este documento es el prompt reutilizable. No describe funcionalidad: describe
**cómo se rompe este proyecto**, con la búsqueda que encuentra cada clase.

---

## Cómo usarlo

> Audita el repo contra `docs/CAZA_DE_FALLOS.md`. Para cada clase, corre su
> búsqueda, revisa TODOS los resultados y decide caso por caso: fallo real,
> aceptable o falso positivo. Antes de arreglar, escribe el test que reproduce el
> fallo y **verifícalo contra el código actual** (si pasa sin el arreglo, no vale).
> Reporta lo que decidas no arreglar y por qué.

Regla que ha costado tiempo aprender: **un test que no falla con el bug presente
no prueba nada**. Se comprueba con `git stash` del arreglo.

---

## Las clases, ordenadas por lo que han costado

### 1. Divergencia entre canales

El mismo concepto implementado por separado en chat, WhatsApp y voz. Cada canal
"mejora" lo suyo y acaban discrepando entre ellos y con el panel.

Casos reales: el menú (3 opciones en el panel, 4 en el chat, 6 en WhatsApp); el
saludo de WhatsApp ignorando la bienvenida configurada; el horario del prompt
saliendo de config crudo mientras la disponibilidad usaba la matriz semanal.

```bash
# Textos casi iguales en dos canales: candidatos a fuente única
rg -n '"(Hola|Menú|📋|👋)' backend/chat.py backend/whatsapp.py backend/voice.py
# Constantes de negocio duplicadas
rg -n 'BASE_STARTERS|_resolve_widget_starters|menu_entries' backend/
```

**Pregunta a hacerse:** ¿esto lo decide el negocio en el panel? Entonces solo
puede haber UNA función que lo lea, y los tres canales la llaman.

---

### 2. El cliente encerrado en un paso

Máquinas de estado (`flow.flow` en WhatsApp) donde una rama responde un error y
`return`, sin salida. El agravante típico es una guarda "protectora"
(`if not flow.flow`) que impide que un saludo o el menú rescaten al usuario.

```bash
# Errores que terminan en return dentro de una rama de estado
rg -n -B2 -A4 'No he reconocido|no he entendido|No entiendo' backend/
# Guardas que apagan capas enteras cuando hay flujo activo
rg -n 'if not flow\.flow' backend/whatsapp.py
```

**Pregunta:** si el cliente escribe algo razonable pero fuera de guion, ¿tiene
salida? ¿Y si escribe "hola"?

---

### 3. Estado en memoria que nadie caduca

Diccionarios globales en `appstate` que crecen sin fin, o —peor— que devuelven un
estado viejo como si fuera actual. `whatsapp_flows` guardaba `last_seen` y no lo
miraba nadie: quien abandonaba una reserva reaparecía en el mismo paso días después.

```bash
rg -n '^[a-z_]+: Dict' backend/appstate.py
# Para cada uno: ¿quién lo purga? ¿quién comprueba su antigüedad?
rg -n 'last_seen|TTL|_purge|expired' backend/
```

**Pregunta:** ¿qué pasa si el usuario vuelve mañana? ¿Y con 10.000 conversaciones?

---

### 4. Límites de plataforma aplicados a lo bruto

WhatsApp corta títulos a 24 caracteres y descripciones a 72; una lista admite 10
filas. Recortar con `[:24]` convirtió "Keratina premium corto chico" en "Keratina
premium corto c" — idéntico al recorte de "corto medio".

```bash
rg -n '\[:[0-9]{1,3}\]' backend/ --glob '!**/test_*'
```

**Pregunta:** ¿este recorte lo lee una persona? ¿Dos elementos distintos pueden
quedar iguales después de cortar?

---

### 5. Texto que no casa lo que el cliente escribe

Patrones acentuados comparados contra texto ya normalizado sin tildes; mojibake
por doble codificación. Ambos fallan **en silencio**: sin error y sin log.

Ya lo vigila `tests/test_patrones_sin_tilde.py`. Ver sección 9 de
`docs/MAPA_DEL_CODIGO.md`.

---

### 6. Operaciones destructivas con un flag inocente

`_sync_services_from_info(deactivate_missing=True)` desactivó 183 servicios de un
salón real al guardar la ficha del panel.

```bash
rg -n 'deactivate|delete_missing|purge|DELETE FROM|UPDATE .* SET is_active' backend/
```

**Pregunta:** ¿quién llama a esto y con qué flag? ¿Qué pasa si el origen viene vacío?

---

### 7. Una verdad repartida en dos sitios

Hay **dos** tablas de pago (`booking_payments` y `customer_payments`). Mirar solo
una hace que el saldo mienta; por eso existe `backend/paystate.py`.

```bash
rg -n 'booking_payments|customer_payments' backend/ | grep -v paystate.py
```

**Pregunta:** ¿esta consulta ve las dos fuentes? ¿O debería llamar a `paystate`?

---

### 8. Índices y contadores que se desalinean

`menu_starter_N` se resolvía contra una lista distinta de la que pintó el menú: al
añadir la fila de tarjeta regalo, los índices dejaban de coincidir.

```bash
rg -n 'enumerate\(|_%d|\[index\]|\[indice\]' backend/whatsapp.py backend/chat.py
```

**Pregunta:** ¿la lista que numera y la que resuelve son la MISMA llamada?

---

### 9. Excepciones tragadas

`except Exception: pass` que oculta un fallo real y deja al cliente sin respuesta.

```bash
rg -n -A2 'except Exception' backend/ | rg -n 'pass$|continue$'
```

**Pregunta:** si esto falla, ¿alguien se entera? ¿El cliente recibe algo?

---

### 10. Lo que promete el panel y no cumple el backend

El panel dice *"las 3 primeras son fijas; Vantelia no añade más sugerencias
automáticamente"* mientras WhatsApp anteponía cuatro. La UI es un contrato.

```bash
rg -n 'panel-sub|<p class="panel-sub"' app_ui/index.html
```

**Pregunta:** ¿el backend cumple literalmente lo que esa frase promete?

---

## Después de auditar

- Los fallos encontrados van con test que reproduce, verificado contra el código
  anterior.
- Las clases nuevas se añaden aquí, con su búsqueda.
- Si una clase deja de tener sentido, se borra: un documento que miente es peor
  que no tenerlo.
