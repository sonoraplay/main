---
sidebar_position: 2
title: "EG-28 · Seed en RDS / Seed on RDS"
---

# EG-28 · Correr el seed contra RDS / Run the seed against RDS

## Español

**Estado: preparado, NO ejecutado.** Esta página es el procedimiento para la HU 19 (EG-28). Se ejecuta **solo si** la infraestructura está arriba en una ventana de prueba ([ADR-0020](../adr/0020-ventanas-encendido-aws.md)) **y** el costo está autorizado (EG-32). No hay evidencia de AWS en esta página todavía.

### Criterios de Jira

1. `DATABASE_URL` se lee de SSM Parameter Store y el seed corre contra RDS **sin cambios de código**.
2. Con el mismo modo (`dev`), el número de filas de cada tabla en RDS coincide con la corrida local.
3. Una segunda corrida contra RDS no cambia ningún conteo (idempotencia).
4. La conexión sale desde dentro de la VPC y RDS sigue sin ser pública.

### Qué hace el seed

El seed son tres pasos en orden, los mismos de `docker/seed.sh`: catálogo F1 → seed F3 de suscripciones (modo `dev`: 10.000 usuarios) → seed F4 de contratos. Usa IDs `uuid5` y `ON CONFLICT DO NOTHING`, así que repetirlo no duplica filas. El esquema lo crean los archivos de `db/ddl/`: en local los aplica el contenedor de PostgreSQL al arrancar, pero **RDS no los aplica sola**, hay que cargarlos a mano.

### Cómo llegar a RDS

RDS no tiene IP pública. Opciones, de mejor a peor para esta ventana:

| Opción | Estado | Nota |
|---|---|---|
| **A · CloudShell dentro de la VPC** (subred privada y Security Group `airflow`) | Disponible | Ya se usó el 15 oct. El entorno no deja subir archivos (se clona de GitHub) y su interfaz de red **impide el `destroy`**: hay que borrarlo antes |
| B · Tarea de ECS de una sola ejecución | No existe | Necesita la imagen en ECR y una definición de tarea (historia aparte) |
| C · Túnel SSM por la EC2 de Airflow | No existe | La EC2 de Airflow llega con la EG-34 |

Se recomienda la **opción A**.

### Costo

Con tarifas de lista, la infraestructura base de esta ventana (NAT y RDS) cuesta unos **0,10 USD por cada 3 horas encendida** (la hoja de EG-32 detalla el cálculo y sus supuestos). Es una estimación, no una factura. El presupuesto máximo sigue pendiente de acordarse (EG-32).

### Procedimiento (opción A)

**0 · Antes.** La infraestructura está creada (`apply`) y RDS en estado `available`. En CloudShell: **Actions → Create VPC environment**, VPC `sonoraplay-dev`, una subred **privada** y el Security Group **`airflow`**. Todo lo siguiente se corre en esa terminal.

**1 · Herramientas.**
```bash
sudo dnf install -y postgresql16 git
python3 -m pip install --user uv
export PATH="$HOME/.local/bin:$PATH"
git clone --depth 1 --branch develop --single-branch https://github.com/sonoraplay/main.git /tmp/sonoraplay
cd /tmp/sonoraplay && uv sync --frozen --no-dev       # el proyecto pide Python 3.12; uv lo descarga
mkdir -p /tmp/evidencia /tmp/procesados
```

**2 · `DATABASE_URL` desde SSM (criterio 1).** La contraseña tiene caracteres especiales (`!#$%^&*()`), por eso se codifica. No se imprime en pantalla.
```bash
export DATABASE_URL=$(python3 - <<'PY'
import subprocess, urllib.parse as u
def ssm(n):
    return subprocess.check_output(["aws", "ssm", "get-parameter", "--name", f"/sonoraplay/rds/{n}",
        "--with-decryption", "--query", "Parameter.Value", "--output", "text"], text=True).strip()
q = lambda s: u.quote(s, safe="")
print(f"postgresql+psycopg://{q(ssm('username'))}:{q(ssm('password'))}@{ssm('host')}:{ssm('port')}/{ssm('dbname')}?sslmode=require")
PY
)
test -n "$DATABASE_URL" && echo "DATABASE_URL lista"
```

