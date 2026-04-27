Esta carpeta contiene exportaciones locales y copias estaticas de webs publicas.

Para clonar `vantelia.es`:

```powershell
python scripts/clone_public_site.py --base-url https://www.vantelia.es --output-dir site_exports/vantelia_public_clone
```

Para previsualizar la copia:

```powershell
cd site_exports/vantelia_public_clone
python -m http.server 8000
```
