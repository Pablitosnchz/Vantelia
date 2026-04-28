# Vantelia Static Clean

Version estatica reconstruida a partir de la web publica de `vantelia.es`.

## Que incluye

- HTML limpio por pagina y slug
- CSS compartido en `assets/css/styles.css`
- JS comun en `assets/js/`
- Assets locales de marca en `assets/img/` y `assets/media/`
- Formularios con fallback por correo y endpoints configurables

## Previsualizar

```powershell
cd c:\Vantelia\site_exports\vantelia_static_clean
python -m http.server 8000
```

Abre `http://localhost:8000`.

## Despliegue estatico

Sube el contenido completo de esta carpeta al directorio publico de cualquier hosting estatico.

No requiere build.

## Configuracion rapida

Edita `assets/js/site-config.js` para cambiar:

- `siteUrl`
- `contactEmail`
- `leadEmail`
- `phone`
- `clientPortalUrl`
- `contactFormEndpoint`
- `newsletterFormEndpoint`

Si no configuras endpoints, los formularios usan un fallback `mailto:`.

## Notas

- Esta version prioriza mantenibilidad y portabilidad, no una replica binaria del builder.
- Los textos de las noticias se han reconstruido a partir del contenido publico visible del sitio exportado.
