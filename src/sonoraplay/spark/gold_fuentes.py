"""EG-37 · Entradas de la liquidación (F1, F3, F4, F5, F6) para el CLI de Gold.

Solo lee PostgreSQL y el catálogo F1; no usa Spark. Las reglas de negocio siguen en
``sonoraplay.reglas.liquidacion`` (país Q6/RN-10, bolsa Q5/Q8, conversión F6) y el plan vigente
por fecha replica ``plan_vigente`` del esqueleto: ``hasta`` exclusivo, y un miembro de familia usa
la suscripción del titular de su grupo cuando no tiene una propia.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from sonoraplay.config import ReglasLiquidacionConfig
from sonoraplay.reglas.liquidacion import (
    BolsaPais,
    CondicionContrato,
    Pago,
    TasaCambio,
    calcular_bolsa,
    convertir_a_usd,
    paises_facturacion,
    suscripcion_neta_por_pais,
)


@dataclass(frozen=True)
class EntradasGold:
    usuarios: list[tuple[str, str]]  # (user_id, pais_facturacion)
    suscripciones: list[
        tuple[str, str, date, date | None, int]
    ]  # user, componente, desde, hasta, prio
    catalogo: list[tuple[str, str]]  # (track_id, titular_id)
    condiciones: list[CondicionContrato]
    bolsas: list[BolsaPais]


def _texto(valor: str | None) -> str | None:
    return (valor or "").strip() or None


def _siguiente_mes(periodo: date) -> date:
    return date(periodo.year + (periodo.month == 12), periodo.month % 12 + 1, 1)


def suscripciones_efectivas(
    suscripciones: dict[str, list[tuple[str, date, date | None]]],
    titular_de_familia: dict[str, str],
    usuarios: list[str],
) -> list[tuple[str, str, date, date | None, int]]:
    """Filas ``(usuario, componente, desde, hasta, prioridad)``: propias (0) y del titular (1)."""
    from sonoraplay.esqueleto.pipeline import componente_de_plan

    filas = []
    for u in usuarios:
        for plan, desde, hasta in suscripciones.get(u, ()):
            filas.append((u, str(componente_de_plan(plan)), desde, hasta, 0))
        duenio = titular_de_familia.get(u)
        if duenio is not None:
            for plan, desde, hasta in suscripciones.get(duenio, ()):
                filas.append((u, str(componente_de_plan(plan)), desde, hasta, 1))
    return filas


def bolsas_del_periodo(
    periodo: date,
    pagos: list[Pago],
    pais_de_usuario: dict[str, str],
    publicidad: dict[str, tuple[str, Decimal]],
    tasas: dict[str, TasaCambio],
    cfg: ReglasLiquidacionConfig | None = None,
) -> list[BolsaPais]:
    """Una bolsa por país (Q5/Q8). Publicidad F5 en moneda local, convertida con el cierre F6.

    Falla si un país con suscripción neta o con ingresos F5 no tiene todo lo necesario: no se
    liquida con una bolsa inventada.
    """
    cfg = cfg or ReglasLiquidacionConfig()
    neta = suscripcion_neta_por_pais(
        [p for p in pagos if p.usuario_id in pais_de_usuario], pais_de_usuario
    )
    paises = sorted(set(neta) | set(publicidad))
    bolsas = []
    for pais in paises:
        if pais not in publicidad:
            raise ValueError(f"{pais}: falta F5 (ingresos de publicidad) de {periodo:%Y-%m}")
        moneda, monto = publicidad[pais]
        if moneda not in tasas:
            raise ValueError(f"{pais}: falta el cierre F6 de {moneda} para {periodo:%Y-%m}")
        usd = convertir_a_usd(monto, moneda, tasas[moneda], periodo)
        bolsas.append(calcular_bolsa(pais, neta.get(pais, Decimal(0)), usd, cfg))
    return bolsas


def _descargar_s3(ubicacion: str, cliente=None) -> Path:
    """``s3://bucket/prefijo`` (o ``.../catalogo_f1.parquet``) a un archivo temporal local."""
    import tempfile

    bucket, _, clave = ubicacion.removeprefix("s3://").partition("/")
    if not clave.endswith(".parquet"):
        clave = f"{clave.rstrip('/')}/catalogo_f1.parquet".lstrip("/")
    if cliente is None:
        import boto3

        cliente = boto3.client("s3")
    destino = Path(tempfile.mkdtemp(prefix="f1_")) / "catalogo_f1.parquet"
    cliente.download_file(bucket, clave, str(destino))
    return destino


def leer_catalogo_f1(ruta: str | Path, cliente_s3=None) -> list[tuple[str, str]]:
    """Catálogo F1 (``track_id``, ``titular_id``) desde un directorio, un parquet o ``s3://``."""
    import pandas as pd

    if str(ruta).startswith("s3://"):
        ruta = _descargar_s3(str(ruta), cliente_s3)
    ruta = Path(ruta)
    if ruta.is_dir():
        ruta = ruta / "catalogo_f1.parquet"
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el catálogo F1: {ruta}")
    cat = pd.read_parquet(ruta, columns=["track_id", "titular_id"]).drop_duplicates()
    repetidas = cat["track_id"][cat["track_id"].duplicated()]
    if not repetidas.empty:
        raise ValueError(f"pistas con más de un titular en F1: {sorted(repetidas)[:5]}")
    return [(str(t), str(h)) for t, h in cat.itertuples(index=False)]



