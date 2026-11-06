-- 005_orquestacion.sql · Estado de las corridas de Airflow (EG-34, EG-38) · PostgreSQL 16
-- Tablas propias del orquestador: no tocan F3/F4 ni el reporte de regalías.

-- Una fila por día UTC cuya ingesta diaria terminó completa (F6, referencia y Bronze → Silver).
-- La liquidación mensual la consulta antes de cerrar el mes. Re-procesar un día solo actualiza.
CREATE TABLE IF NOT EXISTS ingesta_diaria_estado (
    fecha        date PRIMARY KEY,
    completada_en timestamptz NOT NULL DEFAULT now(),
    run_id       text NOT NULL
);

-- Run de Silver (EG-35) verificado para ese día: el "puntero" vive aquí, no en S3. La liquidación
-- mensual lee el del último día requerido y lo pasa a Gold como --silver-run-id.
ALTER TABLE ingesta_diaria_estado ADD COLUMN IF NOT EXISTS silver_run_id text;

-- Una fila por intento de liquidación mensual, para vigilar la meta de < 1 h (RNF-01).
CREATE TABLE IF NOT EXISTS corridas_liquidacion (
    corrida_id     bigserial PRIMARY KEY,
    periodo        date NOT NULL CHECK (periodo = date_trunc('month', periodo)::date),
    run_id         text NOT NULL,
    inicio_utc     timestamptz NOT NULL,
    fin_utc        timestamptz,
    duracion_s     numeric(12,3) CHECK (duracion_s IS NULL OR duracion_s >= 0),
    estado         text NOT NULL CHECK (estado IN ('en_curso', 'ok', 'error')),
    liquidacion_id uuid,
    detalle        text,
    UNIQUE (run_id, periodo, inicio_utc)
);

CREATE INDEX IF NOT EXISTS ix_corridas_liquidacion_periodo ON corridas_liquidacion (periodo, inicio_utc);
