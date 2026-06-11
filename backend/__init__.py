"""Paquete backend de Vantelia (refactor F3, en curso).

`api.py` es el entrypoint de compatibilidad (`uvicorn api:app`); los modulos de
este paquete contienen la implementacion real a medida que se extrae del
monolito.

Convencion interna del paquete: entre modulos de backend/ se accede de forma
cualificada (`from backend import x` y luego `x.simbolo`), nunca
`from backend.x import simbolo` para funciones/constantes. Asi, parchear el
atributo en su modulo "home" (lo que hacen los tests via el proxy de api.py)
afecta a todos los llamadores. Excepcion permitida: clases, dataclasses y
modelos Pydantic.
"""
