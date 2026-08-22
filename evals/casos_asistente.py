# -*- coding: utf-8 -*-
"""Banco de casos del asistente: lo que NUNCA puede fallar, y lo que deberia acertar.

POR QUE EXISTE
--------------
Los fallos aparecian en casa del cliente, de uno en uno, y cada arreglo era un
parche mas. Un banco de casos convierte eso en un NUMERO: cuando algo empeora se
ve aqui, en la misma tirada, y no en un WhatsApp de la duenya del salon.

Es la pieza que usan los equipos que ponen asistentes en produccion: no "probar a
ver", sino medir siempre lo mismo.

COMO SE LEE UN CASO
-------------------
    {
        "id": "precio-mechas",
        "gravedad": "critico",       # critico | importante | deseable
        "mensajes": ["cuanto cuestan unas mechas?"],
        "debe": ["diagnostico"],      # alguna de estas palabras
        "no_debe": ["€", "euros"],    # ninguna de estas
    }

`critico` es lo que no puede fallar NUNCA porque le cuesta dinero o credibilidad
al negocio: inventarse un precio, dar por hecha una cita que no existe, negar un
servicio que si hace. Si uno de esos falla, la tirada entera se da por mala.

Los casos salieron de romper el asistente escribiendo como una clienta real: con
faltas, partiendo frases, insistiendo y preguntando fuera de tema.
"""
from __future__ import annotations

