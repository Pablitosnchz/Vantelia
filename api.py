import os
import json
import time
import hashlib
import requests
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr

from dotenv import load_dotenv

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    Settings,
    StorageContext,
    load_index_from_storage,
)
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding

from datetime import datetime, timedelta
import httpx  # pip install httpx

# ============================================================
# 🔐 CONFIGURACIÓN INICIAL
# ============================================================
load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

# Cargar config de clientes
with open("config.json", "r", encoding="utf-8") as f:
    CONFIG_CLIENTES = json.load(f)

# ============================================================
# 🚀 CREAR APP FASTAPI
# ============================================================
app = FastAPI(
    title="🤖 Agencia IA - API de Chatbots",
    description="Backend para chatbots inteligentes multi-cliente",
    version="1.0.0"
)

# CORS - Permitir que cualquier web use el widget
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # En producción: lista de dominios permitidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos del widget
os.makedirs("widget", exist_ok=True)
app.mount("/widget", StaticFiles(directory="widget"), name="widget")

# ============================================================
# 📦 MODELOS DE DATOS (Lo que recibe y envía la API)
# ============================================================
class MensajeChat(BaseModel):
    cliente_id: str                    # "Clinica_Saga"
    mensaje: str                       # "Quiero una cita"
    session_id: str                    # ID único por visitante

class DatosCita(BaseModel):
    cliente_id: str
    nombre: str
    email: str
    telefono: Optional[str] = ""
    fecha: Optional[str] = ""
    mensaje: Optional[str] = ""

class RespuestaChat(BaseModel):
    respuesta: str
    mostrar_formulario: bool
    session_id: str

# ============================================================
# 🧠 GESTIÓN DE ÍNDICES (Cerebros RAG por cliente)
# ============================================================
indices: Dict[str, VectorStoreIndex] = {}

def cargar_indice(cliente_id: str) -> VectorStoreIndex:
    """Carga o crea el índice RAG de un cliente"""
    
    if cliente_id in indices:
        return indices[cliente_id]
    
    ruta_datos = f"data/{cliente_id}"
    ruta_storage = f"storage/{cliente_id}"
    
    if not os.path.exists(ruta_datos):
        raise HTTPException(
            status_code=404,
            detail=f"No hay datos configurados para: {cliente_id}"
        )
    
    # Configurar modelo
    Settings.llm = OpenAI(model="gpt-4o-mini", temperature=0.1)
    Settings.embed_model = OpenAIEmbedding(model="text-embedding-3-small")
    
    # Intentar cargar índice guardado (más rápido)
    if os.path.exists(ruta_storage):
        try:
            storage_context = StorageContext.from_defaults(persist_dir=ruta_storage)
            indice = load_index_from_storage(storage_context)
            print(f"✅ Índice cargado desde storage: {cliente_id}")
        except:
            indice = _crear_indice_nuevo(ruta_datos, ruta_storage)
    else:
        indice = _crear_indice_nuevo(ruta_datos, ruta_storage)
    
    indices[cliente_id] = indice
    return indice


def _crear_indice_nuevo(ruta_datos: str, ruta_storage: str):
    """Crea un índice nuevo desde los documentos"""
    print(f"🔨 Creando índice nuevo desde: {ruta_datos}")
    documentos = SimpleDirectoryReader(ruta_datos).load_data()
    indice = VectorStoreIndex.from_documents(documentos)
    
    # Guardar para no recalcular cada vez
    os.makedirs(ruta_storage, exist_ok=True)
    indice.storage_context.persist(persist_dir=ruta_storage)
    print(f"💾 Índice guardado en: {ruta_storage}")
    
    return indice

# ============================================================
# 💬 GESTIÓN DE SESIONES (Memoria por visitante)
# ============================================================
sesiones: Dict[str, dict] = {}