**3 · Esquema.** Aplica los tres DDL (están escritos para poder repetirse: `IF NOT EXISTS`, `CREATE OR REPLACE` y `DROP ... IF EXISTS`):
```bash
PSQL_URL="${DATABASE_URL/postgresql+psycopg/postgresql}"
for f in db/ddl/001_f3_suscripciones.sql db/ddl/002_f4_contratos.sql db/ddl/003_reportes_regalias.sql; do
  psql "$PSQL_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

**4 · Seed (criterio 1: sin cambios de código).** Los tres pasos de `docker/seed.sh`, con la muestra versionada del catálogo:
```bash
export SEED=42
uv run python -m sonoraplay.catalogo --entrada data/samples/f1_muestra.csv --salida /tmp/procesados --titulares 50
uv run python -m sonoraplay.seed --modo dev 2>&1 | tee /tmp/evidencia/seed1.txt
uv run python -m sonoraplay.seed.f4_contratos --datos-f1 /tmp/procesados
```

**5 · Conteos (criterio 2).**
```bash
cat > /tmp/conteos.sql <<'SQL'
SELECT 'planes' AS tabla, count(*) FROM planes UNION ALL
SELECT 'usuarios', count(*) FROM usuarios UNION ALL
SELECT 'grupos_familiares', count(*) FROM grupos_familiares UNION ALL
SELECT 'miembros_familia', count(*) FROM miembros_familia UNION ALL
SELECT 'suscripciones', count(*) FROM suscripciones UNION ALL
SELECT 'pagos', count(*) FROM pagos UNION ALL
SELECT 'seed_defectos', count(*) FROM seed_defectos UNION ALL
SELECT 'titulares_derechos', count(*) FROM titulares_derechos UNION ALL
SELECT 'contratos', count(*) FROM contratos UNION ALL
SELECT 'exclusiones_territoriales', count(*) FROM exclusiones_territoriales UNION ALL
SELECT 'liquidaciones', count(*) FROM liquidaciones UNION ALL
SELECT 'reporte_regalias', count(*) FROM reporte_regalias ORDER BY 1;
SQL
psql "$PSQL_URL" -f /tmp/conteos.sql | tee /tmp/evidencia/conteos1.txt
```
Referencia local: haz el mismo conteo en tu PC después de `docker compose up -d` con `docker compose exec postgres psql -U sonora -d sonoraplay -f -` y compara tabla por tabla. En la corrida del 15 oct contra RDS salieron 10.000 usuarios, 8.712 suscripciones, 69.227 pagos, 50 titulares y 208 contratos. `liquidaciones` y `reporte_regalias` deben estar en 0: las publica el esqueleto, no el seed.

**6 · Idempotencia (criterio 3).** Repite el paso 4 y el 5 (guarda `conteos2.txt`) y compara:
```bash
diff /tmp/evidencia/conteos1.txt /tmp/evidencia/conteos2.txt && echo "IDEMPOTENTE: sin diferencias"
```

**7 · Que RDS sigue privada (criterio 4).**
```bash
aws rds describe-db-instances --db-instance-identifier sonoraplay-dev --query 'DBInstances[0].PubliclyAccessible'
```
Debe devolver `false`.

**8 · Cierre.** **Borra el entorno de CloudShell de la VPC** antes del `destroy`. Después destruye la infraestructura y comprueba que no quedan huérfanos, como en [la evidencia de EG-26](./eg26-evidencia-aws.md).

### Riesgos conocidos

- **Contraseña con caracteres especiales:** si se arma la URL sin codificarla, la conexión falla con un error de autenticación. El paso 2 la codifica.
- **Python 3.12:** CloudShell trae una versión anterior. `uv` descarga la correcta, pero necesita salida a internet por la NAT.
- **Sin conteos de referencia completos:** solo hay cinco cifras documentadas de la corrida local. Para cerrar el criterio 2 hay que sacar el conteo de las 12 tablas en local.
- **Si falla a la mitad:** el seed corta en el primer error y se puede repetir sin duplicar. Si el fallo fue de conexión, repite desde el paso 4.

### Qué falta para ejecutarlo

1. Presupuesto máximo acordado (EG-32).
2. Una ventana de AWS (`apply`).
3. Alguien con permisos de administrador en CloudShell.

## English

**Status: prepared, NOT executed.** This page is the procedure for story 19 (EG-28). Run it **only if** the infrastructure is up in a test window ([ADR-0020](../adr/0020-ventanas-encendido-aws.md)) **and** the cost is authorized (EG-32). There is no AWS evidence on this page yet.

### Jira criteria

1. `DATABASE_URL` is read from SSM Parameter Store and the seed runs against RDS with **no code changes**.
2. In the same mode (`dev`), every table's row count in RDS matches the local run.
3. A second run against RDS changes no count (idempotency).
4. The connection is made from inside the VPC and RDS stays non-public.

### What the seed does

The seed is three steps in order, the same as `docker/seed.sh`: F1 catalog → F3 subscriptions seed (`dev` mode: 10,000 users) → F4 contracts seed. It uses `uuid5` IDs and `ON CONFLICT DO NOTHING`, so repeating it does not duplicate rows. The schema comes from the files in `db/ddl/`: locally the PostgreSQL container applies them on start, but **RDS does not apply them by itself**; they must be loaded by hand.

### How to reach RDS

RDS has no public IP. Options, best to worst for this window:

| Option | Status | Note |
|---|---|---|
| **A · CloudShell inside the VPC** (private subnet and `airflow` Security Group) | Available | Used on Oct 15. The environment cannot upload files (clone from GitHub) and its network interface **blocks the `destroy`**: delete it first |
| B · One-off ECS task | Does not exist | Needs the image in ECR and a task definition (separate story) |
| C · SSM tunnel through the Airflow EC2 | Does not exist | The Airflow EC2 arrives with EG-34 |

**Option A** is recommended.

### Cost

At list prices, the base infrastructure of this window (NAT and RDS) costs about **USD 0.10 per 3 hours on** (the EG-32 worksheet explains the calculation and its assumptions). It is an estimate, not an invoice. The maximum budget is still to be agreed (EG-32).

### Procedure (option A)

**0 · Before.** The infrastructure is created (`apply`) and RDS is `available`. In CloudShell: **Actions → Create VPC environment**, VPC `sonoraplay-dev`, one **private** subnet and the **`airflow`** Security Group. Everything below runs in that terminal.

**1 · Tools.** Install `postgresql16` and `git`, install `uv` with `pip install --user uv`, clone `sonoraplay/main` with `--branch develop`, and run `uv sync --frozen --no-dev` (the project needs Python 3.12; `uv` downloads it). Create `/tmp/evidencia` and `/tmp/procesados`. The commands are in the Spanish section above.

**2 · `DATABASE_URL` from SSM (criterion 1).** The password has special characters (`!#$%^&*()`), so it is URL-encoded. It is never printed. Use the Python snippet in the Spanish section above.

