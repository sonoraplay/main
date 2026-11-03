"""EG-46 · El diccionario de datos y el DDL no pueden desincronizarse."""

import os
import re
import uuid
from pathlib import Path

import psycopg
import pytest

RAIZ = Path(__file__).resolve().parents[1]
DICCIONARIO = RAIZ / "docs" / "datos" / "diccionario-de-datos.md"
DDL = sorted(RAIZ.glob("db/ddl/00[1-4]_*.sql"))  # 005 vive en los PR de EG-34/EG-38


def del_diccionario() -> dict[str, set[str]]:
    """Tablas (`#### `tabla``) y sus columnas (primera celda de cada fila) del Markdown."""
    tablas: dict[str, set[str]] = {}
    actual = None
    for linea in DICCIONARIO.read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^#### `([a-z_0-9]+)`", linea):
            actual = m.group(1)
            tablas[actual] = set()
        elif linea.startswith("## ") or linea.startswith("### "):
            actual = None
        elif actual and (m := re.match(r"^\| `([a-z_0-9]+)` \|", linea)):
            tablas[actual].add(m.group(1))
    return tablas


@pytest.fixture
def columnas_del_ddl() -> dict[str, set[str]]:
    url = os.environ.get("EG30_DATABASE_URL")
    if not url:
        pytest.skip("requiere EG30_DATABASE_URL (PostgreSQL)")
    esquema = f"t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1)) as c:
        c.execute(f"CREATE SCHEMA {esquema}")
        c.execute(f"SET search_path TO {esquema}")
        for f in DDL:
            c.execute(f.read_text(encoding="utf-8"))
        filas = c.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = %s",
            (esquema,),
        ).fetchall()
        c.execute(f"DROP SCHEMA {esquema} CASCADE")
        c.commit()
    tablas: dict[str, set[str]] = {}
    for t, col in filas:
        tablas.setdefault(t, set()).add(col)
    return tablas


def test_el_diccionario_cubre_exactamente_las_tablas_y_columnas_del_ddl(columnas_del_ddl):
    doc = del_diccionario()
    assert set(doc) == set(columnas_del_ddl), "tablas distintas entre el DDL y el diccionario"
    for tabla, columnas in columnas_del_ddl.items():
        assert doc[tabla] == columnas, f"{tabla}: columnas distintas"


def test_cada_fila_del_diccionario_tiene_descripcion():
    texto = DICCIONARIO.read_text(encoding="utf-8")
    assert "Estado: borrador por revisar" in texto  # no afirma una revisión que no ocurrió
    for linea in texto.splitlines():
        if re.match(r"^\| `[a-z_0-9]+` \|", linea):
            celdas = [c.strip() for c in linea.strip("|").split("|")]
            assert all(celdas), f"celda vacía: {linea}"