def get_sesion(session_id: str, cliente_id: str) -> dict:
    """Obtiene o crea la sesión de un visitante"""
    
    if session_id not in sesiones:
        config = CONFIG_CLIENTES.get(cliente_id, {})
        nombre_empresa = config.get("nombre", cliente_id)
        prompt_extra = config.get("prompt_extra", "")
        
        system_prompt = f"""Eres el asistente virtual EXCLUSIVO de {nombre_empresa}.
{prompt_extra}

TUS REGLAS INQUEBRANTABLES:
1. SOLO puedes hablar sobre los servicios, precios, horarios e información que aparece en los documentos de {nombre_empresa}.
2. NO tienes otras capacidades. No generas imágenes, no programas, no das consejos médicos generales, financieros ni de otro tipo.
3. Si te preguntan algo fuera del contexto de la empresa, responde: "Lo siento, solo puedo ayudarte con consultas sobre {nombre_empresa} y nuestros servicios."
4. Sé amable, profesional y conciso. Usa emojis con moderación.
5. Si el usuario pide EXPLÍCITAMENTE agendar una cita, reserva o consulta, añade al final de tu respuesta: [MOSTRAR_FORMULARIO]
6. NO muestres [MOSTRAR_FORMULARIO] si solo preguntan información. Solo si PIDEN agendar.
7. Si no encuentras la información en los documentos, di: "No tengo esa información disponible, pero puedes contactarnos directamente."
"""
        
        indice = cargar_indice(cliente_id)
        motor = indice.as_chat_engine(
            chat_mode="condense_plus_context",
            similarity_top_k=3,
            system_prompt=system_prompt,
        )
        
        sesiones[session_id] = {
            "motor": motor,
            "cliente_id": cliente_id,
            "creado": time.time(),
            "mensajes": 0
        }
    
    return sesiones[session_id]


def limpiar_sesiones_viejas():
    """Elimina sesiones inactivas (más de 30 min)"""
    ahora = time.time()
    expiradas = [
        sid for sid, s in sesiones.items() 
        if ahora - s["creado"] > 1800  # 30 minutos
    ]
    for sid in expiradas:
        del sesiones[sid]
    if expiradas:
        print(f"🧹 Limpiadas {len(expiradas)} sesiones expiradas")

# ============================================================
# 🌐 ENDPOINTS DE LA API
# ============================================================

# ---------- HEALTH CHECK ----------
@app.get("/")
async def raiz():
    return {
        "status": "🟢 Online",
        "servicio": "Agencia IA - API de Chatbots",
        "clientes_activos": list(CONFIG_CLIENTES.keys()),
        "sesiones_activas": len(sesiones)
    }


# ---------- INFO DEL CLIENTE ----------
@app.get("/cliente/{cliente_id}")
async def info_cliente(cliente_id: str):
    """Devuelve la configuración pública de un cliente"""
    
    if cliente_id not in CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    config = CONFIG_CLIENTES[cliente_id]
    return {
        "nombre": config["nombre"],
        "icono": config["icono"],
        "color": config["color"],
        "bienvenida": config.get("bienvenida", f"¡Hola! ¿En qué puedo ayudarte?")
    }


