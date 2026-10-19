"""EG-30 · carga transaccional de F5, F6 y F7 en PostgreSQL (criterios 1, 3, 5 y 6).

Las APIs se simulan; la base es real (TEST_DATABASE_URL), como en el CI.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

import sonoraplay.fuentes.eg30 as eg30
from sonoraplay.fuentes.carga import cargar
from sonoraplay.fuentes.f5_publicidad import PAIS_MONEDA

DIAS_HABILES = ["2026-09-28", "2026-09-29", "2026-09-30"]


def _paises_api():
    otros = [
        {"cca2": f"{chr(65 + i // 26)}{chr(65 + i % 26)}", "currencies": {}, "region": ""}
        for i in range(230)
    ]
    otros = [p for p in otros if p["cca2"] not in PAIS_MONEDA]
    return otros + [
        {"cca2": pais, "currencies": {moneda: {}}, "region": "Americas"}
        for pais, moneda in PAIS_MONEDA.items()
    ]


def _simulador(tasa=Decimal("100.5")):
    def simular(url):
        if url == eg30.REST_COUNTRIES:
            return _paises_api()
        if "from=" in url:
            return [
                {"base": "USD", "quote": m, "date": d, "rate": str(tasa)}
                for m in eg30.MONEDAS
                for d in DIAS_HABILES
            ]
        return [
            {"base": "USD", "quote": m, "date": "2026-09-30", "rate": str(tasa)}
            for m in eg30.MONEDAS
        ]

    return simular


def _conteos(engine):
    with engine.connect() as c:
        return {
            t: c.scalar(text(f"SELECT count(*) FROM {t}"))
            for t in ("paises", "tasas_cambio", "ingresos_publicidad")
        }


def test_carga_las_tres_fuentes(db_vacia, monkeypatch, tmp_path):
    monkeypatch.setattr(eg30, "obtener_json", _simulador())
    conteos = eg30.ejecutar("2026-09", tmp_path, engine=db_vacia)

    assert conteos["paises"] >= 200  # criterio 3
    assert conteos["ingresos_publicidad"] == 6  # criterio 4
    # Criterio 1: 6 tasas de cierre + 6 monedas × 3 días hábiles publicados.
    assert conteos["tasas_cambio"] == 6 + 6 * 3
    assert conteos == _conteos(db_vacia)
    with db_vacia.connect() as c:
        cierre = c.execute(
            text("SELECT moneda, fecha::text FROM tasas_cambio WHERE tipo = 'cierre'")
        ).all()
        assert {m for m, _ in cierre} == set(eg30.MONEDAS)
        assert {f for _, f in cierre} == {"2026-09-30"}  # último día del mes (RN-05)
        co = c.execute(text("SELECT region, monedas FROM paises WHERE pais = 'CO'")).one()
        assert co == ("Americas", ["COP"])
    assert (tmp_path / "f6_tasas_diarias_2026-09.json").exists()


def test_repetir_la_carga_no_duplica_filas(db_vacia, monkeypatch, tmp_path):
    monkeypatch.setattr(eg30, "obtener_json", _simulador())
    primera = eg30.ejecutar("2026-09", tmp_path, engine=db_vacia)
    segunda = eg30.ejecutar("2026-09", tmp_path, engine=db_vacia)
    assert primera == segunda == _conteos(db_vacia)  # criterio 5


def test_recargar_actualiza_el_valor_sin_duplicar(db_vacia, monkeypatch, tmp_path):
    monkeypatch.setattr(eg30, "obtener_json", _simulador(Decimal("100")))
    eg30.ejecutar("2026-09", tmp_path, engine=db_vacia)
    monkeypatch.setattr(eg30, "obtener_json", _simulador(Decimal("101.25")))
    conteos = eg30.ejecutar("2026-09", tmp_path, engine=db_vacia)
    with db_vacia.connect() as c:
        tasa = c.scalar(
            text("SELECT unidades_por_usd FROM tasas_cambio WHERE moneda='COP' AND tipo='cierre'")
        )
    assert tasa == Decimal("101.25")
    assert conteos["tasas_cambio"] == 6 + 6 * 3


def test_fallo_de_la_api_no_carga_ni_escribe_nada(db_vacia, monkeypatch, tmp_path):
    def caida(url):
        if url == eg30.REST_COUNTRIES:
            return _paises_api()
        raise OSError("Frankfurter no responde")

    monkeypatch.setattr(eg30, "obtener_json", caida)
    with pytest.raises(OSError):
        eg30.ejecutar("2026-09", tmp_path, engine=db_vacia)
    assert _conteos(db_vacia) == {"paises": 0, "tasas_cambio": 0, "ingresos_publicidad": 0}
    assert list(tmp_path.iterdir()) == []  # criterio 6


def test_fallo_a_mitad_de_la_carga_deshace_todo(db_vacia):
    paises = [{"pais": p, "region": "Americas", "monedas": [m]} for p, m in PAIS_MONEDA.items()]
    tasas = [
        {
            "moneda": m,
            "fecha": "2026-09-30",
            "unidades_por_usd": "100",
            "fecha_observacion": "2026-09-30",
            "proveedor": "prueba",
        }
        for m in eg30.MONEDAS
    ]
    # La última fila de F5 apunta a un país que no está en F7: la FK falla al final.
    f5 = [
        {"mes": "2026-09", "pais": p, "moneda": m, "ingresos_publicidad": "10.00"}
        for p, m in PAIS_MONEDA.items()
    ] + [{"mes": "2026-09", "pais": "US", "moneda": "USD", "ingresos_publicidad": "1.00"}]
    with pytest.raises(IntegrityError):
        cargar(db_vacia, paises, tasas, None, f5, semilla=1)
    # Países y tasas ya se habían insertado en la misma transacción: no queda nada.
    assert _conteos(db_vacia) == {"paises": 0, "tasas_cambio": 0, "ingresos_publicidad": 0}


def test_la_base_rechaza_un_cierre_que_no_es_fin_de_mes(db_vacia):
    with pytest.raises(IntegrityError), db_vacia.begin() as c:
        c.execute(
            text(
                "INSERT INTO tasas_cambio (moneda, fecha, tipo, unidades_por_usd, "
                "fecha_observacion, proveedor) VALUES ('COP', '2026-09-29', 'cierre', 1, "
                "'2026-09-29', 'x')"
            )
        )


def test_cli_cargar_sin_database_url_falla_claro(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "sys.argv", ["eg30", "--mes", "2026-09", "--salida", str(tmp_path), "--cargar"]
    )
    with pytest.raises(SystemExit) as exc:
        eg30.main()
    assert "DATABASE_URL" in str(exc.value)
    assert list(tmp_path.iterdir()) == []


def test_si_falla_un_archivo_no_se_reemplaza_ninguno(tmp_path):
    primero = tmp_path / "f5.csv"
    primero.write_text("viejo", encoding="utf-8")
    bloqueo = tmp_path / "no_es_carpeta"
    bloqueo.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        eg30.escribir_conjunto({primero: "nuevo", bloqueo / "f6.json": "{}"})
    assert primero.read_text(encoding="utf-8") == "viejo"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["f5.csv", "no_es_carpeta"]
