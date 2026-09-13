# -*- coding: utf-8 -*-
"""Lo que el banco necesita saber de cada negocio para medirlo, declarado a mano.

POR QUE EXISTE
--------------
El banco nació con el salón piloto y sus mensajes nombraban SU catálogo («quiero
cita para un corte de señora»). Medir otro negocio con esas frases no mide nada:
pide un servicio que allí no existe y el caso sale roto sin que el asistente haya
hecho nada mal. La aceptación del candidato (13-sep-2026) exige medir Alicia y un
segundo negocio con configuración distinta.

`{un_servicio}` en un mensaje se sustituye por el servicio sencillo de ese negocio
(con su artículo, como lo escribiría una clienta). Para Alicia el texto resuelto
es EXACTAMENTE el de antes, así que sus mediciones siguen siendo comparables. Un
negocio sin servicio declarado aquí queda NO MEDIDO en esos casos: nunca se elige
uno por él.
"""
from __future__ import annotations

SERVICIO_DE_PRUEBA = {
    "alicia_rincon_estilistas": "un corte de señora",
    # Negocio de la revisión de Meta: catálogo de sesiones genéricas.
    "metareview": "una sesion estandar",
}
