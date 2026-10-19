"""EG-30 persistence tests: transaction semantics without a live PostgreSQL server."""

from datetime import date

import pytest

from sonoraplay.fuentes.persistencia import guardar_fuentes


class Cursor:
    def __init__(self, fail_at=None):
        self.statements = []
        self.fail_at = fail_at

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.statements.append((sql, params))
        if self.fail_at == len(self.statements):
            raise RuntimeError("simulated database failure")


class Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.started = True
        return self

    def __exit__(self, typ, *_):
        self.connection.rolled_back = typ is not None
        self.connection.committed = typ is None
        return False


class Connection:
    def __init__(self, fail_at=None):
        self.cur = Cursor(fail_at)
        self.started = False
        self.rolled_back = False
        self.committed = False

    def transaction(self):
        return Transaction(self)

    def cursor(self):
        return self.cur


def payload():
    paises = [
        {"pais": f"{chr(65 + n // 26)}{chr(65 + n % 26)}",
         "region": "Other", "monedas": ["USD"]}
        for n in range(200)
    ]
    paises[0] = {"pais": "ZZ", "region": "Other", "monedas": ["USD"]}\n    paises[66] = {"pais": "CO", "region": "Americas", "monedas": ["COP"]}
    return {
        "mes": "2026-09",
        "paises": paises,
        "tasas_cierre": [{
            "moneda": "COP", "fecha": "2026-09-30",
            "fecha_observacion": "2026-09-30",
            "unidades_por_usd": "4000.12", "proveedor": "Frankfurter v2",
        }],
        "tasas_diarias": [{
            "moneda": "COP", "fecha": "2026-09-30",
            "unidades_por_usd": "4000.12", "proveedor": "Frankfurter v2",
        }],
        "publicidad": [{
            "pais": "CO", "moneda": "COP", "ingresos_publicidad": "120.00",
        }],
    }


def test_upserts_are_in_one_transaction():
    db = Connection()
    guardar_fuentes(db, **payload())
    assert db.started and db.committed and not db.rolled_back
    assert len(db.cur.statements) == 203
    assert all("ON CONFLICT" in sql for sql, _ in db.cur.statements)
    assert db.cur.statements[-1][1][0] == date(2026, 9, 1)


def test_db_failure_rolls_back_entire_batch():
    db = Connection(fail_at=202)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        guardar_fuentes(db, **payload())
    assert db.started and db.rolled_back and not db.committed


def test_duplicate_country_rejected_before_transaction():
    data = payload()
    data["paises"].append(data["paises"][0])
    db = Connection()
    with pytest.raises(ValueError, match="únicos"):
        guardar_fuentes(db, **data)
    assert not db.started
