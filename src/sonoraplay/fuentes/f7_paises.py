"""F7: validación de países y monedas.

Fuente (ADR-0021): dataset público ``mledoze/countries``, licencia ODbL 1.0, fijado a un commit.
Atribución: https://github.com/mledoze/countries . Cambiar el commit solo con revisión.
"""

REST_COUNTRIES = "https://raw.githubusercontent.com/mledoze/countries/c2ac0049c14edcf2436c7aa1b2493222a020b462/countries.json"


def validar_paises(datos: object) -> list[dict]:
    if not isinstance(datos, list):
        raise ValueError("F7 debe ser una lista")
    resultado = {}
    for item in datos:
        if not isinstance(item, dict):
            raise ValueError("País inválido")
        codigo = item.get("cca2")
        monedas = item.get("currencies")
        if not isinstance(codigo, str) or len(codigo) != 2 or not isinstance(monedas, dict):
            raise ValueError("País sin código ISO-2 o monedas")
        resultado[codigo] = {
            "pais": codigo,
            "region": item.get("region") or "Unknown",
            "monedas": sorted(monedas),
        }
    if len(resultado) < 200:
        raise ValueError(f"F7 incompleta: {len(resultado)} países")
    return [resultado[k] for k in sorted(resultado)]
