"""EG-27 · database_url(): local con DATABASE_URL y en ECS con las partes que inyecta SSM."""

import pytest
from sqlalchemy.engine import make_url

from sonoraplay.config import PARTES_DB, database_url

PARTES = {
    "DB_HOST": "sonoraplay-dev.abc.us-east-1.rds.amazonaws.com",
    "DB_PORT": "5432",
    "DB_NAME": "sonoraplay",
    "DB_USER": "sonora",
    "DB_PASSWORD": "p@ss:w/rd#%?&=",
}


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for v in ("DATABASE_URL", "DB_SSLMODE", *PARTES_DB):
        monkeypatch.delenv(v, raising=False)


def test_database_url_tiene_prioridad(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://a:b@localhost:5432/x")
    for k, v in PARTES.items():
        monkeypatch.setenv(k, v)
    assert database_url() == "postgresql+psycopg://a:b@localhost:5432/x"


def test_arma_la_url_desde_las_partes_y_codifica_la_contrasena(monkeypatch):
    for k, v in PARTES.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DB_SSLMODE", "require")
    url = make_url(database_url())
    assert url.drivername == "postgresql+psycopg"
    assert url.password == PARTES["DB_PASSWORD"]  # vuelve intacta tras decodificarse
    assert (url.host, url.port, url.database, url.username) == (
        PARTES["DB_HOST"],
        5432,
        "sonoraplay",
        "sonora",
    )
    assert url.query == {"sslmode": "require"}


def test_sin_sslmode_no_agrega_parametros(monkeypatch):
    for k, v in PARTES.items():
        monkeypatch.setenv(k, v)
    assert "?" not in database_url()


def test_faltan_partes(monkeypatch):
    for k, v in PARTES.items():
        if k != "DB_PASSWORD":
            monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit, match="DB_HOST"):
        database_url()
