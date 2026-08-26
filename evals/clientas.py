# -*- coding: utf-8 -*-
"""Clientas de mentira para probar el asistente en serio.

POR QUE EXISTE
--------------
El banco de casos (`casos_asistente.py`) son 28 guiones ESCRITOS A MANO. Sirven
para que un fallo conocido no vuelva, pero solo prueban las 28 formas que se le
ocurrieron a quien los escribio. Los fallos que aparecen en casa del cliente
vienen de las otras mil.

Aqui la clienta la hace un modelo: se le da una PERSONA (que quiere, como
escribe, como se comporta) y habla sola con el asistente hasta que consigue lo
suyo o se cansa. Cien conversaciones distintas en una tirada, ninguna igual a la
anterior.

QUE MIDE
--------
Lo mismo que importa en el salon:

    ¿acabo habiendo la cita que queria, en la agenda de verdad?
    ¿se atasco por el camino?
    ¿le dijo algo falso?

COMO SE ANADE UNA CLIENTA
-------------------------
Una entrada mas en PERSONAS. `objetivo` decide como se juzga la conversacion;
`estilo` es como escribe (y es donde estan los fallos: nadie escribe como en los
guiones). `familia` es contra que se comprueba que la cita sea la CORRECTA, no
solo que exista.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Como escribe la gente de verdad. Cada uno es una instruccion para el modelo que
# hace de clienta; se combinan con los objetivos para no repetir conversacion.
ESTILOS: Dict[str, str] = {
    "normal": "Escribes con normalidad, frases cortas, sin mayusculas al empezar.",
    "faltas": (
        "Escribes con FALTAS de ortografia y sin acentos ('kiero', 'ora', 'pa', "
        "'q'), como quien escribe rapido desde el movil."
    ),
    "partida": (
        "Partes cada idea en VARIOS mensajes cortos: dices media frase, la envias, "
        "y completas en el siguiente. A veces te cortas a media palabra y lo "
        "arreglas en el mensaje siguiente."
    ),
    "indecisa": (
        "No lo tienes claro: preguntas, dudas entre dos opciones, pides consejo "
        "('¿tu que me recomiendas?') antes de decidirte."
    ),
    "cambia": (
        "A mitad de la conversacion CAMBIAS de idea: te habias decidido por una "
        "cosa y de pronto prefieres otra, o el dia que dijiste ya no te va bien."
    ),
    "insiste": (
        "Insistes: si no te convence lo que te ofrecen, lo dices y pides otra cosa. "
        "Si te preguntan algo que ya has contestado, lo haces notar."
    ),
    "escueta": (
        "Contestas con una o dos palabras. No das mas informacion de la que te "
        "piden, ni la adelantas."
    ),
    "habladora": (
        "Te enrollas: cuentas por que quieres el cambio de look, mencionas a tu "
        "hermana, preguntas cosas de paso. La informacion util va mezclada."
    ),
}

# Que viene a hacer. El objetivo decide como se juzga el resultado.
PERSONAS: List[Dict[str, Any]] = [
    {
        "id": "corte-directo",
        "objetivo": "reservar",
        "familia": "corte",
        "quiere": "cortarte el pelo, nada mas: un corte de senyora",
        "estilos": ["normal", "faltas", "escueta", "partida"],
    },
    {
        "id": "corte-nino",
        "objetivo": "reservar",
        "familia": "corte",
        "quiere": "cortarle el pelo a tu hijo de 7 anyos",
        "estilos": ["normal", "habladora"],
    },
    {
        "id": "mechas-precio",
        "objetivo": "preguntar_precio",
        "familia": "mechas",
        "quiere": "saber cuanto te costarian unas mechas antes de decidirte",
        "estilos": ["normal", "insiste", "faltas"],
    },
    {
        "id": "mechas-reserva",
        "objetivo": "reservar",
        "familia": "mechas",
        "quiere": (
            "hacerte mechas; tienes el pelo por los hombros y no sabes que tecnica "
            "quieres, te dejas aconsejar"
        ),
        "estilos": ["indecisa", "partida", "normal"],
    },
    {
        "id": "alisado-presupuesto",
        "objetivo": "preguntar_precio",
        "familia": "alisado",
        "quiere": "que te digan cuanto vale un alisado, que lo tienes muy largo",
        "estilos": ["normal", "insiste"],
    },
    {
        "id": "recomendacion",
        "objetivo": "consejo",
        "familia": "",
        "quiere": (
            "que te aconsejen: se te cae mucho el pelo y no sabes que hacerte, "
            "quieres que te digan que tratamiento te va bien"
        ),
        "estilos": ["indecisa", "habladora", "faltas"],
    },
    {
        "id": "cambia-de-idea",
        "objetivo": "reservar",
        "familia": "corte",
        "quiere": (
            "al principio unas mechas, pero a mitad de conversacion decides que "
            "solo quieres cortarte las puntas"
        ),
        "estilos": ["cambia", "normal"],
    },
    {
        "id": "cancelar",
        "objetivo": "cancelar",
        "familia": "",
        "con_cita": True,
        "quiere": "anular la cita que tienes cogida, que te ha surgido algo",
        "estilos": ["normal", "escueta", "faltas"],
    },
    {
        "id": "cambiar-hora",
        "objetivo": "reprogramar",
        "familia": "",
        "con_cita": True,
        "quiere": "mover tu cita a otro dia porque no puedes ir el que tienes",
        "estilos": ["normal", "partida", "insiste"],
    },
    {
        "id": "horario",
        "objetivo": "informacion",
        "familia": "",
        "quiere": "saber a que hora abren hoy y si abren los sabados",
        "estilos": ["normal", "escueta"],
    },
    {
        "id": "servicio-que-no-hacen",
        "objetivo": "informacion",
        "familia": "",
        "quiere": "preguntar si te pueden hacer la manicura y las unyas de gel",
        "estilos": ["normal", "insiste"],
    },
    {
        "id": "sin-hueco",
        "objetivo": "reservar",
        "familia": "corte",
        "quiere": (
            "cita para un corte, pero SOLO te viene bien un dia que esta cerrado o "
            "muy tarde; rechazas las dos primeras horas que te ofrezcan"
        ),
        "estilos": ["insiste", "normal"],
    },
]


def guion(persona: Dict[str, Any], estilo: str) -> str:
    """Las instrucciones para el modelo que hace de clienta."""
    import datetime

    hoy = datetime.date.today()
    partes = [
        "Eres una clienta escribiendo por WhatsApp a una peluqueria. NO eres un "
        "asistente: eres la clienta, y escribes como una persona normal.",
        "",
        "LO QUE QUIERES: %s." % persona["quiere"],
        "",
        "COMO ESCRIBES: %s" % ESTILOS[estilo],
        "",
        "REGLAS:",
        "- Un mensaje corto por turno, como en WhatsApp. Nada de parrafos largos.",
        "- No digas que eres una prueba ni menciones que esto es un test.",
        "- Si te preguntan tu nombre, invéntate uno normal y dilo.",
        "- Si te ofrecen una hora que te vale, aceptala; no alargues por alargar.",
        # Sin esto daba la cita por hecha al ver el RESUMEN -que todavia no es una
        # cita- y contestaba LISTO. Medido: se contaban como "se fue sin cita"
        # conversaciones en las que el asistente lo habia hecho todo bien y solo
        # faltaba que ella pulsara "Confirmar".
        "- Si te mandan un resumen y te preguntan si confirmas, la cita AUN NO "
        "existe: responde 'confirmo'. Solo esta hecha cuando te lo digan.",
        "- Cuando ya tengas lo que querias (o veas que no vas a conseguirlo), "
        "responde EXACTAMENTE: LISTO",
        "- Si te piden algo que ya has dicho, hazlo notar en vez de repetirlo sin mas.",
        # Sin saber en que dia vive, la clienta de mentira se inventaba fechas
        # ("mañana es viernes 27 de octubre") y daba por rotas reservas correctas.
        "- HOY es %s. Cuando hables de dias, cuenta desde ahi y no discutas la "
        "fecha si te la dan bien." % hoy.isoformat(),
    ]
    if persona.get("con_cita"):
        # Con solo el codigo, la clienta de mentira no sabia QUE cita tenia y se
        # ponia a discutir ("no era de acido lactico, era de pelo"), lo que daba
        # por rotas cancelaciones que habian ido bien.
        partes.append(
            "- Ya tienes una cita cogida: {servicio}, el {cuando}. Si te piden el "
            "numero de reserva, es {codigo}."
        )
    return "\n".join(partes)


def combinaciones() -> List[Dict[str, Any]]:
    """Todas las clientas: cada persona por cada una de sus formas de escribir."""
    salida = []
    for persona in PERSONAS:
        for estilo in persona["estilos"]:
            salida.append({"persona": persona, "estilo": estilo,
                           "id": "%s/%s" % (persona["id"], estilo)})
    return salida
