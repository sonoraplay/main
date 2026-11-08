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


## CLI mensual y plan por fecha

`python -m sonoraplay.spark.gold --periodo AAAA-MM --silver-run-id ID --run-id ID --silver RUTA --cuarentena RUTA --gold RUTA --catalogo RUTA_F1 [--database-url URL]` (las rutas y `DATABASE_URL` también se leen de `SONORAPLAY_*`). Es el comando que espera `LIQUIDACION_JOB_COMMAND`; el DAG mensual le pasa `{silver_run_id}`.

- Lee **solo** un run de Silver con marcador de commit (`read_verified_snapshot`); sin marcador no corre.
- Lee F1 (parquet), F3, F4, F5 y F6 con `sonoraplay.spark.gold_fuentes`. La bolsa de cada país sale de los pagos aprobados del mes (Q5), de los ingresos F5 convertidos con el cierre F6 del último día del mes y de las fracciones de Q8. Si falta F5 o el cierre F6 de un país, falla.
- **El componente (suscripción o publicidad) se toma del plan vigente en la fecha UTC de cada reproducción** (`desde <= fecha < hasta`): un usuario que cambia de plan a mitad de mes no queda mal liquidado. La suscripción propia gana a la del titular de su familia (RN-10). Sin plan vigente la corrida falla.
- Escribe Gold con `partitionOverwriteMode=dynamic`: solo se reemplaza la partición de esta liquidación; nunca se borran otras (ADR-0007).
- Sale con 0 solo si Gold se escribió y la liquidación quedó publicada en RDS o ya existía idéntica para el mismo `--run-id`.

**Qué no está probado:** el CLI completo de punta a punta (Silver real + RDS poblado + F1) no se ha corrido; están probadas por separado la liquidación con plan por fecha, las bolsas, la escritura append-only y la validación de argumentos. Tampoco existen aún la imagen Spark ni la tarea ECS.

## Imagen y tarea de ECS

- **Imagen:** `docker/spark.Dockerfile` (Python 3.12, Java 17, PySpark 4.0.1 como en el CI, y los jars de S3A `hadoop-aws-3.4.1` y `bundle-2.24.6` con su SHA-256 verificado en el build). Se publica en `sonoraplay/spark` con `infra/scripts/publicar-imagen.sh spark` y debe construirse en arm64 (CodeBuild), igual que las demás.
- **Tarea:** `infra/terraform/spark.tf` crea la definición `<proyecto>-<entorno>-spark` (Fargate ARM64, 4 vCPU y 16 GiB por defecto, raíz escribible: el primer intento con raíz de solo lectura falló al arrancar Spark) solo si se pasa `spark_imagen_tag`. No hay servicio: existe mientras corre un job. Los permisos (rol `spark`, SSM de RDS, security group hacia RDS y el `RunTask` de Airflow) ya estaban en `iam.tf` y `security_groups.tf`. La conexión a RDS llega por `DB_*` desde SSM; el CLI de Gold las convierte en la URL.
- **Lanzador:** `python -m sonoraplay.orquestacion.ecs_job -- <comando del job>` hace `RunTask` con ese comando, espera, y sale con 0 solo si el contenedor salió con 0 (si vence el plazo detiene la tarea). Es lo que debe contener `SILVER_JOB_COMMAND` y `LIQUIDACION_JOB_COMMAND`, con las rutas `s3a://` explícitas; requiere `ECS_CLUSTER`, `ECS_SPARK_FAMILY`, `ECS_SUBNETS` y `ECS_SECURITY_GROUPS` en Airflow.

**Qué no está probado:** la imagen no se ha construido ni ejecutado (en el entorno de desarrollo no hay Docker daemon); `terraform validate` solo corre en el CI (el registro de providers no es accesible aquí); ninguna tarea se ha lanzado en AWS. Riesgos a revisar en la primera corrida real: escritura en S3 con el committer por defecto de S3A (lento y no atómico: por eso Silver publica un marcador al final) y el consumo de memoria del driver con el volumen completo (EG-39). **Hallazgo de la primera ventana (2026-11-08):** con raíz de solo lectura y un volumen en `/tmp` la tarea murió con `No usable temporary directory found`; corregido dejando la raíz escribible.
