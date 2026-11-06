"""Liquidación SIMULADA para probar el DAG mensual sin Spark (solo pruebas locales de Airflow).

Inserta una fila publicada en ``liquidaciones`` (como haría Gold) y exige ``--silver-run-id``, para
comprobar que el DAG lo propaga. Modo con ``echo <modo> > .pruebas-silver/modo_liq.txt``:

  ok           inserta una liquidación publicada (por defecto)
  sin-version  sale con 0 sin insertar nada (el DAG debe fallar con VersionNoCreada)
  falla        falla siempre
"""

import argparse
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo", required=True, help="AAAA-MM")
    ap.add_argument("--silver-run-id", default="")
    a = ap.parse_args()
    modo_f = Path("/opt/silver-simulado/modo_liq.txt")
    modo = modo_f.read_text().strip() if modo_f.exists() else "ok"
    print(
        f"[liquidacion simulada] periodo={a.periodo} silver_run_id={a.silver_run_id!r} modo={modo}"
    )
    if modo == "falla":
        return 1
    if not a.silver_run_id:
        print("falta --silver-run-id: el DAG no lo propagó", file=sys.stderr)
        return 1
    if modo == "sin-version":
        return 0
    anio, mes = a.periodo.split("-")
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url) as c:
        c.execute(
            "INSERT INTO liquidaciones (liquidacion_id, periodo, publicada_en) "
            "VALUES (%s, %s, now())",
            (uuid.uuid4(), date(int(anio), int(mes), 1)),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