def leer_artistas_f1(ruta: str | Path, cliente_s3=None) -> list[tuple[str, str]]:
    """EG-36: F1 main-artist mapping, separate from royalty ownership.

    No inferred artist IDs: RN-03 uses the canonical F1 artista_principal.
    """
    import pandas as pd

    if str(ruta).startswith("s3://"):
        ruta = _descargar_s3(str(ruta), cliente_s3)
    ruta = Path(ruta)
    if ruta.is_dir():
        ruta = ruta / "catalogo_f1.parquet"
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el catálogo F1: {ruta}")
    cat = pd.read_parquet(ruta, columns=["track_id", "artista_principal"])
    if cat[["track_id", "artista_principal"]].isna().any().any():
        raise ValueError("EG-36: F1 tiene pistas o artistas nulos")
    if cat["track_id"].duplicated().any():
        raise ValueError("EG-36: F1 tiene track_id duplicados")
    if cat["artista_principal"].astype(str).str.strip().eq("").any():
        raise ValueError("EG-36: F1 tiene artistas vacíos")
    return [(str(t), str(a)) for t, a in cat.itertuples(index=False)]


def leer_entradas(conexion, periodo: date, ruta_catalogo: str | Path) -> EntradasGold:
    """Lee F1, F3, F4, F5 y F6 del período con una conexión psycopg."""
    if periodo.day != 1:
        raise ValueError("periodo debe ser el primer día del mes")
    catalogo = leer_catalogo_f1(ruta_catalogo)
    q = conexion.execute
    pais_raw = {
        u: _texto(p) for u, p in q("SELECT usuario_id::text, pais_facturacion FROM usuarios")
    }
    familias = dict(
        q(
            "SELECT m.usuario_id::text, g.titular_id::text FROM miembros_familia m "
            "JOIN grupos_familiares g USING (grupo_id) WHERE m.rol = 'miembro'"
        ).fetchall()
    )
    # RN-10: país del titular. Un país nulo es un defecto de F3 que depura Silver: se excluye al
    # usuario y Gold falla si aparece en una reproducción pagable (no se inventa un país).
    conocidos = {u: p for u, p in pais_raw.items() if pais_raw.get(familias.get(u, u)) is not None}
    pais_de_usuario = paises_facturacion(conocidos, familias)

    subs: dict[str, list[tuple[str, date, date | None]]] = defaultdict(list)
    for u, plan, desde, hasta in q(
        "SELECT s.usuario_id::text, p.codigo, s.fecha_inicio, s.fecha_fin "
        "FROM suscripciones s JOIN planes p USING (plan_id)"
    ):
        subs[u].append((plan, desde, hasta))

    pagos = [
        Pago(u, Decimal(monto), estado)
        for u, monto, estado in q(
            "SELECT s.usuario_id::text, p.monto_usd, p.estado FROM pagos p "
            "JOIN suscripciones s USING (suscripcion_id) "
            "WHERE p.fecha_pago >= %s AND p.fecha_pago < %s",
            (periodo, _siguiente_mes(periodo)),
        )
    ]
    publicidad = {
        pais.strip(): (moneda.strip(), Decimal(monto))
        for pais, moneda, monto in q(
            "SELECT pais, moneda, ingresos_publicidad FROM fuente_f5_publicidad WHERE mes = %s",
            (periodo,),
        )
    }
    cierre = _siguiente_mes(periodo).replace(day=1)
    ultimo = date.fromordinal(cierre.toordinal() - 1)
    tasas = {
        m.strip(): TasaCambio(m.strip(), f, Decimal(t))
        for m, f, t in q(
            "SELECT moneda, fecha_cierre, unidades_por_usd FROM fuente_f6_cierres "
            "WHERE fecha_cierre = %s",
            (ultimo,),
        )
    }
    contratos = q(
        "SELECT c.contrato_id, c.titular_id, c.track_id, c.porcentaje, c.valido_desde, "
        "c.valido_hasta, c.territorio, "
        "coalesce(array_agg(e.pais) FILTER (WHERE e.pais IS NOT NULL), '{}') "
        "FROM contratos c LEFT JOIN exclusiones_territoriales e USING (contrato_id) "
        "WHERE c.track_id = ANY(%s) GROUP BY c.contrato_id",
        ([t for t, _ in catalogo],),
    ).fetchall()
    condiciones = [
        CondicionContrato(
            contrato_id=cid,
            titular_id=tid,
            track_id=track,
            porcentaje=pct,
            valido_desde=desde,
            valido_hasta=hasta,
            territorio=_texto(territorio),
            exclusiones=frozenset(x.strip() for x in excl),
        )
        for cid, tid, track, pct, desde, hasta, territorio, excl in contratos
    ]
    return EntradasGold(
        usuarios=sorted(pais_de_usuario.items()),
        suscripciones=suscripciones_efectivas(subs, familias, sorted(pais_de_usuario)),
        catalogo=catalogo,
        condiciones=condiciones,
        bolsas=bolsas_del_periodo(periodo, pagos, pais_de_usuario, publicidad, tasas),
    )
