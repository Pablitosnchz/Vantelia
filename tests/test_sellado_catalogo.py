from contextlib import contextmanager



def test_familias_pedidas_lee_su_catalogo_una_vez(monkeypatch):
    from backend import catalog_pick, intents
    lecturas = []
    def familias(cid, **kwargs):
        lecturas.append(cid)
        return ["cortes", "color"]
    monkeypatch.setattr(intents, "familias_del_tenant", familias)
    assert catalog_pick.familias_pedidas("negocio", "corte y color") == ["cortes", "color"]
    assert lecturas == ["negocio"]


def test_consultar_familias_no_lee_qa(monkeypatch):
    from backend import intents
    consultas = []
    class Conexion:
        def execute(self, sql, params):
            consultas.append(sql)
            return self
        def fetchall(self):
            return []
    @contextmanager
    def conectar():
        yield Conexion()
    monkeypatch.setattr(intents.db, "_get_db_connection", conectar)
    monkeypatch.setattr(intents, "_familias_del_tenant", lambda cid: ["cortes"])
    assert intents.familias_del_tenant("solo-catalogo") == ["cortes"]
    assert len(consultas) == 1 and "FROM services" in consultas[0]
