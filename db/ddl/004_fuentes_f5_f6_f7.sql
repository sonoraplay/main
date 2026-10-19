-- 004_fuentes_f5_f6_f7.sql · Fuentes externas de la bolsa (PostgreSQL 16)
-- EG-30 · RN-05 · F5 (publicidad simulada), F6 (tasas de cambio), F7 (países)
-- Carga: src/sonoraplay/fuentes/carga.py, una sola transacción con UPSERT (idempotente).
-- Detalle: docs/datos/eg30-fuentes-f5-f6-f7.md

-- F7 · REST Countries. Una fila por país ISO-2.
CREATE TABLE IF NOT EXISTS paises (
    pais           char(2) PRIMARY KEY CHECK (pais ~ '^[A-Z]{2}$'),
    region         text NOT NULL,
    -- Códigos ISO 4217 que usa el país; puede estar vacío (p. ej. Antártida).
    monedas        text[] NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

-- F6 · Unidades de moneda local por 1 USD.
-- tipo = 'diaria': una fila por observación publicada (sin inventar fines de semana ni festivos).
-- tipo = 'cierre': una fila por moneda y mes, con fecha = último día del mes UTC (RN-05, ADR-0002);
--                  fecha_observacion es el último día con cotización publicada en ese mes.
CREATE TABLE IF NOT EXISTS tasas_cambio (
    moneda            char(3) NOT NULL CHECK (moneda ~ '^[A-Z]{3}$'),
    fecha             date NOT NULL,
    tipo              text NOT NULL CHECK (tipo IN ('diaria', 'cierre')),
    unidades_por_usd  numeric(20,8) NOT NULL CHECK (unidades_por_usd > 0),
    fecha_observacion date NOT NULL,
    proveedor         text NOT NULL,
    actualizado_en    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (moneda, fecha, tipo),
    CHECK (fecha_observacion <= fecha),
    CHECK (tipo = 'cierre' OR fecha_observacion = fecha),
    -- El cierre cae el último día del mes.
    CHECK (tipo = 'diaria' OR fecha = (date_trunc('month', fecha) + interval '1 month - 1 day')::date)
);

-- F5 · Ingresos publicitarios simulados del mes, en moneda local (se convierten con F6 al liquidar).
CREATE TABLE IF NOT EXISTS ingresos_publicidad (
    -- Primer día del mes UTC (ADR-0002).
    periodo        date NOT NULL CHECK (periodo = date_trunc('month', periodo)::date),
    pais           char(2) NOT NULL REFERENCES paises (pais),
    moneda         char(3) NOT NULL CHECK (moneda ~ '^[A-Z]{3}$'),
    ingresos       numeric(14,2) NOT NULL CHECK (ingresos >= 0),
    -- Semilla del generador: con la misma semilla y mes, el CSV es idéntico.
    semilla        integer NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (periodo, pais)
);