# ---------- CHAT PRINCIPAL ----------
@app.post("/chat", response_model=RespuestaChat)
async def chat(data: MensajeChat):
    """Endpoint principal del chatbot"""
    
    # Validar cliente
    if data.cliente_id not in CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no configurado")
    
    # Validar mensaje
    if not data.mensaje.strip():
        raise HTTPException(status_code=400, detail="Mensaje vacío")
    
    if len(data.mensaje) > 2000:
        raise HTTPException(status_code=400, detail="Mensaje demasiado largo")
    
    # Limpiar sesiones viejas periódicamente
    if len(sesiones) > 50:
        limpiar_sesiones_viejas()
    
    # Obtener sesión del visitante
    sesion = get_sesion(data.session_id, data.cliente_id)
    sesion["mensajes"] += 1
    
    # Límite de mensajes por sesión (anti-abuso)
    if sesion["mensajes"] > 50:
        return RespuestaChat(
            respuesta="Has alcanzado el límite de mensajes. Por favor, contáctanos directamente.",
            mostrar_formulario=True,
            session_id=data.session_id
        )
    
    try:
        # 🧠 CONSULTA AL MOTOR RAG
        respuesta = sesion["motor"].chat(data.mensaje)
        texto = respuesta.response
        
        # Detectar si debe mostrar formulario
        mostrar_form = "[MOSTRAR_FORMULARIO]" in texto
        texto_limpio = texto.replace("[MOSTRAR_FORMULARIO]", "").strip()
        
        # Log para debugging
        print(f"💬 [{data.cliente_id}] {data.mensaje[:50]}... → {texto_limpio[:50]}...")
        
        return RespuestaChat(
            respuesta=texto_limpio,
            mostrar_formulario=mostrar_form,
            session_id=data.session_id
        )
    
    except Exception as e:
        print(f"❌ Error en chat: {e}")
        raise HTTPException(status_code=500, detail="Error procesando tu mensaje")


# ---------- AGENDAR CITA ----------
@app.post("/agendar")
async def agendar_cita(data: DatosCita):
    """Envía los datos de la cita al webhook de Make.com"""
    
    if data.cliente_id not in CONFIG_CLIENTES:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    config = CONFIG_CLIENTES[data.cliente_id]
    webhook_url = config.get("webhook")
    
    if not webhook_url:
        raise HTTPException(status_code=500, detail="Webhook no configurado")
    
    # Validaciones básicas
    if not data.nombre or not data.email:
        raise HTTPException(status_code=400, detail="Nombre y email son obligatorios")
    
    # Preparar datos para el webhook
    payload = {
        "clinica": config["nombre"],
        "nombre": data.nombre,
        "email": data.email,
        "telefono": data.telefono,
        "fecha": data.fecha,
        "mensaje": data.mensaje,
        "timestamp": datetime.now().isoformat(),
        "fuente": "widget_ia"
    }
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        
        print(f"📅 Cita agendada: {data.nombre} → {config['nombre']}")
        
        return {
            "status": "ok",
            "mensaje": "¡Cita registrada correctamente!"
        }
    
    except requests.exceptions.RequestException as e:
        print(f"❌ Error webhook: {e}")
        raise HTTPException(status_code=500, detail="Error al enviar la cita")


# ---------- RECARGAR ÍNDICE DE UN CLIENTE ----------
@app.post("/admin/reindex/{cliente_id}")
async def reindexar(cliente_id: str):
    """Recarga los documentos de un cliente (cuando actualizan info)"""
    
    ruta_storage = f"storage/{cliente_id}"
    
    # Eliminar índice cacheado
    if cliente_id in indices:
        del indices[cliente_id]
    
    # Eliminar storage guardado
    if os.path.exists(ruta_storage):
        import shutil
        shutil.rmtree(ruta_storage)
    
    # Eliminar sesiones de ese cliente
    sesiones_a_borrar = [
        sid for sid, s in sesiones.items() 
        if s["cliente_id"] == cliente_id
    ]
    for sid in sesiones_a_borrar:
        del sesiones[sid]
    
    # Recargar
    cargar_indice(cliente_id)
    
    return {"status": "ok", "mensaje": f"Índice de {cliente_id} recargado"}


# ---------- ESTADÍSTICAS ----------
@app.get("/admin/stats")
async def estadisticas():
    """Panel básico de estadísticas"""
    
    stats_por_cliente = {}
    for sid, sesion in sesiones.items():
        cid = sesion["cliente_id"]
        if cid not in stats_por_cliente:
            stats_por_cliente[cid] = {"sesiones": 0, "mensajes_total": 0}
        stats_por_cliente[cid]["sesiones"] += 1
        stats_por_cliente[cid]["mensajes_total"] += sesion["mensajes"]
    
    return {
        "sesiones_activas": len(sesiones),
        "clientes": stats_por_cliente,
        "indices_cargados": list(indices.keys())
    }

