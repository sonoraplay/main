"""Silver SIMULADO para probar el DAG diario sin Spark (solo pruebas locales de Airflow).

Hace lo que hace el CLI real desde el punto de vista del DAG: escribe ``commits/<run_id>.json``
sin sobrescribir y sale con 0 solo si lo escribió. El modo se cambia sin reiniciar nada con
``echo <modo> > .pruebas-silver/modo.txt``:

  ok            publica el marcador (por defecto)
  falla-1       falla el primer intento de cada fecha y publica en el siguiente
  sin-marcador  sale con 0 pero NO escribe marcador (el DAG no debe marcar el día)
  falla         falla siempre
"""

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path("/opt/silver-simulado")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", required=True)
    ap.add_argument("--run-id", required=True)
    a = ap.parse_args()
    modo_f = RAIZ / "modo.txt"
    modo = modo_f.read_text().strip() if modo_f.exists() else "ok"
    print(f"[silver simulado] fecha={a.fecha} run_id={a.run_id} modo={modo}", flush=True)
    if modo == "falla":
        print("fallo simulado", file=sys.stderr)
        return 1
    if modo == "falla-1":
        marca = RAIZ / "intentos" / a.fecha
        if not marca.exists():
            marca.parent.mkdir(parents=True, exist_ok=True)
            marca.write_text(a.run_id)
            print("primer intento: fallo simulado", file=sys.stderr)
            return 1
    if modo == "sin-marcador":
        return 0
    destino = RAIZ / "commits" / f"{a.run_id}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        print(f"el marcador {destino} ya existe: no se sobrescribe", file=sys.stderr)
        return 1
    carga = {
        "schema_version": "eg35-commit-v1",
        "run_id": a.run_id,
        "fecha": a.fecha,
        "silver_rows": 38,
        "quarantine_rows": 0,
    }
    destino.write_text(json.dumps(carga, sort_keys=True), encoding="utf-8")
    print(json.dumps(carga), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