**3 · Schema.** Apply the three DDL files with `psql` (they are written to be repeatable: `IF NOT EXISTS`, `CREATE OR REPLACE` and `DROP ... IF EXISTS`).

**4 · Seed (criterion 1: no code changes).** Run the three steps of `docker/seed.sh` with the versioned catalog sample: `sonoraplay.catalogo`, `sonoraplay.seed --modo dev` and `sonoraplay.seed.f4_contratos`, with `SEED=42`.

**5 · Counts (criterion 2).** Run the count query over the 12 tables (in the Spanish section above) and save it as `conteos1.txt`. For the local reference, run the same count on your PC after `docker compose up -d` and compare table by table. In the Oct 15 run against RDS the results were 10,000 users, 8,712 subscriptions, 69,227 payments, 50 rights holders and 208 contracts. `liquidaciones` and `reporte_regalias` must be 0: the skeleton publishes them, not the seed.

**6 · Idempotency (criterion 3).** Repeat steps 4 and 5, save `conteos2.txt`, and run `diff` between the two files. It must show no differences.

**7 · RDS stays private (criterion 4).** `aws rds describe-db-instances --db-instance-identifier sonoraplay-dev --query 'DBInstances[0].PubliclyAccessible'` must return `false`.

**8 · Wrap-up.** **Delete the VPC CloudShell environment** before the `destroy`. Then destroy the infrastructure and check for orphans, as in [the EG-26 evidence](./eg26-evidencia-aws.md).

### Known risks

- **Password with special characters:** building the URL without encoding it fails with an authentication error. Step 2 encodes it.
- **Python 3.12:** CloudShell ships an older version. `uv` downloads the right one but needs internet access through the NAT.
- **No complete reference counts:** only five figures from the local run are documented. To close criterion 2, take the count of all 12 tables locally.
- **If it fails midway:** the seed stops at the first error and can be repeated without duplicating. If it was a connection failure, repeat from step 4.

### What is needed to run it

1. The maximum budget agreed (EG-32).
2. An AWS window (`apply`).
3. Someone with administrator permissions in CloudShell.