# ============================================================
# 📅 CALENDLY CONFIG — pon esto arriba de api.py
# ============================================================
CALENDLY_TOKEN = "eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0MDIzZjdjMzJiZTgzNDliMjM4MDEzNWI0IiwidHlwIjoiUEFUIiwiYWxnIjoiRVMyNTYifQ.eyJpc3MiOiJodHRwczovL2F1dGguY2FsZW5kbHkuY29tIiwiaWF0IjoxNzc2NjA3MjIxLCJqdGkiOiI5NGFkNDU5Yi05ZDM3LTRiOTItOWUwMS1kOTQ2NmRmZGE2OWUiLCJ1c2VyX3V1aWQiOiI5NzQ5OGUyMS02NjI1LTRkMTYtOGZmMS03OWVlMGZlMDBhZTciLCJzY29wZSI6ImF2YWlsYWJpbGl0eTpyZWFkIGF2YWlsYWJpbGl0eTp3cml0ZSBldmVudF90eXBlczpyZWFkIGV2ZW50X3R5cGVzOndyaXRlIGxvY2F0aW9uczpyZWFkIHJvdXRpbmdfZm9ybXM6cmVhZCBzaGFyZXM6d3JpdGUgc2NoZWR1bGVkX2V2ZW50czpyZWFkIHNjaGVkdWxlZF9ldmVudHM6d3JpdGUgc2NoZWR1bGluZ19saW5rczp3cml0ZSJ9.4Dw7bRVv6OwLUYFmObUI5U8kMrejTmm0FCMrJN9Fy_4UEXQOxbZ6fdh2RvtXQlD6tH4XftHvauA5WUJyVyoEvg"  # Personal Access Token
CALENDLY_EVENT_TYPE = "https://calendly.com/pablitosnchz/30min"
CALENDLY_USER = "https://api.calendly.com/users/pablitosnchz"


# ============================================================
# 🔌 ENDPOINT: Disponibilidad (consulta Calendly)
# ============================================================
@app.get("/disponibilidad")
async def disponibilidad(cliente_id: str, fecha: str):
    """
    Devuelve slots de 30min para una fecha.
    Consulta Calendly para ver cuáles están ocupados.
    """
    # Generar slots base (9:00 - 19:00)
    slots_base = []
    for h in range(9, 20):
        slots_base.append(f"{h:02d}:00")
        if h < 19:
            slots_base.append(f"{h:02d}:30")

    # Consultar eventos existentes en Calendly para ese día
    ocupados = set()
    try:
        start = f"{fecha}T00:00:00Z"
        end = f"{fecha}T23:59:59Z"

        async with httpx.AsyncClient() as client:
            res = await client.get(
                "https://api.calendly.com/scheduled_events",
                headers={"Authorization": f"Bearer {CALENDLY_TOKEN}"},
                params={
                    "user": CALENDLY_USER,
                    "min_start_time": start,
                    "max_start_time": end,
                    "status": "active",
                },
            )
            if res.status_code == 200:
                events = res.json().get("collection", [])
                for ev in events:
                    # Extraer hora de inicio del evento
                    st = ev.get("start_time", "")
                    if st:
                        hora_ev = datetime.fromisoformat(st.replace("Z", "+00:00"))
                        # Ajustar a tu zona horaria (ejemplo: +2)
                        hora_local = hora_ev + timedelta(hours=2)
                        ocupados.add(hora_local.strftime("%H:%M"))
    except Exception as e:
        print(f"⚠️ Error consultando Calendly: {e}")
        # Si falla, devolvemos todo disponible

    # Construir respuesta
    slots = []
    for s in slots_base:
        slots.append({
            "hora": s,
            "disponible": s not in ocupados
        })

    return {"fecha": fecha, "slots": slots}


