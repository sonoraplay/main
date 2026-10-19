"""Pruebas offline para EG-30: no dependen de APIs externas."""

from datetime import date
from urllib.error import HTTPError, URLError

import pytest

import sonoraplay.fuentes.eg30 as eg30
from sonoraplay.fuentes.eg30 import generar_f5, ultimo_dia, validar_paises, validar_tasas
from sonoraplay.fuentes.f5_publicidad import PAIS_MONEDA
from sonoraplay.fuentes.f6_tasas import validar_tasas_diarias


def paises():
    return [
        {"pais": c, "monedas": [m]}
        for c, m in [
            ("AR", "ARS"),
            ("BR", "BRL"),
            ("CL", "CLP"),
            ("CO", "COP"),
            ("MX", "MXN"),
            ("PE", "PEN"),
        ]
    ]


def test_ultimo_dia_bisiesto():
    assert ultimo_dia("2024-02") == date(2024, 2, 29)


def test_f5_determinista_y_menos_de_mil():
    a = generar_f5("2026-09", paises(), 42)
    assert a == generar_f5("2026-09", paises(), 42)
    assert len(a) == 6
    assert all(f["moneda"] in {"ARS", "BRL", "CLP", "COP", "MXN", "PEN"} for f in a)


def test_f5_exige_moneda_de_f7():
    with pytest.raises(ValueError, match="moneda"):
        generar_f5(
            "2026-09",
            [
                {"pais": codigo, "monedas": ["USD"] if codigo == "BR" else [moneda]}
                for codigo, moneda in PAIS_MONEDA.items()
            ],
        )


def test_f6_rechaza_faltantes():
    with pytest.raises(ValueError, match="cobertura"):
        validar_tasas(
            [{"base": "USD", "quote": "BRL", "date": "2026-09-30", "rate": 5}],
            ("BRL", "COP"),
            date(2026, 9, 30),
        )


def test_f7_rechaza_incompleta():
    with pytest.raises(ValueError, match="incompleta"):
        validar_paises([{"cca2": "CO", "currencies": {"COP": {}}, "region": "Americas"}])


def test_cli_error_de_conexion_sin_traceback(monkeypatch, capsys, tmp_path):
    def conexion_fallida(_url):
        raise URLError("sin conexión")

    monkeypatch.setattr(eg30, "obtener_json", conexion_fallida)
    monkeypatch.setattr("sys.argv", ["eg30", "--mes", "2026-09", "--salida", str(tmp_path)])
    with pytest.raises(SystemExit) as salida:
        eg30.main()
    assert salida.value.code == 1
    error = capsys.readouterr().err
    assert "Error EG-30:" in error
    assert "sin conexión" in error
    assert "Traceback" not in error
    assert list(tmp_path.iterdir()) == []


