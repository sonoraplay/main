"""F6: validación y normalización de cotizaciones USD."""

from datetime import date
from decimal import Decimal

from sonoraplay.fuentes.f5_publicidad import PAIS_MONEDA

FRANKFURTER = "https://api.frankfurter.dev/v2/rates"
MONEDAS = tuple(PAIS_MONEDA.values())
# ADR-0021: la cotización de cierre no puede ser más vieja que esto (fin de semana o festivo).
MAX_ANTIGUEDAD_DIAS = 5


def validar_tasas(
    datos: object,
    monedas: tuple[str, ...] = MONEDAS,
    cierre: date | None = None,
    max_antiguedad_dias: int = MAX_ANTIGUEDAD_DIAS,
) -> list[dict]:
    """Normaliza Frankfurter v2; conserva fecha real y fecha de cierre UTC.

    Toma, por moneda, la última cotización del mes anterior o igual al cierre. Si es más
    antigua que ``max_antiguedad_dias`` días corridos, falla en lugar de aceptarla (ADR-0021).
    """
    if not isinstance(datos, list):
        raise ValueError("Respuesta F6 inválida: se esperaba lista v2")
    if cierre is None:
        raise ValueError("F6 requiere fecha de cierre")
    por_moneda: dict[str, dict] = {}
    for item in datos:
        if not isinstance(item, dict) or item.get("base") != "USD":
            raise ValueError("F6 exige tasas con base USD")
        moneda = item.get("quote")
        if moneda not in monedas:
            continue
        try:
            observacion = date.fromisoformat(item["date"])
            valor = Decimal(str(item["rate"]))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError(f"F6 inválida para {moneda}") from exc
        if not valor.is_finite() or valor <= 0:
            raise ValueError(f"Tasa inválida: {moneda}")
        if not date(cierre.year, cierre.month, 1) <= observacion <= cierre:
            raise ValueError(f"Fecha de tasa fuera del mes: {moneda} {observacion}")
        anterior = por_moneda.get(moneda)
        if anterior is None or observacion > date.fromisoformat(anterior["fecha_observacion"]):
            por_moneda[moneda] = {
                "moneda": moneda,
                "fecha": cierre.isoformat(),
                "unidades_por_usd": str(valor),
                "fecha_observacion": observacion.isoformat(),
                "proveedor": "Frankfurter v2 (tasas combinadas)",
            }
    faltantes = sorted(set(monedas) - set(por_moneda))
    if faltantes:
        raise ValueError(f"F6 sin cobertura para: {', '.join(faltantes)}")
    viejas = sorted(
        f"{moneda} ({fila['fecha_observacion']})"
        for moneda, fila in por_moneda.items()
        if (cierre - date.fromisoformat(fila["fecha_observacion"])).days > max_antiguedad_dias
    )
    if viejas:
        raise ValueError(
            f"F6 con cotización de más de {max_antiguedad_dias} días antes del cierre "
            f"{cierre.isoformat()}: {', '.join(viejas)}"
        )
    return [por_moneda[moneda] for moneda in monedas]


def validar_tasas_diarias(
    datos: object, monedas: tuple[str, ...], inicio: date, cierre: date
) -> list[dict]:
    """Normaliza observaciones diarias reales sin inventar días sin cotización.

    Se exige cobertura por moneda dentro del período, no una tasa para cada día
    calendario: fines de semana y festivos pueden carecer de observación.
    """
    if not isinstance(datos, list):
        raise ValueError("Respuesta F6 diaria inválida: se esperaba lista v2")
    if inicio > cierre:
        raise ValueError("Rango F6 diario inválido")
    observaciones: dict[tuple[str, date], dict] = {}
    for item in datos:
        if not isinstance(item, dict) or item.get("base") != "USD":
            raise ValueError("F6 diaria exige tasas con base USD")
        moneda = item.get("quote")
        if moneda not in monedas:
            continue
        try:
            fecha = date.fromisoformat(item["date"])
            tasa = Decimal(str(item["rate"]))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError(f"F6 diaria inválida para {moneda}") from exc
        if fecha < inicio:
            # Frankfurter arrastra la última cotización previa cuando el día 1 es festivo
            # para esa moneda (CLP el 1 de mayo de 2026 trae 2026-04-30); no es del período.
            continue
        if fecha > cierre or not tasa.is_finite() or tasa <= 0:
            raise ValueError(f"Observación F6 diaria inválida: {moneda} {fecha}")
        clave = (moneda, fecha)
        if clave in observaciones and observaciones[clave]["unidades_por_usd"] != str(tasa):
            raise ValueError(f"Tasas contradictorias para {moneda} {fecha}")
        observaciones[clave] = {
            "moneda": moneda,
            "fecha": fecha.isoformat(),
            "unidades_por_usd": str(tasa),
            "proveedor": "Frankfurter v2 (tasas combinadas)",
        }
    faltantes = sorted(set(monedas) - {moneda for moneda, _ in observaciones})
    if faltantes:
        raise ValueError(f"F6 diaria sin cobertura para: {', '.join(faltantes)}")
    return [observaciones[clave] for clave in sorted(observaciones)]
