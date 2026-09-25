# Plan: que Sara hable con quien decide

Idea de Pablo (25-sep-2026): en una peluqueria suele coger el telefono quien esta en
el mostrador, no quien decide. Sara tiene que saber con quien habla y, si no es el
dueno o la encargada, preguntar por esa persona: o se pone al telefono, o le dan sus
datos para hablar con ella despues.

## Como tiene que ir la llamada

1. **Saludo y gancho, igual que hoy** (corto, con el aviso de que es una IA y la
   opcion de no recibir mas llamadas).
2. **Justo despues del gancho, una pregunta natural, una sola vez**, algo como
   "¿Hablo con quien lleva el salon?". No es un interrogatorio al empezar: va
   despues del gancho, cuando ya sabe por que la llaman. Si ya ha dicho que es la
   duena ("si, soy yo, digame"), no se pregunta.
3. Tres caminos:
   - **Es la duena o la encargada:** sigue como hoy (demo y cierre).
   - **No lo es, pero "un segundo, ahora se pone":** Sara dice "claro, espero" y se
     queda **callada** hasta que hable alguien. Cuando se pone la otra persona,
     **se vuelve a presentar entera**: quien es, que es una IA, que es comercial y
     que puede pedir que no la llamemos. La que coge ahora no lo ha oido, y la ley lo
     exige a quien recibe la llamada. Despues, gancho y demo como siempre.
   - **No lo es y no esta:** pide el nombre y cuando suele estar ("¿como se llama?
     ¿cuando la pillo?"). Si le ofrecen un email para mandarle la informacion, lo
     apunta. No insiste en nada: si no quieren dar datos, se despide amable.
4. Si quien coge es del equipo y tiene curiosidad, la demo tambien se le puede
   hacer: sufre el telefono todos los dias. Pero el cierre (mandar la informacion,
   volver a llamar) apunta siempre a quien decide.

## Que se apunta

Herramienta nueva `anotar_responsable`, que Sara llama en cuanto lo sabe:

| Campo | Ejemplo |
| --- | --- |
| `interlocutor` | duena_o_encargada / empleado / no_se_sabe |
| `responsable_nombre` | "Marta" |
| `responsable_cuando` | "por las tardes a partir de las cuatro" (tal cual) |
| `responsable_email` | solo si lo dan ellos |
| `se_pone_ahora` | si / no |

Se guardan en columnas nuevas de `llamadas_voz`. Respaldo: la clasificacion al
terminar la llamada (fase 1 del plan de segunda oportunidad) recoge tambien
`interlocutor` y el nombre, por si Sara no llamo a la herramienta.

**Un telefono movil del dueno que de un empleado NO se usa para llamadas
automaticas.** Llamar al movil personal de alguien que no ha dado su permiso es otro
riesgo legal (la ley de telecomunicaciones pide consentimiento para llamadas
comerciales a personas). Se guarda como nota para Pablo, que decide. Sara vuelve a
llamar al fijo del negocio a la hora en que esta el responsable.

## La espera ("un segundo, ahora se pone")

- Herramienta de sistema de ElevenLabs para esperar en silencio (`skip_turn`, a
  verificar al implementarlo). Hoy, a los 7 s de silencio, Sara diria "¿sigues ahi?".
- Limite: si en unos 60 s no habla nadie, "vale, te llamo en otro momento", apunta
  la rellamada y cuelga.
- Probarlo con la voz real: la musica de espera o el ruido del salon no pueden contar
  como "ya se ha puesto".

## Volver a llamar a quien decide

- Si quedo nombre y cuando, el lanzador vuelve a llamar **al fijo del negocio** en
  esa franja (si cae fuera del horario de llamadas, en la franja mas cercana).
- El saludo cambia: "Hola, buenas. Soy Sara, una asistente virtual de Vantelia.
  ¿Hablo con Marta?" (variable `responsable` para la agente).
- Una sola rellamada dirigida por negocio, con la Lista Robinson consultada otra vez
  y respetando la baja si la piden.

## En el panel y en lo demas

- Panel "Llamadas": columnas "Con quien hablo" y "Responsable" (nombre y cuando).
- El correo de segunda oportunidad va "a la atencion de Marta" cuando se sabe.
- El aviso a Pablo de un interesado dice si hablo con el responsable o con alguien
  del equipo.

## Pruebas

- Tests del guion: la pregunta va despues del gancho y una sola vez; al cambiar de
  persona hay presentacion completa (IA, comercial, baja).
- Tests de la herramienta y de la rellamada dirigida (franja, Robinson, una sola vez,
  nunca al movil que da un empleado).
- Tres llamadas reales con Pablo:
  1. es el dueno;
  2. es un empleado que dice "un segundo" y pasa el telefono (otra persona o Pablo
     cambiando de voz tras 20-30 s);
  3. es un empleado que da el nombre y la hora del responsable.

## Esfuerzo

Un dia y medio. Encaja con la fase 1 del plan de segunda oportunidad
(`docs/PLAN_SEGUNDA_OPORTUNIDAD_LLAMADAS.md`): la clasificacion al terminar la llamada
se hace una vez para los dos. Probarlo en real necesita el numero 91 (o, para las
pruebas con Pablo, el numero de pruebas de EEUU, como hasta ahora).
