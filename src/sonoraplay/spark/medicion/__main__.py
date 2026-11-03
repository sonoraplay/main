"""CLI del arnés: ``generar``, ``medir`` e ``informe``.

    uv run --with pyspark==4.0.1 python -m sonoraplay.spark.medicion generar --destino /tmp/eg39 \\
        --reproducciones 1000000
    uv run --with pyspark==4.0.1 python -m sonoraplay.spark.medicion medir --datos /tmp/eg39 \\
        --salida /tmp/eg39/resultados.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sonoraplay.spark.medicion import medir
from sonoraplay.spark.medicion.generador import Parametros, generar


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="medicion")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generar", help="genera un mes sintético sesgado")
    g.add_argument("--destino", required=True)
    g.add_argument("--reproducciones", type=int, default=Parametros.reproducciones)
    g.add_argument("--usuarios", type=int, default=Parametros.usuarios)
    g.add_argument("--artistas", type=int, default=Parametros.artistas)
    g.add_argument("--sesgo", type=float, default=Parametros.sesgo)
    g.add_argument("--semilla", type=int, default=Parametros.semilla)

    m = sub.add_parser("medir", help="corre las variantes y guarda los resultados")
    m.add_argument("--datos", required=True, help="carpeta creada por `generar`")
    m.add_argument("--salida", required=True, help="archivo JSON de resultados")
    m.add_argument("--variantes", nargs="*", default=list(medir.VARIANTES))
    m.add_argument("--hasta", default=None, help="AAAA-MM-DD: procesa hasta esa fecha (poda)")
    m.add_argument("--repeticiones", type=int, default=3)
    m.add_argument("--nucleos", type=int, default=2)
    m.add_argument("--memoria", default="6g")
    m.add_argument("--evento-log", default=None, help="carpeta para el historial de Spark UI")

    i = sub.add_parser("informe", help="tabla Markdown desde el JSON de resultados")
    i.add_argument("resultados")
    i.add_argument("--precio-vcpu-h", type=float)
    i.add_argument("--precio-gb-h", type=float)

    a = ap.parse_args(argv)
    if a.cmd == "generar":
        from pyspark.sql import SparkSession

        spark = (
            SparkSession.builder.master("local[*]")
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.driver.memory", "6g")
            .getOrCreate()
        )
        p = Parametros(
            reproducciones=a.reproducciones,
            usuarios=a.usuarios,
            artistas=a.artistas,
            sesgo=a.sesgo,
            semilla=a.semilla,
        )
        print(json.dumps(generar(spark, a.destino, p), indent=2))
        return 0
    if a.cmd == "medir":
        if "base" not in a.variantes:
            print("La variante `base` es obligatoria: es la referencia.", file=sys.stderr)
            return 2
        resultados = [
            medir.correr(
                medir.VARIANTES[n],
                f"{a.datos}/bronze",
                f"{a.datos}/catalogo",
                f"{a.datos}/salida",
                hasta=a.hasta,
                repeticiones=a.repeticiones,
                memoria=a.memoria,
                nucleos=a.nucleos,
                evento_log=a.evento_log,
            )
            for n in a.variantes
        ]
        problemas = medir.verificar_identico(resultados)
        Path(a.salida).write_text(
            json.dumps(
                {
                    "entorno": medir.entorno(a.nucleos, a.memoria),
                    "datos": a.datos,
                    "hasta": a.hasta,
                    "resultados": resultados,
                    "problemas": problemas,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        for p in problemas:
            print("DIFERENCIA:", p, file=sys.stderr)
        return 1 if problemas else 0
    datos = json.loads(Path(a.resultados).read_text(encoding="utf-8"))
    print(
        medir.informe(
            datos["resultados"],
            {"entorno": json.dumps(datos["entorno"], ensure_ascii=False), "datos": datos["datos"]},
            a.precio_vcpu_h,
            a.precio_gb_h,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
