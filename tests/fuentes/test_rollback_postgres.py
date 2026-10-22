import os
from decimal import InvalidOperation

import psycopg
import pytest

from sonoraplay.fuentes.persistencia import guardar_fuentes


def test_rollback_postgresql():
    url_configurada = os.environ.get("EG30_DATABASE_URL")
    if not url_configurada:
        pytest.skip("PostgreSQL integration test requires EG30_DATABASE_URL")

    url = url_configurada.replace("postgresql+psycopg://", "postgresql://", 1)

    with psycopg.connect(url) as conexion:
        with conexion.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM fuente_f7_paises")
            total_antes = cursor.fetchone()[0]

        paises = [
            {
                "pais": f"{chr(65 + i // 26)}{chr(65 + i % 26)}",
                "region": "Test",
                "monedas": ["USD"],
            }
            for i in range(200)
        ]

        # 200 códigos ISO-2 válidos; el fallo ocurre después de insertar F7.
        # Decimal inválido en F6 dispara rollback de los INSERT de F7.
        tasas_diarias = [
            {
                "moneda": "USD",
                "fecha": "2026-09-01",
                "unidades_por_usd": "valor_invalido",
                "proveedor": "Prueba",
            }
        ]

        with pytest.raises(InvalidOperation):
            guardar_fuentes(
                conexion,
                mes="2026-09",
                paises=paises,
                tasas_cierre=[],
                tasas_diarias=tasas_diarias,
                publicidad=[],
            )

        conexion.rollback()

        with conexion.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM fuente_f7_paises")
            total_despues = cursor.fetchone()[0]


    assert total_antes == total_despues
