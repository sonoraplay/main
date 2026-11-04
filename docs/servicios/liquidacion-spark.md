---
title: "EG-37 · Liquidación en Spark (Gold) / Settlement in Spark (Gold)"
---

# EG-37 · Liquidación de regalías en Spark (Gold)

`src/sonoraplay/spark/gold.py` liquida un mes **reutilizando las reglas puras de la EG-23**, sin reescribirlas:

1. **Distribuido.** Las reproducciones pagables del período (Silver) se unen con el país de facturación y el componente de cada usuario (F3) y el titular de la pista (F1), y se agrupan por país, componente, titular, pista, fecha UTC y país de reproducción. Cada grupo pide su % a `porcentaje_aplicable` (RN-07, RN-08, Q7).
2. **En el driver (pocas filas).** Los conteos por (componente, titular, %) de cada país se reparten con `repartir_bolsa`, la misma función que usa `liquidar_pais` (se extrajo de ella; las pruebas de la EG-23 siguen pasando). Así el redondeo al centavo es idéntico (RNF-02).
3. **Trazabilidad (RNF-03).** `plays_liquidados` guarda cada reproducción pagada con su `liquidacion_id` (Parquet particionado por período, país de facturación y liquidación).
4. **Append-only (ADR-0007, CA-07).** Cada `run_id` produce un `liquidacion_id` determinista (UUIDv5). Un `run_id` nuevo agrega una liquidación nueva y no toca las anteriores; repetir el mismo `run_id` no duplica filas, y si el resultado difiere de lo ya cargado lanza error en vez de sobrescribir.

```python
salida, plays = liquidar(
    spark, silver, usuarios, catalogo, condiciones, bolsas, date(2026, 9, 1), run_id
)
escribir_gold(salida, plays, "s3://<gold>/")
cargar_rds(conexion_psycopg, salida)  # una transacción; publicada_en al final
```

Entradas: `silver` (salida de la EG-35: `play_id, user_id, track_id, country, inicio_utc, mes_liquidacion, pagable`), `usuarios` (`user_id, pais_facturacion, componente`), `catalogo` (`track_id, titular_id`), `condiciones` (F4 como `CondicionContrato`) y `bolsas` (una `BolsaPais` por país). Si falta la bolsa de un país o un usuario no tiene país de facturación, **falla**: no inventa datos.

## Qué está probado y qué no

| Criterio | Estado |
|---|---|
| 1 · Mismas pruebas que la EG-23 en Spark | Probado por **comparación**: 1 500 reproducciones aleatorias con sesgo, cambio de % a mitad de mes, % territorial y 3 países dan las mismas filas, regalías, conteos, participaciones e incidentes que `liquidar_pais`. No se portó cada caso nombrado de `tests/reglas/test_liquidacion.py` |
| 2 · Re-liquidación agrega y no actualiza | Probado contra PostgreSQL: un `run_id` nuevo crea una segunda liquidación y la original queda idéntica |
| 3 · Regalía rastreable a sus reproducciones | Probado: cada reproducción liquidada lleva su `liquidacion_id` y los conteos por fila coinciden |
| 4 · Suma por país ≤ bolsa (± 0,01 USD) | Probado con bolsas que fuerzan el redondeo (100,005 USD, etc.) |
| 5 · Carga a RDS sin duplicar al repetir el `run_id` | Probado contra PostgreSQL local (esquema de `db/ddl/001-003`) |

**No probado:** la corrida contra el Silver real de la EG-35 (su PR #38 sigue en borrador), contra S3 y RDS en AWS, ni el rendimiento con el volumen completo. El cálculo de las **bolsas** a partir de F3, F5 y F6 no está en este job: llega como argumento. La reproducción liquidada no distingue los ajustes de meses anteriores (RN-04) más allá de la columna `mes_liquidacion` que ya trae Silver.

## Integración con Bronze (EG-33) y Silver (EG-35)

`tests/spark/test_integracion_bronze_silver_gold.py` prueba la cadena **Bronze en S3 → Silver verificado → liquidación Gold** de punta a punta, con un directorio local en lugar de S3:

1. Escribe 400 reproducciones (800 eventos) con `AlmacenBronzeS3` y re-entrega 250 con otros límites de lote, para tener **duplicados reales** entre objetos.
2. Silver las lee (`write_historical_snapshot`), publica el marcador (`publish_verified_snapshot`) y Gold lee **solo el `run_id` verificado** (`read_verified_snapshot`).
3. Comprueba que Silver quita los duplicados (una reproducción por sesión), que las pagables son exactamente las de ≥ 30 s (RN-01) y que Gold da **las mismas filas y regalías que `liquidar_pais`** sobre la misma verdad de campo, con la suma por país ≤ la bolsa (RNF-02).

**Se salta mientras las tres ramas no estén fusionadas** (necesita `silver.py` del PR #38 y `bronze_s3.py` del PR #49). Se corrió una vez en una combinación local de las tres ramas: 2 pruebas pasan en 78 s. **No corre todavía en el CI.**

### Lo que falta para ejecutar Gold en AWS
- **No hay punto de entrada** (`python -m sonoraplay.spark.gold`): el DAG mensual ejecuta `LIQUIDACION_JOB_COMMAND` con `{periodo}` y hoy no hay nada que ejecutar.
- **Nada carga los insumos desde AWS:** país y componente de cada usuario (F3), contratos (F4) y las bolsas (F3, F5, F6). Gold los recibe ya cargados.
- **Imagen `spark` y tarea en ECS:** no existe `docker/spark.Dockerfile` ni una definición de tarea de Spark en Terraform, y ningún archivo configura el acceso de Spark a S3 (JAR de `hadoop-aws` y del SDK de AWS).
- Al fusionar #38 y #50, **`.github/workflows/ci.yml` tendrá conflicto**: hay que conservar completos los dos jobs (`spark-silver` y `spark-gold`).

