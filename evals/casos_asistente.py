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
        "agenda": "crea",             # y que quede en la AGENDA: crea|no_crea|
                                      # cancela|cambia
        "con_cita": True,             # se le deja una cita cogida antes de empezar;
                                      # {codigo} en los mensajes es la suya
    }

Lo de `agenda` importa: un asistente puede decir "listo, te he apuntado" y no
haber tocado la agenda. Lo que se mide es el efecto, no la frase.

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
        # Solo tiene sentido donde el negocio NO da ese precio por
        # mensaje. Sin esto, una copia mal configurada lo daba por roto.
        "solo_si": "sin_precio:mechas balayage color",
        "por_que": "El salon NO da precios de trabajos tecnicos sin ver el pelo.",
        "mensajes": ["cuanto cuestan unas mechas?"],
        "debe": ["diagnostico", "diagnóstico", "en persona", "valoracion", "valoración"],
        "no_debe": ["€", " euros"],
    },
    {
        "id": "precio-balayage-indirecto",
        "gravedad": "critico",
        # Solo tiene sentido donde el negocio NO da ese precio por
        # mensaje. Sin esto, una copia mal configurada lo daba por roto.
        "solo_si": "sin_precio:mechas balayage color",
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
        # Sin `debe` de vocabulario: "todavia no esta reservada", "esa hora no la
        # tienes cogida" y "me falta un dato" son igual de correctas. Lo que se
        # exige es lo objetivo: que NO afirme que existe y que no haya cita.
        "agenda": "no_crea",
        "debe": [],
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
        # Solo aplica si el negocio publica precios. El salon decidio despues que
        # NO se dan por mensaje ("es mas facil que no de precio de nada"), y con
        # eso puesto este caso pedia justo lo contrario que su dueña. Un banco de
        # casos no puede contradecir lo que el negocio ha decidido.
        "solo_si": "precios_visibles",
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
        "por_que": "Ser honesta: lo que no se hace, no se hace.",
        # Lo que importa es que lo diga claro y no coja una cita de algo que no
        # existe. Que ademas ofrezca alternativas es deseable, pero exigir que
        # nombre un servicio concreto es medir vocabulario: "tenemos variedad de
        # servicios, ¿te cuento?" tambien es una buena respuesta.
        "mensajes": ["hola, me quiero hacer la manicura"],
        "debe": ["no ofrecemos", "no hacemos", "no tenemos", "no realizamos",
                 "no disponemos", "no contamos"],
        "no_debe": [],
        "agenda": "no_crea",
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

    # ─── Que la cita ocurra de verdad, no solo que lo diga ─────────────────
    {
        "id": "reserva-completa-de-verdad",
        "gravedad": "critico",
        "por_que": "Es a lo que viene el negocio: que la cita acabe en la agenda.",
        "mensajes": [
            "hola quiero cita para un corte de señora",
            "el primer hueco que tengas",
            "me llamo Marta Ruiz",
            "si, confirmo",
        ],
        "agenda": "crea",
        "debe": [],
        "no_debe": [],
    },
    {
        "id": "cancelar-de-verdad",
        "gravedad": "critico",
        "por_que": "Si dice que la cancela y no la cancela, el hueco se pierde.",
        "con_cita": True,
        "mensajes": ["hola quiero anular mi cita", "{codigo}", "si, cancelala"],
        "agenda": "cancela",
        "debe": ["cancel", "anulad"],
        "no_debe": [],
    },
    {
        "id": "cambiar-la-hora-de-verdad",
        "gravedad": "importante",
        "por_que": "Reprogramar tiene que mover la cita, no crear otra.",
        "con_cita": True,
        # Cuatro turnos porque mover una cita SIN que elija hora seria peor:
        # ofrecer y esperar a que diga cual es lo correcto.
        "mensajes": [
            "buenas, necesito cambiar mi cita de dia",
            "{codigo}",
            "cualquier otro hueco que tengas me vale",
            "vale, la primera opcion que me has dicho",
        ],
        "agenda": "cambia",
        "debe": [],
        "no_debe": [],
    },
    {
        "id": "no-coge-cita-sin-que-lo-pidan",
        "gravedad": "critico",
        "por_que": "Preguntar un precio no es pedir hora.",
        "mensajes": ["cuanto vale un corte de señora?"],
        "agenda": "no_crea",
        "debe": [],
        "no_debe": [],
    },

    # ─── Como pidio el salon que hable ─────────────────────────────────────
    {
        "id": "sin-formulario-se-habla",
        "gravedad": "importante",
        "por_que": "Pidio que la IA le guie hablando, no que le suelte un formulario.",
        "mensajes": ["quiero hacerme mechas"],
        "debe": [],
        "no_debe": ["formulario", "rellena el", "completa el formulario"],
    },
    {
        "id": "recomienda-ante-un-problema",
        "gravedad": "importante",
        "por_que": (
            "Con 186 servicios planos proponia un ALISADO a quien se le caia el "
            "pelo. Tiene que entender el problema, no buscar por parecido."
        ),
        "mensajes": ["se me esta cayendo mucho el pelo, que me recomiendas?"],
        "debe": [],
        "no_debe": ["alisado", "keratina"],
    },
    {
        "id": "no-elige-el-servicio-por-ella",
        "gravedad": "critico",
        "por_que": (
            "Al pulsar 'Agendar cita', sin que nadie dijera nada, contesto 'vamos a "
            "agendar tu cita para el Acido Lactico Bio Premium - Muy Corto': el "
            "PRIMER servicio del catalogo. Elegirle un tratamiento de 260 EUR no es "
            "un detalle."
        ),
        "mensajes": ["quiero agendar una cita"],
        "debe": [],
        "no_debe": ["acido lactico", "ácido láctico", "vamos a agendar tu cita para el"],
        "agenda": "no_crea",
    },
    {
        "id": "pregunta-el-dia-en-vez-de-recitar",
        "gravedad": "importante",
        "por_que": (
            "Soltaba diez fechas de golpe. Una persona pregunta cuando te viene bien "
            "y mira ESE dia."
        ),
        # No se mide por vocabulario ("¿que dia te viene bien?" y "¿te va bien el
        # martes?" valen las dos), sino por lo unico objetivo: que no le suelte un
        # puñado de horas de un dia que ha elegido el.
        "mensajes": ["hola, quiero pedir cita para un corte de señora"],
        "sin_horas": True,
        "debe": [],
        "no_debe": [],
    },
    {
        "id": "varios-servicios-no-reserva-uno-corto",
        "gravedad": "critico",
        "por_que": (
            "26-ago-2026, salon piloto. Fue sumando por WhatsApp: corte de senora, "
            "'cortarme y secarme tambien', el elumen y 'he pensado que quiero un "
            "alisado'. La cita creada fue 'Corte senora' de 14:00 a 14:20: VEINTE "
            "MINUTOS para cuatro servicios. Los otros tres desaparecieron sin aviso "
            "y el salon se habria encontrado a una clienta que viene a estar tres "
            "horas en un hueco de veinte minutos."
        ),
        "mensajes": [
            "hola quiero un corte de señora",
            "pero quiero cortarme y secarme tambien",
            "tambien quisiera hacer el elumen",
            "he pensado que quiero un alisado",
            "el jueves por la tarde me viene bien",
            "me llamo Ana Ruiz",
        ],
        # No hay ningun servicio de su catalogo que cubra las cuatro cosas, asi
        # que lo correcto es NO reservar y decirle que lo cuadren por telefono.
        # Reservar una de las cuatro es el fallo que trae este caso.
        "agenda": "no_crea",
        "debe": [],
        "no_debe": [],
    },
    {
        "id": "duracion-depende-del-largo",
        "gravedad": "importante",
        "por_que": (
            "Queja literal de la duenya: 'tendria que preguntar cual es tu largo "
            "para que la informacion que le hemos metido le sirva'. Ese tratamiento "
            "va de 30 a 180 minutos segun el pelo, y contestaba una cifra suelta."
        ),
        "mensajes": ["cuanto tarda el acido lactico bio premium?"],
        # Vale preguntarle el largo o darle el abanico: lo que no vale es una
        # cifra a secas como si fuera igual para todo el mundo.
        "debe": ["largo", "depende", "segun", "según", "pelo"],
        "no_debe": [],
    },
    {
        "id": "cuanto-tarda-lo-que-ya-ha-elegido",
        "gravedad": "critico",
        "por_que": (
            "La captura que mando la duenya: habia pedido corte y secado, pregunto "
            "'que suele tardar?' y el asistente contesto que el tiempo puede variar "
            "y que mejor hacer una CITA DE VALORACION. La duracion estaba en su "
            "catalogo todo el rato. Sus palabras: 'que ponga que hagamos un "
            "diagnostico para un corte y un secador no tiene sentido'."
        ),
        "mensajes": ["hola quiero un corte de señora", "que suele tardar?"],
        "debe": ["minuto"],
        "no_debe": ["valoracion", "valoración", "diagnostico", "diagnóstico"],
    },
]
