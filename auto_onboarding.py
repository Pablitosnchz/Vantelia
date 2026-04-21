import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import re
import os

st.set_page_config(page_title="Auto Onboarding IA", page_icon="🤖")
st.title("🤖 Generador Automático de Info")
st.markdown("Pega la web del cliente y la IA extrae todo sola")

# API Key
api_key = st.text_input("🔑 OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))

url = st.text_input("🌐 URL de la web del negocio", placeholder="https://www.clinicaejemplo.com")

# Opciones avanzadas
with st.expander("⚙️ Opciones"):
    nombre_bot = st.text_input("Nombre del asistente IA", "Clara")
    tono = st.selectbox("Tono", ["Profesional y cercano", "Muy formal", "Informal y divertido", "Cálido y empático"])
    idioma = st.selectbox("Idioma principal", ["Español", "Inglés", "Francés", "Portugués"])
    max_paginas = st.slider("Máx. páginas a analizar", 1, 30, 15)


def get_all_links(base_url):
    """Obtiene todos los links internos de la web"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(base_url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        
        links = set()
        domain = base_url.split("//")[1].split("/")[0].replace("www.", "")
        
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Convertir relativos a absolutos
            if href.startswith("/"):
                href = base_url.rstrip("/") + href
            # Solo links del mismo dominio
            if domain in href and not any(x in href for x in ["#", ".pdf", ".jpg", ".png", "mailto:", "tel:", "javascript:"]):
                links.add(href.split("?")[0].split("#")[0])
        
        return list(links)
    except Exception as e:
        st.error(f"Error obteniendo links: {e}")
        return [base_url]


def scrape_page(url):
    """Extrae texto limpio de una página"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Eliminar scripts, styles, nav, footer repetitivos
        for tag in soup(["script", "style", "noscript", "iframe"]):
            tag.decompose()
        
        # Extraer título
        title = soup.title.string if soup.title else ""
        
        # Extraer meta description
        meta_desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            meta_desc = meta.get("content", "")
        
        # Extraer texto principal
        text = soup.get_text(separator="\n", strip=True)
        
        # Limpiar líneas vacías múltiples
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)
        
        # Limitar tamaño por página
        text = text[:5000]
        
        return f"PÁGINA: {url}\nTÍTULO: {title}\nMETA: {meta_desc}\nCONTENIDO:\n{text}\n"
    
    except Exception as e:
        return f"PÁGINA: {url}\nError: {e}\n"


def generate_info(all_text, api_key, nombre_bot, tono, idioma):
    """Usa GPT para generar el info.txt estructurado"""
    
    client = OpenAI(api_key=api_key)
    
    prompt = f"""Eres un experto en onboarding de negocios para asistentes IA. 
A partir del contenido scrapeado de una web, genera un archivo de información COMPLETO y ESTRUCTURADO.

INSTRUCCIONES:
- Extrae TODA la información posible: nombre, descripción, servicios con precios, horarios, contacto, equipo, FAQs, políticas, etc.
- Si algo no aparece en la web, pon "No especificado en la web"
- Inventa preguntas frecuentes lógicas basándote en el tipo de negocio y servicios
- Sé muy detallado en los servicios y precios
- Genera en {idioma}

USA EXACTAMENTE ESTE FORMATO:

===== INFORMACIÓN DE [NOMBRE DEL NEGOCIO] =====

DATOS GENERALES:
- Nombre: 
- Tipo de negocio: 
- Descripción: (2-3 frases completas)
- Eslogan: 

CONTACTO Y UBICACIÓN:
- Dirección: 
- Ciudad: 
- Teléfono: 
- Email: 
- Web: 
- Instagram: 
- Facebook: 
- Google Maps: 

HORARIOS:
- Lunes a Viernes: 
- Sábados: 
- Domingos: 
- Notas: 

SERVICIOS Y PRECIOS:
(Lista TODOS los servicios encontrados con precio y descripción)

EQUIPO PROFESIONAL:
(Lista todos los profesionales mencionados)

PREGUNTAS FRECUENTES:
(Mínimo 10 preguntas frecuentes con respuestas completas, basadas en la info real + preguntas lógicas del sector)

P: ¿...?
R: ...

POLÍTICAS:
- Citas/Reservas: 
- Métodos de pago: 
- Cancelaciones: 
- Garantías: 

OFERTAS Y PROMOCIONES:
(Lo que encuentres vigente)

DIFERENCIACIÓN:
- Ventajas competitivas: 
- Certificaciones/Premios: 

CONFIGURACIÓN DEL ASISTENTE:
- Nombre del bot: {nombre_bot}
- Tono: {tono}
- Idioma: {idioma}
- Instrucciones: Siempre intentar agendar cita. Ser útil y resolver dudas. No inventar información que no esté aquí.

CONTENIDO DE LA WEB:
{all_text[:25000]}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=6000
    )
    
    return response.choices[0].message.content


# ===== BOTÓN PRINCIPAL =====
if st.button("🚀 ANALIZAR WEB Y GENERAR INFO", type="primary", use_container_width=True):
    
    if not url or not api_key:
        st.error("Necesito la URL y la API Key")
    else:
        # Paso 1: Obtener links
        with st.status("🔍 Analizando web...", expanded=True) as status:
            st.write("📡 Buscando páginas internas...")
            links = get_all_links(url)
            
            # Añadir la URL base si no está
            if url not in links:
                links.insert(0, url)
            
            # Limitar páginas
            links = links[:max_paginas]
            st.write(f"📄 Encontradas **{len(links)} páginas** para analizar")
            
            # Paso 2: Scrapear todo
            all_text = ""
            progress = st.progress(0)
            for i, link in enumerate(links):
                st.write(f"  📖 Leyendo: {link}")
                page_text = scrape_page(link)
                all_text += page_text + "\n---\n"
                progress.progress((i + 1) / len(links))
            
            st.write(f"📊 Total texto extraído: **{len(all_text):,} caracteres**")
            
            # Paso 3: Generar con IA
            st.write("🧠 Generando info con IA...")
            info_txt = generate_info(all_text, api_key, nombre_bot, tono, idioma)
            
            status.update(label="✅ ¡Completado!", state="complete")
        
        # Mostrar resultado
        st.subheader("📄 Resultado generado:")
        st.text_area("", info_txt, height=500)
        
        # Opciones
        col1, col2 = st.columns(2)
        with col1:
            nombre_archivo = url.split("//")[1].split("/")[0].replace("www.", "").replace(".", "_")
            st.download_button(
                "⬇️ Descargar info.txt",
                data=info_txt,
                file_name=f"info_{nombre_archivo}.txt",
                mime="text/plain",
                use_container_width=True
            )
        with col2:
            if st.button("📋 Copiar al portapapeles", use_container_width=True):
                st.code(info_txt)
        
        # Mostrar páginas scrapeadas (debug)
        with st.expander("🔧 Ver texto crudo extraído"):
            st.text_area("", all_text, height=300)