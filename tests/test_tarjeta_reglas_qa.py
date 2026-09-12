"""Ejecuta las funciones reales del portal con la respuesta de un negocio nuevo."""
import pathlib
import shutil
import subprocess

import pytest


def test_reglas_de_negocio_visibles_y_palabras_clave_sin_activar_ocultas():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node necesario para ejecutar el JavaScript del portal")
    html = (pathlib.Path(__file__).resolve().parents[1] / "app_ui" / "index.html").read_text(encoding="utf-8")
    funciones = []
    for nombre in ("loadBusinessRules", "loadKeywordRules"):
        inicio = html.index("async function " + nombre + "()")
        funciones.append(html[inicio:html.index("\n}", inicio) + 2])
    prueba = """
const assert = require('assert');
const nodos = Object.fromEntries(['brCard','brList','brEnabled','brStatus','brFamiliasHint',
    'brIntenciones','kwrCard','kwrList','kwrEnabled'].map(id => [id, {
        style: {display:'none'}, dataset: {}, innerHTML:'', checked:false }]));
const document = {getElementById: id => nodos[id]};
const api = async () => ({enabled:false, items:[], familias:[], intenciones:[]});
let brFamiliasDisponibles = [];
const BR_INTENCION_LABEL = {};
const escapeHtml = x => x;
""" + "\n".join(funciones) + """
(async () => {
  await loadBusinessRules(); await loadKeywordRules();
  assert.strictEqual(nodos.brCard.style.display, '');
  assert.strictEqual(nodos.brEnabled.checked, false);
  assert.ok(nodos.brStatus.textContent.includes('no se aplican')); 
  assert.strictEqual(nodos.kwrCard.style.display, 'none');
})().catch(e => { console.error(e); process.exit(1); });
"""
    resultado = subprocess.run([node, "-e", prueba], capture_output=True, text=True, timeout=20)
    assert resultado.returncode == 0, resultado.stderr
