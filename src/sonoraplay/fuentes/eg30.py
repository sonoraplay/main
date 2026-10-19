"""EG-30: captura HTTP reintentable y CSV F5 reproducible y atómico.

Los datos de F6/F7 se obtienen de las APIs oficiales; no se inventan respuestas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sonoraplay.fuentes.f5_publicidad import CAMPOS_F5, generar_f5
from sonoraplay.fuentes.f6_tasas import (
    FRANKFURTER,
    MONEDAS,
    validar_tasas,
    validar_tasas_diarias,
)
from sonoraplay.fuentes.f7_paises import REST_COUNTRIES, validar_paises


def obtener_json(url: str, intentos: int = 3) -> object:
    """Reintenta errores transitorios; falla sin escribir archivos parciales."""
    for intento in range(intentos):
        try:
            solicitud = Request(url, headers={"User-Agent": "SonoraPlay-EG30/1.0"})
            with urlopen(solicitud, timeout=20) as resp:
                return json.load(resp)
        except HTTPError as exc:
            if exc.code not in (408, 429) and not 500 <= exc.code < 600:
                raise
            if intento == intentos - 1:
                raise
            time.sleep(min(2**intento, 4))
        except OSError:
            if intento == intentos - 1:
                raise
            time.sleep(min(2**intento, 4))
    raise RuntimeError("Sin respuesta")


def ultimo_dia(mes: str) -> date:
    inicio = date.fromisoformat(mes + "-01")
    siguiente = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1)
    return siguiente - timedelta(days=1)


def escribir_atomico(destino: Path, contenido: str) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destino.parent, delete=False
        ) as fh:
            temporal = Path(fh.name)
            fh.write(contenido)
        os.replace(temporal, destino)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)


def ejecutar(mes: str, salida: Path, semilla: int = 2026, diarias: bool = False) -> None:
    """Valida primero; reemplaza cada archivo de forma atómica, no los tres juntos."""
    import io

    cierre = ultimo_dia(mes)
    fecha = cierre.isoformat()
    paises = validar_paises(obtener_json(REST_COUNTRIES))
    # v2 devuelve una fila por par con fecha de observación propia.
    url = f"{FRANKFURTER}?date={fecha}&base=USD&quotes={','.join(MONEDAS)}"
    tasas = validar_tasas(obtener_json(url), cierre=cierre)
    serie_diaria = None
    if diarias:
        inicio = cierre.replace(day=1)
        url_diaria = (
            f"{FRANKFURTER}?from={inicio.isoformat()}&to={fecha}"
            f"&base=USD&quotes={','.join(MONEDAS)}"
        )
        serie_diaria = validar_tasas_diarias(obtener_json(url_diaria), MONEDAS, inicio, cierre)
    filas = generar_f5(mes, paises, semilla)
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=CAMPOS_F5, lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(filas)
    # Escribe el manifiesto después de validar; la sustitución de cada archivo es atómica.
    escribir_atomico(salida / f"f5_publicidad_{mes}.csv", buffer.getvalue())
    escribir_atomico(
        salida / f"f6_tasas_{fecha}.json", json.dumps(tasas, ensure_ascii=False, indent=2) + "\n"
    )
    escribir_atomico(
        salida / "f7_paises.json", json.dumps(paises, ensure_ascii=False, indent=2) + "\n"
    )
    if serie_diaria is not None:
        escribir_atomico(
            salida / f"f6_tasas_diarias_{mes}.json",
            json.dumps(serie_diaria, ensure_ascii=False, indent=2) + "\n",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="EG-30: descargar F6/F7 y generar F5")
    parser.add_argument("--mes", required=True, help="AAAA-MM")
    parser.add_argument("--salida", type=Path, default=Path("data/generated/eg30"))
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument("--diarias", action="store_true", help="incluir observaciones F6 diarias")
    args = parser.parse_args()
    try:
        ejecutar(args.mes, args.salida, args.semilla, args.diarias)
    except (OSError, ValueError) as exc:
        print(f"Error EG-30: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"F5/F6/F7 generados en {args.salida}")


if __name__ == "__main__":
    main()
