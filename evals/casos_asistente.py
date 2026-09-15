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
        "horario_semanal": True,      # cuenta la SEMANA, no solo hoy/mañana
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
    {
        "id": "dice-que-si-y-acaba-en-cita",
        "gravedad": "critico",
        "solo_si": "sin_precio:mechas balayage color",
        "por_que": ("Conversacion real del 9-sep-2026: le ofrecieron hora, dijo que si "
                    "TRES veces y se quedo sin cita. El freno de 'cita sin pedirla' "
                    "bloqueo la creacion cinco veces seguidas porque el asistente "
                    "escribio 'te reserve' y la lista de frases tenia 'te reservo'."),
        # El nombre va al final porque en el banco la clienta es DESCONOCIDA: por
        # WhatsApp el telefono ya la identifica y no se lo piden. Lo que se mide es
        # lo mismo: que decir "si" a una hora ofrecida termine en cita.
        # Nombre y DOS apellidos desde el 11-sep-2026 (decision de Pablo): a una
        # clienta nueva se le piden los dos, asi que con uno solo esta conversacion
        # se quedaba en "¿y tu segundo apellido?" y no llegaba a medir lo suyo.
        "servicio_calendario": "valoracion",
        "horas_calendario": ["15:00"],
        "mensajes": ["quiero un alisado", "no lo tengo claro", "el {dia_abierto}",
                     "a las 15", "si", "me llamo Ana Ruiz Perez"],
        # En WhatsApp la cita NACE al pulsar el boton del resumen, no antes: el
        # final bueno de esta conversacion es el resumen para confirmar. Pedir
        # aqui `agenda: crea` seria pedir que la cita naciera sin que ella la
        # confirme, que es justo lo que el canal evita a proposito.
        "debe": ["Resumen de tu cita", "Confirmamos"],
        # Cualquier resumen NO vale. 13-sep-2026, referencia con el codigo de
        # produccion (bd7a6da): el reintento "aprobo" con un resumen de "Acido
        # lactico bio premium corto, 1 h 30 min, fianza 50 EUR" a nombre de
        # "clienta", a quien habia dicho "no lo tengo claro" y "me llamo Ana Ruiz
        # Perez". Le eligio la tecnica y le invento el nombre. El resumen tiene que
        # ser el de la cita de diagnostico (decision de Alicia, 13-sep) y a su nombre.
        "no_debe_en": "ultima",
        "no_debe": ["acido lactico", "ácido láctico", "keratina", "clienta"],
    },
    # ─── La prueba de la duenya por WhatsApp, 15-sep-2026 ──────────────────
    {
        "id": "cambia-de-mechas-a-grey-blending",
        "gravedad": "critico",
        "solo_si": ["tiene_servicio:mechas", "tiene_servicio:grey blending"],
        "por_que": ("Prueba de la duenya del 15-sep-2026: pidio mechas, dio el largo, cambio de "
                    "idea a grey blending y dio largo, dia y hora. El freno de varios servicios le "
                    "pregunto '¿mechas o grey blending?' y en el MISMO turno le llego el resumen "
                    "con Jose, que no hace grey blending. Confirmo sin contestar la pregunta."),
        "servicio_calendario": "Pack grey blending medio",
        "horas_calendario": ["10:30"],
        "mensajes": ["Quiero coger una cita para hacerme unas mechas",
                     "Pues tengo el cabello por los hombros yo creo que medio",
                     "Pues quiero un grey blindin", "Medio", "Y prefiero por las mañanas",
                     "el {dia_abierto_nombre} a las 10:30", "me llamo Ana Ruiz Perez"],
        # El final bueno es el resumen (la cita nace al pulsar el boton), sin volver a
        # preguntarle si queria las mechas y con quien hace grey blending segun su Excel.
        "debe": ["Resumen de tu cita"],
        "no_debe": ["cual de los dos", "o las mechas", "Jose", "Lucia"],
    },
    # ─── La demo del 8-sep-2026, delante de la duenya ──────────────────────
    {
        "id": "palabra-suelta-no-es-un-servicio",
        "gravedad": "critico",
        "por_que": ("Un dia, una hora o un 'vale' se tomaban por el nombre de un "
                    "servicio: 'veo que mencionas manana, pero no tengo un servicio "
                    "con ese nombre'. Misma forma que el 'gracias' del 4-sep."),
        "fecha_relativa_intencional": True,  # Comprueba interpretar la palabra, no reservar ese día.
        "mensajes": ["mañana"],
        "no_debe": ["no tengo un servicio", "con ese nombre", "no existe un servicio"],
    },
    {
        "id": "el-si-al-diagnostico-vale",
        "gravedad": "critico",
        "solo_si": "sin_precio:mechas balayage color",
        "por_que": ("Le ofrecio el diagnostico, ella dijo 'si', y siguio con el "
                    "alisado preguntandole el largo. Tuvo que escribir 'quiero el "
                    "diagnostico' dos turnos despues para que se lo cogieran."),
        "mensajes": ["quiero un alisado", "no estoy segura de cual", "si"],
        "debe": ["diagnostico", "diagnóstico", "valoracion", "valoración"],
    },
    {
        "id": "no-elige-la-tecnica-por-ella",
        "gravedad": "critico",
        "solo_si": "sin_precio:mechas balayage color",
        "por_que": ("Dijo dos veces que no podia elegir sin verle el pelo y a los "
                    "dos mensajes le reservo el acido lactico 'y si en la cita "
                    "prefieres la keratina, se puede cambiar'. Se lo pedia nuestra "
                    "propia nota anti-repeticion."),
        "servicio_calendario": "valoracion",
        "horas_calendario": ["10:00"],
        "mensajes": ["quiero un alisado", "no estoy segura de cual", "lo tengo corto",
                     "el {dia_abierto_nombre} a las 10"],
        "no_debe": ["se puede cambiar"],
        "no_debe_en": "ultima",
    },
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
        "solo_si": ["tiene_servicio:cejas"],
        "gravedad": "critico",
        "por_que": "Decir que no haceis algo que si haceis es perder una clienta.",
        "mensajes": ["me haceis las cejas?"],
        "debe": ["cejas"],
        "no_debe": ["no realizamos", "no hacemos", "no ofrecemos"],
    },
    {
        "id": "no-dar-la-cita-por-hecha",
        "horas_calendario": ["17:00"],
        "no_debe_en": "ultima",
        "gravedad": "critico",
        "por_que": "Decirle que tiene cita cuando no la tiene es lo peor que puede pasar.",
        "mensajes": [
            "quiero cita para {un_servicio}",
            "el {dia_abierto_nombre} a las 17:00",
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
        "solo_si": ["tiene_servicio:mechas"],
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
        "solo_si": ["precios_visibles", "tiene_servicio:corte"],
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
        "solo_si": ["tiene_servicio:alisado", "tiene_regla:pedir_foto"],
        "gravedad": "importante",
        "por_que": "Su norma: presupuesto de alisado = foto por detras.",
        "mensajes": ["me pasais presupuesto de un alisado?"],
        "debe": ["foto"],
        "no_debe": [],
    },
    {
        "id": "cita-alisado-sin-foto",
        "solo_si": ["tiene_servicio:alisado"],
        "gravedad": "importante",
        "por_que": "Si solo quiere cita, NO se le pide foto: solo el largo.",
        "mensajes": ["quiero coger cita para un alisado"],
        "debe": [],
        "no_debe": ["foto"],
    },
    {
        "id": "extensiones-a-diagnostico",
        "solo_si": ["tiene_servicio:extensiones"],
        "gravedad": "importante",
        "por_que": "No dan precio de extensiones sin ver a la clienta.",
        "mensajes": ["cuanto me costarian unas extensiones?"],
        "debe": ["diagnostico", "diagnóstico", "en persona", "valoracion", "valoración",
                 "presupuesto"],
        "no_debe": [],
    },
    {
        "id": "telefono-si-no-encaja-nada",
        "solo_si": ["telefono_publicado"],
        "gravedad": "importante",
        "por_que": "Antes de perder la cita, que llamen.",
        "mensajes": [
            "quiero cita para {un_servicio} el {dia_abierto_nombre}",
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
        # Con "debe": ["lunes"] pasaba el domingo («mañana, lunes») y suspendia el lunes
        # («mañana, martes»), sin dar el horario ninguno de los dos: medía el calendario
        # (14-sep-2026). `horario_semanal` no cuenta los dias pegados a hoy/mañana.
        "debe": [],
        "horario_semanal": True,
        "no_debe": [],
    },
    {
        "id": "que-servicios-hay",
        "solo_si": ["tiene_servicio:corte", "tiene_servicio:alisado"],
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
        "mensajes": ["kiero pedir sita pa el {dia_abierto_nombre}"],
        "debe": [],
        "no_debe": ["no he reconocido", "no entiendo"],
    },
    {
        "id": "frase-partida",
        "solo_si": ["tiene_servicio:mechas"],
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
        "mensajes": ["quiero cita para {un_servicio}", "oye y teneis parking?"],
        "debe": [],
        "no_debe": ["no he reconocido"],
    },
    {
        "id": "cambiar-de-idea-no-es-cambiar-de-cita",
        "solo_si": ["no_tiene_servicio:manicura", "tiene_servicio:corte"],
        "gravedad": "importante",
        "por_que": "'no espera, mejor un corte' le pedia un numero de reserva.",
        "mensajes": ["hola, me quiero hacer la manicura", "no espera, mejor un corte"],
        "debe": [],
        "no_debe": ["R-XXXX", "numero de reserva", "número de reserva"],
    },
    {
        "id": "servicio-que-no-existe",
        "solo_si": ["no_tiene_servicio:manicura"],
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
            "hola quiero cita para {un_servicio}",
            "el primer hueco que tengas",
            # Nombre y dos apellidos: es una clienta NUEVA por WhatsApp
            # (decision de Pablo, 11-sep-2026). Con uno solo, esta conversacion se
            # quedaba en "¿y tu segundo apellido?" y no medía si la cita acaba en
            # la agenda, que es lo suyo.
            "me llamo Marta Ruiz Gomez",
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
        # ofrecer y esperar a que diga cual es lo correcto. El quinto, «si», acepta
        # el resumen del cambio: desde el 15-sep-2026 por WhatsApp no se mueve sin
        # aceptarlo (decision de Pablo; tests/test_reprogramar_desde_el_agente.py).
        "mensajes": [
            "buenas, necesito cambiar mi cita de dia",
            "{codigo}",
            "cualquier otro hueco que tengas me vale",
            "vale, la primera opcion que me has dicho",
            "si",
        ],
        "agenda": "cambia",
        "debe": [],
        "no_debe": [],
    },
    {
        "id": "no-coge-cita-sin-que-lo-pidan",
        "gravedad": "critico",
        "por_que": "Preguntar un precio no es pedir hora.",
        "mensajes": ["cuanto vale {un_servicio}?"],
        "agenda": "no_crea",
        "debe": [],
        "no_debe": [],
    },

    # ─── Como pidio el salon que hable ─────────────────────────────────────
    {
        "id": "sin-formulario-se-habla",
        "solo_si": ["tiene_servicio:mechas"],
        "gravedad": "importante",
        "por_que": "Pidio que la IA le guie hablando, no que le suelte un formulario.",
        "mensajes": ["quiero hacerme mechas"],
        "debe": [],
        "no_debe": ["formulario", "rellena el", "completa el formulario"],
    },
    {
        "id": "recomienda-ante-un-problema",
        "solo_si": ["tiene_servicio:alisado"],
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
        "mensajes": ["hola, quiero pedir cita para {un_servicio}"],
        "sin_horas": True,
        "debe": [],
        "no_debe": [],
    },
    {
        "id": "varios-servicios-no-reserva-uno-corto",
        "solo_si": ["tiene_servicio:alisado", "tiene_servicio:elumen", "tiene_servicio:secado"],
        "horas_calendario": ["17:00"],
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
            "el {dia_abierto_nombre} a las 17:00 me viene bien",
            # Con un solo apellido este caso pasaba por el motivo equivocado: lo
            # frenaba la pregunta de los apellidos, no el freno de varios
            # servicios que es lo que viene a vigilar.
            "me llamo Ana Ruiz Perez",
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
        "solo_si": ["tiene_servicio:acido lactico"],
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
        "mensajes": ["hola quiero {un_servicio}", "que suele tardar?"],
        "debe": ["minuto"],
        "no_debe": ["valoracion", "valoración", "diagnostico", "diagnóstico"],
    },
    # ─── Lo que rompio la confianza del salon piloto (2-sep-2026) ──────────
    #
    # Los cuatro salieron de conversaciones REALES de la duenya probando su propio
    # asistente. Los tres primeros tienen la misma raiz, ya arreglada: al agente le
    # llegaba la frase fija "Quiero coger cita." en vez de lo que ella escribia.
    {
        "id": "no-quiero-diagnostico-quiero-cita",
        "solo_si": ["tiene_servicio:mechas"],
        "gravedad": "critico",
        "por_que": (
            "Lo dijo TRES veces -'no quiero cita para diagnostico, quiero cita para "
            "hacermelas'- y el asistente siguio ofreciendole el diagnostico hasta "
            "mandarla a llamar por telefono. No la ignoraba: su mensaje se perdia "
            "antes de llegar al agente. Es el fallo que le hizo dudar del producto."
        ),
        "mensajes": [
            "quiero unas mechas y tengo el pelo largo",
            "no quiero cita para diagnostico, quiero cita para hacermelas",
        ],
        # Ofrecerlo la PRIMERA vez es su politica configurada y esta bien. Lo que
        # se mide es la respuesta de despues, cuando ella ya ha dicho que no.
        "no_debe_en": "ultima",
        "debe": [],
        # Insistir en el diagnostico despues de que lo rechace, o mandarla a
        # llamar, es exactamente lo que hizo perder la conversacion.
        "no_debe": ["diagnostico", "diagnóstico", "llamarnos", "que nos llames"],
    },
    {
        "id": "no-negar-el-servicio-por-como-se-llama-en-el-catalogo",
        "solo_si": ["tiene_servicio:mechas"],
        "gravedad": "critico",
        "por_que": (
            "'Carino, no tengo un servicio especifico llamado mechas' a un salon que "
            "tiene 31 servicios de mechas. Pasa porque busca la frase de la clienta "
            "en el catalogo y anuncia el fallo en vez de resolverlo."
        ),
        "mensajes": ["quiero una cita para hacerme unas mechas"],
        "debe": [],
        "no_debe": [
            "no tengo un servicio", "no tenemos un servicio",
            "no existe ese servicio", "no encuentro ese servicio",
        ],
    },
    {
        "id": "no-enumerar-las-variantes-del-catalogo",
        "solo_si": ["tiene_servicio:mechas"],
        "gravedad": "importante",
        "por_que": (
            "Le solto la lista interna: 'Mechas media cabeza-extra largo, Mechas "
            "corto, Mechas medio, Mechas corto-med. Cual de estas te gustaria?'. "
            "Esos nombres son de cocina y la clienta no puede elegir entre ellos. "
            "Lo que hay que preguntar es como tiene el pelo de largo."
        ),
        # Lo que este caso vigila DE VERDAD es `no_debe`: los nombres de cocina.
        # `debe` acepta las dos salidas correctas porque las dos lo son para este
        # negocio: preguntarle el largo, o mandarla al diagnostico, que es lo que
        # su propia regla ("Color y mechas: precio tras valoracion") dice que hay
        # que hacer con las mechas. Exigiendo solo "largo", el caso fallaba una de
        # cada dos tiradas segun lo que decidiera el clasificador, y castigaba una
        # respuesta que la duenya configuro a mano.
        "mensajes": ["quiero unas mechas"],
        "debe": ["largo", "diagnostico", "diagnóstico", "valoracion", "valoración"],
        "no_debe": ["corto-med", "media cabeza-"],
    },
    {
        "id": "no-soltar-la-duracion-sin-que-la-pidan",
        "solo_si": ["tiene_servicio:mechas"],
        "gravedad": "importante",
        "por_que": (
            "'El servicio es Mechas o balayage largo y dura 440 minutos' cuando "
            "nadie habia preguntado. Palabras de la duenya: 'no le he preguntado "
            "nada de precio ni del tiempo que dura, todo eso no tiene que decirlo'. "
            "Siete horas sueltas asi asustan a cualquiera."
        ),
        "mensajes": ["quiero unas mechas", "tengo el cabello largo"],
        # Se mide la respuesta de DESPUES de elegir servicio, y se prohibe "dura",
        # no "minutos": el texto que escribio la duenya para el diagnostico dice
        # "una cita de 15 minutos", y prohibir esa palabra la castigaba a ella.
        "no_debe_en": "ultima",
        "debe": [],
        "no_debe": ["dura"],
    },
    {
        "id": "foto-anunciada-no-vuelve-a-preguntar-el-largo",
        "solo_si": ["tiene_servicio:mechas"],
        "gravedad": "critico",
        "por_que": (
            "Bucle real: ella insistia en mandar una foto y el asistente repetia "
            "'necesito saber como tienes el pelo de largo' una y otra vez, tambien "
            "despues de mandarla. El asistente no ve fotos, pero entonces lo que "
            "toca es decir que la mande y que le contestan, no seguir preguntando."
        ),
        "mensajes": ["si te mando una foto y me ves el cabello, es mejor?"],
        "debe": ["mand", "foto"],
        "no_debe": ["como tienes el pelo de largo", "corto, medio, largo"],
    },
    {
        "id": "precio-sin-regla-de-familia-tampoco",
        "gravedad": "critico",
        "solo_si": "sin_precio_global",
        "por_que": (
            "Su negocio tiene `mostrar_precios: False`: NO da precios por mensaje, de "
            "nada. Con mechas o alisado funciona, porque ademas hay una regla de "
            "familia con texto propio. Pero preguntado por un secado -que no tiene "
            "regla, solo el interruptor global- el asistente en produccion recito el "
            "catalogo: 'Secado al aire corto: 10 min, Precio: 10 EUR'. El freno esta "
            "escrito como INSTRUCCION al modelo, y el modelo puede desobedecerla."
        ),
        "mensajes": ["cuanto cuesta un secado?"],
        "debe": [],
        # 10 y 15 son las DURACIONES de esos secados. El asistente las daba como
        # precio: dijo 10 EUR de un servicio que cuesta 4 y 15 de uno que cuesta 8.
        "no_debe": ["€", " eur"],
    },
    # ─── Digresiones: preguntar algo de verdad a media reserva ────────────
    # La duenya del salon, 2-sep-2026. A mitad de elegir alisado pregunto si
    # habia problema estando dando pecho y el asistente contesto "consulta con
    # tu medico", teniendo el salon escrito que su Acido Lactico Bio Premium es
    # apto para embarazadas y madres lactantes. La MISMA pregunta, hecha sola,
    # se contestaba perfecta: fallaba solo DENTRO de una reserva.
    # El caso 18 (`duda-a-media-cita`) no lo cazaba: solo miraba que no dijera
    # "no he reconocido". Una respuesta creible pero contraria a lo que el
    # negocio tiene escrito le parecia bien.
    {
        "id": "digresion-protocolo-a-media-reserva",
        "gravedad": "critico",
        "solo_si": "tiene_qa:como tengo que venir con el cabello para un alisado",
        "por_que": "Lo que el negocio tiene escrito no puede apagarse por estar reservando.",
        "mensajes": ["quiero cita para un alisado",
                     "y como tengo que venir con el cabello?"],
        "debe": ["3 lavados", "mismo dia", "mismo día", "la noche anterior"],
        "no_debe": ["consulta con tu medico", "consulta con tu médico",
                    "te recomiendo consultar", "no dispongo de esa informacion",
                    "no dispongo de esa información"],
    },
    {
        "id": "digresion-donde-estais-a-media-reserva",
        "gravedad": "importante",
        "solo_si": "tiene_qa:donde estais",
        "por_que": "La direccion la tiene escrita: inventarla manda a la clienta a otro sitio.",
        "mensajes": ["quiero cita para un corte de señora",
                     "y donde estais exactamente?"],
        "debe": ["andreu castillejos", "elche"],
        "no_debe": [],
    },
    {
        "id": "digresion-fianza-a-media-reserva",
        "gravedad": "critico",
        "solo_si": "tiene_qa:como se paga la fianza de la cita",
        "por_que": "Es dinero. Inventarse el metodo de pago es el fallo mas caro que hay.",
        "mensajes": ["quiero cita para un alisado", "y la fianza como se paga?"],
        "debe": ["bizum", "transferencia", "670 387 625"],
        "no_debe": ["efectivo en el salon", "paypal", "link de pago"],
    },
]
