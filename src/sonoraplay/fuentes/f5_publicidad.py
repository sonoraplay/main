"""F5: ingresos publicitarios reproducibles para seis países."""

import random
from datetime import date
from decimal import Decimal

PAIS_MONEDA = {"AR": "ARS", "BR": "BRL", "CL": "CLP", "CO": "COP", "MX": "MXN", "PE": "PEN"}
PAISES = tuple(PAIS_MONEDA)
CAMPOS_F5 = ("mes", "pais", "moneda", "ingresos_publicidad")


def generar_f5(mes: str, paises: list[dict], semilla: int = 2026) -> list[dict]:
    date.fromisoformat(mes + "-01")
    por_codigo = {p["pais"]: p for p in paises}
    rng = random.Random(f"sonoraplay:f5:{semilla}:{mes}")
    filas = []
    for codigo in PAISES:
        if codigo not in por_codigo:
            raise ValueError(f"F7 no contiene {codigo}")
        monedas = por_codigo[codigo]["monedas"]
        esperada = PAIS_MONEDA[codigo]
        if esperada not in monedas:
            raise ValueError(f"F7 no confirma moneda {esperada} para {codigo}")
        valor = Decimal(rng.randint(100_000, 900_000)) / Decimal(100)
        filas.append(
            {"mes": mes, "pais": codigo, "moneda": esperada, "ingresos_publicidad": f"{valor:.2f}"}
        )
    return filas
