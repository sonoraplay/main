-- EG-30 · F5/F6/F7 source tables (PostgreSQL 16)
-- Isolated from F3/F4/royalty reporting tables; load all three sources in one transaction.
CREATE TABLE IF NOT EXISTS fuente_f7_paises (
    pais char(2) PRIMARY KEY CHECK (pais ~ '^[A-Z]{2}$'),
    region text NOT NULL,
    monedas text[] NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fuente_f6_tasas_diarias (
    moneda char(3) NOT NULL CHECK (moneda ~ '^[A-Z]{3}$'),
    fecha_observacion date NOT NULL,
    unidades_por_usd numeric(24,10) NOT NULL CHECK (unidades_por_usd > 0),
    proveedor text NOT NULL,
    extraido_en_utc timestamptz NOT NULL,
    PRIMARY KEY (moneda, fecha_observacion)
);

CREATE TABLE IF NOT EXISTS fuente_f6_cierres (
    moneda char(3) NOT NULL CHECK (moneda ~ '^[A-Z]{3}$'),
    fecha_cierre date NOT NULL,
    fecha_observacion date NOT NULL,
    unidades_por_usd numeric(24,10) NOT NULL CHECK (unidades_por_usd > 0),
    proveedor text NOT NULL,
    extraido_en_utc timestamptz NOT NULL,
    PRIMARY KEY (moneda, fecha_cierre),
    CHECK (fecha_observacion <= fecha_cierre)
);

CREATE TABLE IF NOT EXISTS fuente_f5_publicidad (
    mes date NOT NULL CHECK (mes = date_trunc('month', mes)::date),
    pais char(2) NOT NULL REFERENCES fuente_f7_paises(pais),
    moneda char(3) NOT NULL,
    ingresos_publicidad numeric(18,2) NOT NULL CHECK (ingresos_publicidad >= 0),
    PRIMARY KEY (mes, pais)
);

-- The ingestion application must wrap F7/F6/F5 upserts in a single BEGIN/COMMIT,
-- and roll back the entire batch on any validation, network or database failure.
