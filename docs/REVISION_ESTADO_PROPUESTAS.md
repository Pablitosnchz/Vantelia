# Revisión de c22cc42 / bb4083b

Revisión de Claude recibida el 12-sep. Se corrige en astra/estado-propuestas y se
integra aquí la arquitectura 6d00071; no se considera todavía versión final.

1. **Rechazo que se repite:** ambos caminos consultan `rechazo_de_regla_de_precio`.
   El rechazo se asocia al id de la regla ofrecida, nunca a la capitalización o
   al nombre público frente al Pack. Otra regla o tenant no hereda esa negativa.
2. **Intención tras cancelar:** `contexto_para_ofrecer_reserva` abre la nueva
   reserva solo si la cancelación se ejecutó y hay creación pendiente. Conserva
   la cancelación y desmarca terminado para la nueva reserva. Una reprogramación
   activa no se convierte en reserva ni provoca ValueError en el canal.
3. **Tarjeta Q&A:** ya corregida por 0c9dc22 y 6d10eba. Una prueba ejecuta las
   funciones reales de JavaScript con datos de negocio vacío y comprueba que las
   reglas son visibles y las respuestas por palabra clave siguen ocultas.
4. **Centro sin valoración:** el freno consulta el mismo centro que el canal.
   Si no está disponible, conserva la explicación del negocio y remite al centro;
   no cambia de ubicación, no crea oferta ficticia ni promete consultar después.
5. **Fallo del interactivo:** respaldo con texto; solo el acuse de ese texto
   acredita oferta si fallaron los botones. Si fallan ambos, sigue preparada.
6. **Siguiente paso:** al rechazar se continúa con el servicio original y se abre
   el resumen si están los datos; al aceptar con fecha se nombra el día y se
   consultan huecos del servicio aceptado. No se reutiliza la hora del tratamiento.

Evidencia en tests/test_revision_rechazo_diagnostico.py,
tests/test_reglas_tarjetas_qa.py y las suites existentes de propuestas/precio.
La mutación que ignora el rechazo hace fallar las variantes Pack/mayúsculas.
La ausencia de centro, el cambio de intención y el respaldo de texto dieron rojo.
Validación: 67 dirigidos de base, 11 de cierre y 68 de integración con 6d00071
verdes (grupos solapados). Pyflakes limpio. La revisión exacta sigue pendiente
de resolver los fallos de demos y pasar una única suite completa del conjunto.

Independiente: 6d00071 terminó con 2261 correctos, 1 omitido y cinco fallos en
test_demo_conversion. Claude tiene un encargo acotado para aislar su causa;
no se afirma que esa suite esté verde. No push ni despliegue.
