"""El usuario nunca confirma con Enter un servicio fuera de la lista visible."""
import json
import re

from test_nueva_cita_del_portal import _panel, _node


def test_enter_no_elige_resultado_invisible_y_buscar_lo_hace_accesible():
    fuente = _panel()
    inicio = fuente.index("  svc.addEventListener('keydown',")
    fin = fuente.index("\n})();", inicio)
    listener = fuente[inicio:fin]
    constante = re.search(r"const NB_SVC_VISIBLES = \d+;", fuente).group()
    salida = _node([constante], """
      let nbSvcIdx=-1, manejar, elegido='';
      const todos=Array.from({length:301},(_,i)=>({nombre:'Servicio '+i}));
      const svc={value:'',addEventListener(tipo,fn){manejar=fn}};
      const document={getElementById(){return {classList:{contains(){return true}}}}};
      function nbSvcSugerencias(q){return q ? todos.filter(s=>s.nombre===q) : todos}
      function nbSvcPintar(){} function nbSvcVerElegido(){} function nbSvcBuscar(){}
      function nbSvcElegir(n){elegido=n} function nbSvcResuelto(){return ''}
      function nbSvcCerrar(){}
    """ + listener + """
      for(let i=0;i<400;i++) manejar({key:'ArrowDown',preventDefault(){}});
      manejar({key:'Enter',preventDefault(){}});
      const primero=elegido;
      svc.value='Servicio 300'; nbSvcIdx=-1;
      manejar({key:'ArrowDown',preventDefault(){}});
      manejar({key:'Enter',preventDefault(){}});
      process.stdout.write(JSON.stringify([primero,elegido]));
    """)
    assert json.loads(salida) == ['Servicio 299', 'Servicio 300']