# Cada caso corre en una conversacion limpia (telefono propio).
CASOS = [
    # ─── Lo que no puede fallar nunca ──────────────────────────────────────
    {
        "id": "precio-mechas-sin-cifra",
        "gravedad": "critico",
        "por_que": "El salon NO da precios de trabajos tecnicos sin ver el pelo.",
        "mensajes": ["cuanto cuestan unas mechas?"],
        "debe": ["diagnostico", "diagnóstico", "en persona", "valoracion", "valoración"],
        "no_debe": ["€", " euros"],
    },
    {
        "id": "precio-balayage-indirecto",
        "gravedad": "critico",
        "por_que": "Preguntado de otra forma tiene que dar igual.",
        "mensajes": ["mas o menos en cuanto se me queda un balayage?"],
        "debe": ["diagnostico", "diagnóstico", "en persona", "valoracion", "valoración"],
        "no_debe": ["€", " euros"],
    },
    {
        "id": "no-negar-servicio-que-existe",
        "gravedad": "critico",
        "por_que": "Decir que no haceis algo que si haceis es perder una clienta.",
        "mensajes": ["me haceis las cejas?"],
        "debe": ["cejas"],
        "no_debe": ["no realizamos", "no hacemos", "no ofrecemos"],
    },
    {
        "id": "no-dar-la-cita-por-hecha",
        "gravedad": "critico",
        "por_que": "Decirle que tiene cita cuando no la tiene es lo peor que puede pasar.",
        "mensajes": [
            "quiero cita para un corte de señora",
            "el jueves a las 17:00",
            "ya esta reservada no?",
        ],
        "debe": ["aun no", "aún no", "no esta reservada", "no está reservada",
                 "necesito", "falta"],
        # OJO al escribir un "no_debe": "esta reservada" tambien casa dentro de
        # "aun no esta reservada", que es justo la respuesta CORRECTA. Solo se
        # prohiben las formas que AFIRMAN que la cita existe.
        "no_debe": ["ya esta reservada", "ya está reservada", "queda reservada",
                    "queda confirmada", "esta confirmada", "está confirmada",
                    "te he apuntado", "te he reservado"],
    },
    {
        "id": "no-inventar-duraciones",
        "gravedad": "critico",
        "por_que": "Inventarse cuanto dura un servicio es igual de malo que el precio.",
        # Dos turnos a proposito: preguntar primero el largo es MEJOR que soltar
        # una duracion (varia por largo). Lo que se exige es que acabe dando una
        # duracion REAL, no una inventada.
        "mensajes": ["cuanto tiempo tengo que estar ahi para unas mechas?",
                     "lo tengo por los hombros"],
        "debe": ["min"],
        "no_debe": [],
    },
    {
        "id": "precio-cerrado-si-se-dice",
        "gravedad": "critico",
        "por_que": "Su catalogo SI tiene precio para corte: taparlo seria un paso atras.",
        "mensajes": ["cuanto vale un corte de señora?"],
        "debe": ["20"],
        "no_debe": [],
    },

    # ─── Las condiciones que pidio el salon ────────────────────────────────
    {
        "id": "gracias-a-ti",
        "gravedad": "importante",
        "por_que": "Lo pidio expresamente.",
        "mensajes": ["muchas gracias!"],
        "debe": ["gracias a ti"],
        "no_debe": [],
    },
    {
        "id": "presupuesto-alisado-pide-foto",
        "gravedad": "importante",
        "por_que": "Su norma: presupuesto de alisado = foto por detras.",
        "mensajes": ["me pasais presupuesto de un alisado?"],
        "debe": ["foto"],
        "no_debe": [],
    },
    {
        "id": "cita-alisado-sin-foto",
        "gravedad": "importante",
        "por_que": "Si solo quiere cita, NO se le pide foto: solo el largo.",
        "mensajes": ["quiero coger cita para un alisado"],
        "debe": [],
        "no_debe": ["foto"],
    },
    {
        "id": "extensiones-a-diagnostico",
        "gravedad": "importante",
        "por_que": "No dan precio de extensiones sin ver a la clienta.",
        "mensajes": ["cuanto me costarian unas extensiones?"],
        "debe": ["diagnostico", "diagnóstico", "en persona", "valoracion", "valoración",
                 "presupuesto"],
        "no_debe": [],
    },
    {
        "id": "telefono-si-no-encaja-nada",
        "gravedad": "importante",
        "por_que": "Antes de perder la cita, que llamen.",
        "mensajes": [
            "quiero cita para un corte de señora el jueves",
            "no me va bien ninguna de esas horas",
            "es que solo puedo por la noche",
        ],
        "debe": ["llamar", "llamanos", "llámanos", "625", "966"],
        "no_debe": [],
    },

    # ─── Saber cuando consultar ────────────────────────────────────────────
    {
        "id": "abiertos-ahora-es-de-hoy",
        "gravedad": "importante",
        "por_que": "Soltar el horario semanal no responde 'estais abiertos AHORA'.",
        "mensajes": ["estais abiertos ahora?"],
        "debe": ["ahora", "hoy", "cerrado", "cerrados", "abierto", "abiertos"],
        "no_debe": [],
    },
    {
        "id": "horario-escrito-manda",
        "gravedad": "importante",
        "por_que": "Lo que el negocio ha redactado gana a nuestras heuristicas.",
        "mensajes": ["cual es vuestro horario?"],
        "debe": ["lunes"],
        "no_debe": [],
    },
    {
        "id": "que-servicios-hay",
        "gravedad": "importante",
        "por_que": "Tiene que contar lo que SI hay, no una frase generica.",
        "mensajes": ["que me podeis hacer en el pelo?"],
        "debe": ["alisado", "color", "corte", "peinado", "tratamiento"],
        "no_debe": [],
    },

    # ─── Escribir como una clienta de verdad ───────────────────────────────
    {
        "id": "con-faltas",
        "gravedad": "importante",
        "por_que": "Nadie escribe bien por WhatsApp.",
        "mensajes": ["kiero pedir sita pa el jueves"],
        "debe": [],
        "no_debe": ["no he reconocido", "no entiendo"],
    },
    {
        "id": "frase-partida",
        "gravedad": "importante",
        "por_que": "Se manda media frase y se completa en el siguiente mensaje.",
        "mensajes": ["buenas queria una cita para hacerme unas mech", "*mechas perdon"],
        "debe": [],
        "no_debe": ["no he reconocido"],
    },
    {
        "id": "duda-a-media-cita",
        "gravedad": "importante",
        "por_que": "Preguntar algo a media reserva no puede romper el hilo.",
        "mensajes": ["quiero cita para un corte de señora", "oye y teneis parking?"],
        "debe": [],
        "no_debe": ["no he reconocido"],
    },
    {
        "id": "cambiar-de-idea-no-es-cambiar-de-cita",
        "gravedad": "importante",
        "por_que": "'no espera, mejor un corte' le pedia un numero de reserva.",
        "mensajes": ["hola, me quiero hacer la manicura", "no espera, mejor un corte"],
        "debe": [],
        "no_debe": ["R-XXXX", "numero de reserva", "número de reserva"],
    },
    {
        "id": "servicio-que-no-existe",
        "gravedad": "importante",
        "por_que": "Ser honesta y ofrecer lo que si hay.",
        "mensajes": ["hola, me quiero hacer la manicura"],
        "debe": ["alisado", "color", "corte", "peinado", "capilar", "pelo", "cabello"],
        "no_debe": [],
    },
    {
        "id": "sinsentido-no-rompe",
        "gravedad": "deseable",
        "por_que": "Basura y emojis sueltos no pueden dejarla muda.",
        "mensajes": ["asdfgh", "😂😂😂", "?"],
        "debe": [],
        "no_debe": [],
        "exige_respuesta": True,
    },
]
