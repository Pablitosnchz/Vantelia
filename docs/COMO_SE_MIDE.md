# Como se mide si el asistente esta bien

> Antes de esto, saber si el asistente funcionaba consistia en que el duenyo pegara
> capturas de WhatsApp. Los ocho fallos del 25 y 26 de agosto de 2026 se
> descubrieron todos asi. Los que nadie cuenta -a la clienta a la que se le dijo
> "a las 10:30 ya tengo una cita" siendo mentira- no se veian jamas: esa no se
> queja, simplemente no vuelve.

Hay **cinco instrumentos**. Cada uno contesta una pregunta distinta y ninguno
sustituye a otro. Esta pagina dice cual usar, que cuesta, como se lee y las
trampas que ya han costado tiempo o dinero.

---

## De un vistazo

| Instrumento | Contesta | Cuesta | Cuando |
| --- | --- | --- | --- |
| `python -m pytest` | ¿Sigue funcionando el mecanismo? | gratis, 10 min | siempre, antes de commit |
| `scripts/humo.py` | ¿Llegan las conversaciones al final? | centimos, 5 min | automatico en cada despliegue |
| `scripts/evaluar_asistente.py` | ¿Contesta bien a los casos que ya fallaron? | centimos | tras tocar como responde |
| `scripts/simular_clientas.py` | ¿Que porcentaje de clientas consigue lo que venia a buscar? | ~1 EUR, 1-2 h | para decidir con datos |
| `backend/calidad.py` + `backend/trazas.py` | ¿Que esta pasando AHORA en produccion? | gratis | a diario, en el panel |

---

## 1. Los tests: el mecanismo

```powershell
python -m pytest
```

Comprueban que las piezas hacen lo que dicen. **No comprueban que la clienta
acabe con su cita**, y esa distincion ha costado dos regresiones en produccion en
la misma tarde: las dos pasaron los 1.373 tests, porque el detector que
comprobaban saltaba perfectamente. Lo que se rompio fue el CAMINO.

Los tests de este repo que vigilan REGLAS (no mecanismos) estan listados en
`tests/README.md`. **Si uno de esos falla, leelo antes de "arreglarlo"**: suele
estar impidiendo que se repita un fallo que ya paso.

## 2. El humo: los cinco caminos

```powershell
python scripts/humo.py --cliente alicia_rincon_estilistas
```

Cinco conversaciones enteras por el recorrido REAL de WhatsApp, contra una copia
de la base de datos. Exige el resultado en la **agenda**, no lo que diga el texto:
¿acabo habiendo cita?, ¿se cancelo?, ¿se movio sin duplicarse?

Corre solo en cada `deploy.ps1` y **para el despliegue** si un camino se rompe.

Trampa aprendida: al otro lado hay un modelo, no una funcion, asi que la misma
conversacion puede salir distinta dos veces. Por eso **reintenta una vez** antes de
acusar. Un fallo de verdad falla las dos; un tropiezo, no. Sin eso bloqueaba
despliegues por azar, se le habria perdido la fe y habria acabado ignorandose, que
es como si no existiera.

## 3. El banco de casos: lo que ya fallo una vez

```powershell
python scripts/evaluar_asistente.py --db-copia /tmp/eval.db
```

Los casos reales que salieron mal alguna vez, con **severidad**: si falla un
CRITICO -inventarse un precio, dar por hecha una cita, negar un servicio que
existe- la tirada entera se da por mala.

`--db-copia` es **obligatorio** para los casos que exigen un efecto en la agenda.
No basta con exportar `DB_PATH`: `settings.DB_PATH` se fija al importar. Ignorarlo
costo siete citas de prueba en la agenda de un cliente real.

## 4. El simulador: el porcentaje

```powershell
python scripts/simular_clientas.py --cliente alicia_rincon_estilistas \
    --conversaciones 100 --db-copia storage/mediciones/sim.db \
    --guardar storage/mediciones/sim100.json
```

Cien clientas inventadas (con su objetivo, su familia de servicio y su forma de
escribir) hablan de verdad con el asistente. El veredicto lo pone la **agenda**:

* **bien** — consiguio lo que venia a buscar,
* **atascada** — se fue sin ello,
* **fallo** — ademas se dijo o se hizo algo mal.

Deja dos ficheros: el informe y, al lado, `*.fallos.json` con las conversaciones
rotas **enteras**. Sin eso, el informe dice "14 x repite la misma pregunta" y
averiguar QUE pregunta repetia costaba otra tirada de 100.

## 5. La vigilancia: que pasa ahora

* `backend/trazas.py` — que hizo el asistente en cada turno: herramientas con sus
  argumentos, frenos que saltaron, vueltas, milisegundos, modelo y **coste en
  euros**. Contesta "¿miro la agenda antes de decir eso?" mirando una fila, en vez
  de escribiendo un script desechable (un dia se escribieron doce).
* `backend/calidad.py` — repasa las conversaciones del dia y marca las malas sin
  que nadie las cuente. Son funciones puras: **no llama al modelo**, asi que
  vigilar no cuesta dinero por conversacion. Hay un test que lo impide.

---

## Las trampas (todas han pasado)

**Cuando el arreglo no mueve la aguja, sospecha de la CAPA, no de la fuerza.**
Cuatro veces se puso un guardarrail en el agente cuando por WhatsApp la cita la
crea el boton del resumen. El guardarrail era correcto y no servia de nada. Los
frenos van en el **cuello de botella**, no en uno de los caminos que pasan por el.

**Cuando el numero BAJA, sospecha del instrumento.** El simulador daba por rotas
conversaciones bien llevadas porque no podia pulsar "Confirmar". Y tenia su propia
lista de "sies", mas permisiva que la del producto: pulsaba el boton en frases que
el producto rechazaba, la cita salia en la agenda y la conversacion contaba como
buena. La clienta real se habria quedado sin cita. Ahora **el arnes delega en el
producto**.

**No despliegues en mitad de una medicion.** Recrea el contenedor y se lleva la
tirada por delante. Paso dos veces. Por eso las mediciones se guardan en
`storage/mediciones/`, no en `/tmp`.

**No parchees el contenedor a mano mientras mides.** Un 72 % salio contaminado
asi. Un numero que no se puede reproducir no es un numero.

**Un test que no falla sin el arreglo no prueba nada.** Antes de darlo por bueno,
quita el arreglo y comprueba que el test se pone rojo.

**Mide siempre con el mismo juez y el mismo n.** Comparar 40 con 100, o dos
versiones distintas del veredicto, es comparar cosas distintas. Si el instrumento
cambia, dilo al dar el numero.

---

## Historial de mediciones (n=100, mismo juez)

| Fecha | Bien | Que cambio |
| --- | --- | --- |
| 26-ago | 62 % | primera medida seria |
| 26-ago | 63 % | memoria del estado de la reserva |
| 26-ago | 66 % | las cuatro opciones de mechas, sin repetir |
| 26-ago | 68 % | remate con horas reales a quien insiste con el precio |

Las tiradas de 45 %, 51 % y 58 % de ese mismo dia salieron de un arnes roto (no
podia pulsar "Confirmar") y **no son comparables**. El 72 % salio de un
contenedor parcheado a mano y **tampoco cuenta**.
