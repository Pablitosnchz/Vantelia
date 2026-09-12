"""Un negocio nuevo puede configurar reglas sin exponer la tarjeta antigua."""
import pathlib
import re
import shutil
import subprocess

import pytest


def test_reglas_vacias_visibles_y_palabras_clave_ocultas():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node no disponible para ejecutar el JavaScript del portal")
    html = (pathlib.Path(__file__).resolve().parents[1] / "app_ui/index.html").read_text(encoding="utf-8")
    funciones = []
    for nombre in ("loadBusinessRules", "loadKeywordRules"):
        funciones.append(re.search(r"async function " + nombre + r"\(\) \{.*?^\}", html, re.S | re.M).group())
    script = """
const assert = require('assert');
const nodos = {};
const document = {getElementById(id) {return nodos[id] || (nodos[id] = {style:{display:'none'},dataset:{},checked:false});}};
const state = {}; let brFamiliasDisponibles = [];
async function api() {return {enabled:false,items:[],familias:[],intenciones:[]};}
""" + "\n".join(funciones) + """
(async () => {
 await loadBusinessRules(); await loadKeywordRules();
 assert.strictEqual(nodos.brCard.style.display, '');
 assert.strictEqual(nodos.brEnabled.checked, false);
 assert.strictEqual(nodos.kwrCard.style.display, 'none');
 assert.ok(nodos.brList.innerHTML.includes('Sin reglas'));
})().catch(e => {console.error(e); process.exitCode=1;});
"""
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
