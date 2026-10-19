"""F7: validación de países y monedas según REST Countries."""

REST_COUNTRIES = "https://restcountries.com/v3.1/all?fields=cca2,name,region,currencies"


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