# ============================================================
# 📅 ENDPOINT: Agendar (crea evento en Calendly)
# ============================================================
@app.post("/agendar")
async def agendar(data: dict):
    """Agenda una cita y la crea en Calendly"""

    nombre = data.get("nombre")
    email = data.get("email")
    telefono = data.get("telefono", "")
    fecha = data.get("fecha")
    hora = data.get("hora")

    if not nombre or not email or not fecha or not hora:
        raise HTTPException(status_code=400, detail="Faltan datos")

    # Crear invitación en Calendly via API
    # Nota: Calendly no permite crear eventos directamente via API,
    # pero sí puedes usar scheduling links o webhooks.
    # La alternativa real es usar el one-off event o guardar en tu DB:

    # Opción A: Guardar en tu propia base de datos
    cita = {
        "cliente_id": data.get("cliente_id"),
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
        "fecha": fecha,
        "hora": hora,
        "timestamp": datetime.now().isoformat(),
    }

    # Guardar en archivo JSON (cambia a DB en producción)
    import json
    citas_file = "citas.json"
    try:
        with open(citas_file, "r") as f:
            citas = json.load(f)
    except:
        citas = []

    citas.append(cita)
    with open(citas_file, "w") as f:
        json.dump(citas, f, indent=2, ensure_ascii=False)

    # Opción B: Crear evento via Calendly (invitee scheduling)
    try:
        async with httpx.AsyncClient() as client:
            # Enviar email de invitación via Calendly
            await client.post(
                "https://api.calendly.com/scheduling_links",
                headers={
                    "Authorization": f"Bearer {CALENDLY_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "max_event_count": 1,
                    "owner": CALENDLY_EVENT_TYPE,
                    "owner_type": "EventType",
                },
            )
    except Exception as e:
        print(f"⚠️ Calendly link error (no crítico): {e}")

    return {"ok": True, "mensaje": f"Cita agendada: {fecha} a las {hora}"}

@app.get("/servicios/{cliente_id}")
async def obtener_servicios(cliente_id: str):
    ruta_info = f"data/{cliente_id}/info.txt"
    
    if not os.path.exists(ruta_info):
        return {"servicios": []}
    
    with open(ruta_info, "r", encoding="utf-8") as f:
        contenido = f.read()
    
    servicios = []
    en_seccion = False
    excluir = ["promociones", "precios", "ofertas", "notas"]
    
    for linea in contenido.split("\n"):
        linea_strip = linea.strip()
        linea_lower = linea_strip.lower()
        
        if "servicios y precios" in linea_lower or "servicios:" in linea_lower:
            en_seccion = True
            continue
        
        if en_seccion and linea_strip and linea_strip.isupper() and linea_strip.endswith(":"):
            en_seccion = False
            continue
        
        if en_seccion and linea_strip.startswith("- ") and linea_strip.endswith(":"):
            categoria = linea_strip.lstrip("- ").rstrip(":").strip()
            if categoria and len(categoria) > 2 and categoria.lower() not in excluir:
                servicio_id = categoria.lower().replace(" ", "_").replace("/", "_")
                servicio_id = ''.join(c for c in servicio_id if c.isalnum() or c == '_')
                servicios.append({
                    "id": servicio_id,
                    "nombre": categoria
                })
    
    if not servicios:
        try:
            from openai import OpenAI
            client = OpenAI()
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Extrae las CATEGORÍAS principales de servicios del texto. Devuelve SOLO un JSON array: [{\"id\": \"id\", \"nombre\": \"Nombre\"}]. Sin promociones ni ofertas."},
                    {"role": "user", "content": contenido[:3000]}
                ],
                temperature=0
            )
            import json
            servicios = json.loads(resp.choices[0].message.content)
        except:
            servicios = []
    
    return {"servicios": servicios}

# ============================================================
# ▶️ ARRANCAR SERVIDOR
# ============================================================
if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando servidor de la Agencia IA...")
    print(f"📋 Clientes configurados: {list(CONFIG_CLIENTES.keys())}")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
