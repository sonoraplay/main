"""EG-30: captura HTTP reintentable, CSV F5 reproducible y carga transaccional.

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

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

from sonoraplay.config import database_url
from sonoraplay.fuentes.carga import cargar
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


def escribir_conjunto(archivos: dict[Path, str]) -> None:
    """Escribe todos los temporales primero y solo después los reemplaza.

    Si falla la escritura de cualquier temporal, no se reemplaza ningún archivo.
    """
    temporales: dict[Path, Path] = {}
    try:
        for destino, contenido in archivos.items():
            destino.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=destino.parent, delete=False
            ) as fh:
                temporales[destino] = Path(fh.name)
                fh.write(contenido)
        for destino, temporal in temporales.items():
            os.replace(temporal, destino)
    finally:
        for temporal in temporales.values():
            temporal.unlink(missing_ok=True)


def ejecutar(
    mes: str,
    salida: Path,
    semilla: int = 2026,
    diarias: bool = True,
    engine: Engine | None = None,
) -> dict[str, int] | None:
    """Descarga y valida F6/F7, genera F5, carga en PostgreSQL y escribe los archivos.

    Orden: 1) validar todo; 2) cargar en PostgreSQL en una sola transacción (si hay
    `engine`); 3) escribir los archivos. Si algo falla antes, no queda nada a medias.
    """
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

    conteos = None
    if engine is not None:
        conteos = cargar(engine, paises, tasas, serie_diaria, filas, semilla)

    def a_json(datos: object) -> str:
        return json.dumps(datos, ensure_ascii=False, indent=2) + "\n"

    archivos = {
        salida / f"f5_publicidad_{mes}.csv": buffer.getvalue(),
        salida / f"f6_tasas_{fecha}.json": a_json(tasas),
        salida / "f7_paises.json": a_json(paises),
    }
    if serie_diaria is not None:
        archivos[salida / f"f6_tasas_diarias_{mes}.json"] = a_json(serie_diaria)
    escribir_conjunto(archivos)
    return conteos


def main() -> None:
    parser = argparse.ArgumentParser(description="EG-30: descargar F6/F7, generar F5 y cargar")
    parser.add_argument("--mes", required=True, help="AAAA-MM")
    parser.add_argument("--salida", type=Path, default=Path("data/generated/eg30"))
    parser.add_argument("--semilla", type=int, default=2026)
    parser.add_argument(
        "--sin-diarias", action="store_true", help="solo la tasa de cierre, sin la serie diaria"
    )
    parser.add_argument(
        "--cargar", action="store_true", help="cargar en PostgreSQL (usa DATABASE_URL)"
    )
    args = parser.parse_args()
    try:
        engine = create_engine(database_url()) if args.cargar else None
        conteos = ejecutar(args.mes, args.salida, args.semilla, not args.sin_diarias, engine)
    except (OSError, ValueError, SQLAlchemyError) as exc:
        print(f"Error EG-30: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"F5/F6/F7 generados en {args.salida}")
    if conteos is not None:
        print("Cargado en PostgreSQL: " + ", ".join(f"{t}={n}" for t, n in conteos.items()))


if __name__ == "__main__":
    main()
