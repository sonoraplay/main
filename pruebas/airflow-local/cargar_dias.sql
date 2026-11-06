-- Marca como ingeridos los 33 días que exige el DAG mensual para liquidar OCTUBRE 2026
-- (todo el mes más los 2 días de gracia de RN-04), cada uno con su silver_run_id.
INSERT INTO ingesta_diaria_estado (fecha, run_id, silver_run_id)
SELECT d::date, 'prueba-manual', 'prueba-manual.1.' || to_char(d, 'YYYYMMDD')
FROM generate_series(date '2026-10-01', date '2026-11-02', interval '1 day') AS d
ON CONFLICT (fecha) DO UPDATE SET silver_run_id = EXCLUDED.silver_run_id;
