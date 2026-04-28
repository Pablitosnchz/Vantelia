# Migracion a WordPress

## Estructura recomendada

- Pagina de inicio: `/`
- Paginas:
  - `/servicios/`
  - `/testimonios/`
  - `/consultas/`
- Pagina de noticias o blog: `/noticias/`
- Entradas:
  - `/innovaciones-en-ia-para-transformar-tu-marketing-digital/`
  - `/tendencias-en-ia-y-marketing-digital-para-2024/`

## Material reutilizable

- Textos y estructura visual: HTML de esta carpeta
- Contenido centralizado: `assets/js/site-data.js`
- Imagenes de marca: `assets/img/`
- Video del hero: `assets/media/hero-loop.mp4`

## Paso a paso

1. Crea las paginas con los mismos slugs.
2. Crea una pagina para `Noticias` y asi gnale el rol de pagina del blog si quieres usar entradas nativas de WordPress.
3. Crea las dos entradas y conserva los slugs actuales.
4. Configura el menu principal con Inicio, Servicios, Testimonios, Noticias y Consultas.
5. Reemplaza el formulario por el plugin o endpoint que prefieras.
6. Sube las imagenes desde `assets/img/` para mantener identidad visual y reducir dependencias externas.

## Sugerencia practica

Si quieres una migracion rapida, usa esta version estatica como referencia visual y copia por bloques:

- Hero
- Servicios
- Testimonio destacado
- Blog / Noticias
- Contacto y footer