def test_cli_mes_invalido_sin_traceback(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("sys.argv", ["eg30", "--mes", "2026-13", "--salida", str(tmp_path)])
    with pytest.raises(SystemExit) as salida:
        eg30.main()
    assert salida.value.code == 1
    assert "Error EG-30:" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_f6_normaliza_cierre_domingo_y_decimal():
    filas = [{"base": "USD", "quote": "COP", "date": "2026-05-29", "rate": 4000.125}]
    resultado = validar_tasas(filas, ("COP",), date(2026, 5, 31))
    assert resultado[0]["fecha"] == "2026-05-31"
    assert resultado[0]["fecha_observacion"] == "2026-05-29"
    assert resultado[0]["unidades_por_usd"] == "4000.125"


def test_f6_rechaza_fecha_de_otro_mes():
    with pytest.raises(ValueError, match="fuera del mes"):
        validar_tasas(
            [{"base": "USD", "quote": "COP", "date": "2026-04-30", "rate": 4000}],
            ("COP",),
            date(2026, 5, 31),
        )


def test_ejecutar_no_escribe_si_f6_incompleta(monkeypatch, tmp_path):
    def simular(url):
        if url == eg30.REST_COUNTRIES:
            datos = [
                {
                    "cca2": f"{chr(65 + i // 26)}{chr(65 + i % 26)}",
                    "currencies": {"USD": {}},
                    "region": "Other",
                }
                for i in range(200)
            ]
            datos += [
                {"cca2": codigo, "currencies": {moneda: {}}, "region": "Americas"}
                for codigo, moneda in PAIS_MONEDA.items()
            ]
            return datos
        return [{"base": "USD", "quote": "BRL", "date": "2026-09-30", "rate": 5}]

    monkeypatch.setattr(eg30, "obtener_json", simular)
    with pytest.raises(ValueError, match="cobertura"):
        eg30.ejecutar("2026-09", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_http_400_no_reintenta(monkeypatch):
    llamadas = []

    def fallo(_request, timeout):
        llamadas.append(timeout)
        raise HTTPError("https://example.org", 400, "bad request", {}, None)

    monkeypatch.setattr(eg30, "urlopen", fallo)
    with pytest.raises(HTTPError):
        eg30.obtener_json("https://example.org")
    assert len(llamadas) == 1


def test_http_503_reintenta_y_falla(monkeypatch):
    llamadas = []

    def fallo(_request, timeout):
        llamadas.append(timeout)
        raise HTTPError("https://example.org", 503, "unavailable", {}, None)

    monkeypatch.setattr(eg30, "urlopen", fallo)
    monkeypatch.setattr(eg30.time, "sleep", lambda _: None)
    with pytest.raises(HTTPError):
        eg30.obtener_json("https://example.org", intentos=3)
    assert len(llamadas) == 3


def test_escritura_atomica_reemplaza_contenido(tmp_path):
    destino = tmp_path / "datos" / "f5.csv"
    destino.parent.mkdir()
    destino.write_text("viejo", encoding="utf-8")
    eg30.escribir_atomico(destino, "nuevo")
    assert destino.read_text(encoding="utf-8") == "nuevo"
    assert list(destino.parent.iterdir()) == [destino]


def test_ejecutar_tres_fuentes_simuladas(monkeypatch, tmp_path):
    import csv
    import json

    def simular(url):
        if url == eg30.REST_COUNTRIES:
            datos = [
                {
                    "cca2": f"{chr(65 + i // 26)}{chr(65 + i % 26)}",
                    "currencies": {"USD": {}},
                    "region": "Other",
                }
                for i in range(200)
            ]
            datos += [
                {"cca2": pais, "currencies": {moneda: {}}, "region": "Americas"}
                for pais, moneda in PAIS_MONEDA.items()
            ]
            return datos
        return [
            {"base": "USD", "quote": moneda, "date": "2026-09-30", "rate": 100}
            for moneda in eg30.MONEDAS
        ]

    monkeypatch.setattr(eg30, "obtener_json", simular)
    eg30.ejecutar("2026-09", tmp_path)
    with (tmp_path / "f5_publicidad_2026-09.csv").open(encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 6
    tasas = json.loads((tmp_path / "f6_tasas_2026-09-30.json").read_text())
    assert len(tasas) == 6
    assert len(json.loads((tmp_path / "f7_paises.json").read_text())) >= 200


def test_f6_diaria_conserva_observaciones_sin_inventar_festivos():
    datos = [
        {"base": "USD", "quote": "COP", "date": "2026-05-28", "rate": "3800.25"},
        {"base": "USD", "quote": "COP", "date": "2026-05-29", "rate": "3810.25"},
        {"base": "USD", "quote": "PEN", "date": "2026-05-29", "rate": "3.75"},
    ]
    filas = validar_tasas_diarias(datos, ("COP", "PEN"), date(2026, 5, 1), date(2026, 5, 31))
    assert len(filas) == 3
    assert {fila["fecha"] for fila in filas} == {"2026-05-28", "2026-05-29"}
    assert filas[0]["unidades_por_usd"] == "3800.25"


def test_f6_diaria_rechaza_faltantes_y_duplicados_contradictorios():
    datos = [{"base": "USD", "quote": "COP", "date": "2026-09-30", "rate": "4000"}]
    with pytest.raises(ValueError, match="cobertura"):
        validar_tasas_diarias(datos, ("COP", "ARS"), date(2026, 9, 1), date(2026, 9, 30))
    with pytest.raises(ValueError, match="contradictorias"):
        validar_tasas_diarias(
            datos + [{**datos[0], "rate": "4001"}],
            ("COP",),
            date(2026, 9, 1),
            date(2026, 9, 30),
        )


def test_ejecutar_diarias_no_escribe_si_serie_incompleta(monkeypatch, tmp_path):
    def simular(url):
        if url == eg30.REST_COUNTRIES:
            datos = [
                {
                    "cca2": f"{chr(65 + i // 26)}{chr(65 + i % 26)}",
                    "currencies": {"USD": {}},
                    "region": "Other",
                }
                for i in range(200)
            ]
            datos += [
                {"cca2": pais, "currencies": {moneda: {}}, "region": "Americas"}
                for pais, moneda in PAIS_MONEDA.items()
            ]
            return datos
        if "from=" in url:
            return [{"base": "USD", "quote": "COP", "date": "2026-09-30", "rate": 4000}]
        return [
            {"base": "USD", "quote": moneda, "date": "2026-09-30", "rate": 100}
            for moneda in eg30.MONEDAS
        ]

    monkeypatch.setattr(eg30, "obtener_json", simular)
    with pytest.raises(ValueError, match="cobertura"):
        eg30.ejecutar("2026-09", tmp_path, diarias=True)
    assert list(tmp_path.iterdir()) == []


def test_f6_cierre_sabado_usa_viernes_anterior():
    datos = [
        {"base": "USD", "quote": "COP", "date": "2026-10-29", "rate": "3850.20"},
        {"base": "USD", "quote": "COP", "date": "2026-10-30", "rate": "3851.25"},
    ]
    filas = validar_tasas(datos, ("COP",), date(2026, 10, 31))
    assert filas[0]["fecha"] == "2026-10-31"
    assert filas[0]["fecha_observacion"] == "2026-10-30"
    assert filas[0]["unidades_por_usd"] == "3851.25"


def test_f6_cierre_domingo_seis_monedas_sin_fabricar_tasas():
    datos = [
        {"base": "USD", "quote": moneda, "date": "2026-05-29", "rate": str(i + 1)}
        for i, moneda in enumerate(eg30.MONEDAS)
    ]
    filas = validar_tasas(datos, cierre=date(2026, 5, 31))
    assert len(filas) == 6
    assert {fila["fecha"] for fila in filas} == {"2026-05-31"}
    assert {fila["fecha_observacion"] for fila in filas} == {"2026-05-29"}
    assert {fila["moneda"] for fila in filas} == set(eg30.MONEDAS)


def test_f6_rechaza_observacion_futura_y_tasa_no_positiva():
    with pytest.raises(ValueError, match="fuera del mes"):
        validar_tasas(
            [{"base": "USD", "quote": "COP", "date": "2026-06-01", "rate": "4000"}],
            ("COP",),
            date(2026, 5, 31),
        )
    with pytest.raises(ValueError, match="Tasa inválida"):
        validar_tasas(
            [{"base": "USD", "quote": "COP", "date": "2026-05-29", "rate": "0"}],
            ("COP",),
            date(2026, 5, 31),
        )
