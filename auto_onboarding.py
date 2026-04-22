from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from onboarding_utils import run_onboarding, slugify_company


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

st.set_page_config(page_title="Vantelia Auto Onboarding", page_icon="AI", layout="wide")
st.title("Vantelia Auto Onboarding")
st.markdown(
    "Analiza una web corporativa y genera un `info.txt` listo para alimentar el RAG del chatbox embebido."
)


def build_config_snippet(cliente_id: str, business_url: str, nombre_bot: str) -> str:
    return json.dumps(
        {
            cliente_id: {
                "nombre": cliente_id.replace("_", " "),
                "icono": nombre_bot[:2].upper(),
                "color": "#1F6FEB",
                "bienvenida": f"Hola, soy {nombre_bot}. En que puedo ayudarte hoy?",
                "prompt_extra": (
                    "Habla con tono profesional, mantente dentro del contexto del negocio y "
                    "deriva al equipo humano cuando falte informacion."
                ),
                "allowed_origins": [business_url],
                "contacto": {"email": "", "telefono": ""},
                "branding": {"powered_by": "Powered by Vantelia"},
                "booking": {
                    "enabled": True,
                    "timezone": "Europe/Madrid",
                    "slot_minutes": 30,
                    "day_start": "09:00",
                    "day_end": "18:00",
                    "closed_weekdays": [6],
                    "webhook_env": "WEBHOOK_DEFAULT",
                    "success_message": "Tu solicitud ha quedado registrada correctamente.",
                },
            }
        },
        indent=2,
        ensure_ascii=False,
    )


api_key = st.text_input(
    "OpenAI API Key",
    type="password",
    value=os.getenv("OPENAI_API_KEY", ""),
    help="Puedes dejarla vacia si ya existe en tu entorno.",
)

url = st.text_input("URL del negocio", placeholder="https://www.empresa.com")

with st.expander("Opciones avanzadas", expanded=True):
    cliente_id = st.text_input("ID interno del cliente", "empresa_demo")
    nombre_bot = st.text_input("Nombre del asistente", "Clara")
    tono = st.selectbox(
        "Tono del asistente",
        ["Profesional y cercano", "Muy formal", "Calido y empatico", "Directo y resolutivo"],
    )
    idioma = st.selectbox("Idioma principal", ["Español", "Inglés", "Francés", "Portugués"])
    max_paginas = st.slider("Maximo de paginas a analizar", 1, 30, 12)
    guardar_en_data = st.checkbox("Guardar resultado en la carpeta data/", value=True)


if st.button("Analizar web y generar onboarding", type="primary", use_container_width=True):
    if not url:
        st.error("Introduce una URL valida.")
    elif not api_key:
        st.error("Necesitas una OpenAI API Key para generar el borrador.")
    else:
        normalized_cliente_id = slugify_company(cliente_id)

        with st.status("Analizando web...", expanded=True) as status:
            try:
                result = run_onboarding(
                    website_url=url,
                    api_key=api_key,
                    nombre_bot=nombre_bot,
                    tono=tono,
                    idioma=idioma,
                    max_paginas=max_paginas,
                )
                st.write(f"Paginas encontradas: {len(result.links)}")
                st.write(f"Texto extraido: {len(result.all_text):,} caracteres")
                status.update(label="Proceso completado", state="complete")
            except Exception as exc:  # noqa: BLE001
                status.update(label="Proceso interrumpido", state="error")
                st.error(f"No se ha podido completar el onboarding: {exc}")
                st.stop()

        save_path = DATA_DIR / normalized_cliente_id / "info.txt"
        if guardar_en_data:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(result.info_txt, encoding="utf-8")
            st.success(f"Archivo guardado en: {save_path}")

        st.subheader("Borrador generado")
        st.text_area("Resultado", result.info_txt, height=520)

        st.download_button(
            "Descargar info.txt",
            data=result.info_txt,
            file_name=f"{normalized_cliente_id}_info.txt",
            mime="text/plain",
            use_container_width=True,
        )

        st.subheader("Snippet sugerido para config.json")
        st.code(build_config_snippet(normalized_cliente_id, result.normalized_url, nombre_bot), language="json")

        with st.expander("Texto fuente extraido"):
            st.text_area("Fuente", result.all_text, height=320)
