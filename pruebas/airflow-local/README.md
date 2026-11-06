# Pruebas locales de Airflow (EG-34 y EG-38) sin AWS

Prueban la **orquestación** (2 workers, reintentos, idempotencia, verificación del marcador, sensor, versiones de la liquidación). Silver y la liquidación están **simulados**: la cadena real de Spark se probó aparte. Todo corre en Docker en tu computador y no cuesta nada.

Los pasos están en la conversación con Claude. Resumen de archivos:

- `docker-compose.pruebas.yml`: añade a los workers el directorio compartido `.pruebas-silver` y los comandos simulados.
- `silver_simulado.py`: escribe `commits/<run_id>.json` sin sobrescribir. Modo en `.pruebas-silver/modo.txt`: `ok`, `falla-1`, `sin-marcador`, `falla`.
- `liquidacion_simulada.py`: inserta una liquidación publicada y exige `--silver-run-id`. Modo en `.pruebas-silver/modo_liq.txt`: `ok`, `sin-version`, `falla`.
- `cargar_dias.sql`: marca como ingeridos los 33 días que exige octubre 2026.
