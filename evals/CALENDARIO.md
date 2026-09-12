# Calendario del banco y del humo

Los guiones no deben asumir que mañana abre el negocio. `calendario.resolver_mensajes`
se ejecuta una vez por caso antes de hablar con el modelo; los dos intentos usan
las mismas fechas. La salida imprime los valores elegidos para comparar tiradas.

Marcadores:
- `{dia_abierto}`: fecha ISO futura con los huecos necesarios.
- `{dia_abierto_nombre}`: esa misma fecha con día de semana, mes y año en español.
- `{dia_cerrado}` y `{dia_cerrado_nombre}`: fecha sin horas de horario reservable;
  una agenda llena no se considera cerrada. No usar para probar simplemente ocupación.
- `{codigo}`: se conserva hasta preparar la cita de cancelación/reprogramación.

Ejemplo de configuración de caso:

```python
{
    "servicio_calendario": "valoracion",
    "horas_calendario": ["15:00"],
    "mensajes": ["quiero un alisado", "no lo tengo claro",
                 "el {dia_abierto}", "a las 15", "si"],
}
```

`valoracion` se resuelve al servicio de valoración del tenant; también se admite
el nombre de otro servicio. No escribe ni altera horarios, servicios o citas.
Consulta desde el día siguiente en la zona horaria del negocio, hasta 30 días.
Si no se encuentra el día/hueco requerido, el instrumento muestra **NO MEDIDO**,
no llama al modelo para ese caso y termina con código distinto de cero.
Eso es una medición incompleta, no una regresión demostrada del asistente.

Un guion que pruebe deliberadamente la palabra «mañana» debe declarar
`fecha_relativa_intencional: True`. No sirve como excepción para casos que
pretenden crear una cita. El test de los guiones vigila esta distinción.

`tests/calendario_de_pruebas.py` reutiliza el selector de fechas para la fixture
de estirar citas. Exige 10:00, 11:00 y 12:00, igual que el arreglo 02bd1a7.
Las pruebas cubren sábado y martes con reloj controlado, cierre frente a ocupación,
falta de huecos, conservación del código y resolución única antes de reintentar.

Barrido de hoy+1: los otros tests de creación ya filtraban domingos. Se mantienen
las fechas intencionales de recordatorios, interpretación y preparaciones por SQL.
El caso `test_servicio_desactivado_no_vacia_la_agenda` tiene una aserción condicional
que puede no ejercitarse en día cerrado; queda como deuda separada, sin afirmar
que esta búsqueda haya validado todos los instrumentos del repositorio.
