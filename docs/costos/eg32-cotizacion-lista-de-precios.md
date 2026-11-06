---
title: "EG-32 · Cotización con la lista de precios oficial de AWS"
---

# EG-32 · Cotización de los dos escenarios con la lista de precios oficial de AWS

> **Estado (2026-11-06): hay estimaciones guardadas en la AWS Pricing Calculator, con enlaces públicos** (sección «Estimaciones guardadas en la calculadora»). La A (24/7) y la de EKS a 730 h coinciden con el cálculo de esta página (126,16 contra 126,21 y 86,86 contra 86,86). La B (ventanas) y la de EKS a 24 h **no coinciden**, porque la calculadora no permite expresar horas parciales de varios servicios; la diferencia está conciliada línea por línea más abajo. Los totales de esta página siguen siendo del cálculo con la lista de precios. Los enlaces los reportó quien creó las estimaciones y **no se han abierto desde el entorno de desarrollo** (`calculator.aws` está bloqueado): ábrelos en una ventana privada para confirmar que son públicos.

## Resultado

| Escenario | USD/mes | USD/año (mes redondeado × 12) | Cómo se calcula |
|---|---:|---:|---|
| **A · Infraestructura 24/7** | **126,21** | **1.514,52** | 730 h para todo lo que corre continuo |
| **B · Ventanas de prueba** | **5,61** | **67,32** | 8 ventanas × 3 h = 24 h; lo persistente se cobra todo el mes |
| **EKS (aparte, no suma en A ni B)** | 86,86 (730 h) · 2,86 (24 h) | 1.042,32 · 34,32 | Plano de control + 1 nodo `t4g.small` + 20 GB de disco |

Región `us-east-1`, USD, precios de lista **On-Demand sin descuentos, sin créditos y sin capa gratuita** (como la calculadora por defecto). Coinciden con las cifras que el equipo ya tenía en la hoja de la EG-32 (≈ 126 y ≈ 5,6 USD/mes).

## Primera estimación de la calculadora (2026-11-03): rechazada

La primera estimación guardada en la calculadora sumó **248,63 USD/mes (2.983,56 USD/año)** con seis servicios. **No es válida como evidencia** porque no reproduce el inventario del ticket ni coincide con ninguno de los dos escenarios:

| Servicio | Calculadora (USD/mes) | Esperado A (24/7) | Esperado B (ventanas) | Qué indica |
|---|---:|---:|---:|---|
| RDS PostgreSQL | **221,30** | 13,98 | 0,46 | Un `db.t4g.micro` Single-AZ cuesta ≈ 14 USD; 221 sugiere otra clase de instancia o Multi-AZ. Es el 89 % del total |
| CloudWatch | **9,13** | 1,16 | 0,09 | Tiene entradas de monitoreo móvil; el inventario es 1 alarma y 2 GB de logs |
| EC2 | 1,53 | 47,56 | 1,56 | Coincide con 24 h (B), no con 730 h (A) |
| Elastic Load Balancing | 16,66 | 22,27 | 0,73 | Parece 730 h; la calculadora deriva los LCU del tráfico que se le declara |
| AWS Fargate | **0,00** | 29,40 | 1,51 | Vacío: sin tareas u horas |
| S3 | **0,01** | 0,70 | 0,70 | Casi vacío: faltan 5 GB, PUT y GET |
| ECR, IPv4 públicas | no aparecen | 0,20 / 10,95 | 0,20 / 0,36 | Faltan |

Las seis filas suman exactamente 248,63 (× 12 = 2.983,56): la aritmética es correcta; las **entradas** no. Las estimaciones corregidas deben dar **126,21 USD/mes (1.514,52 USD/año)** en A y **5,61 USD/mes (67,32 USD/año)** en B, con EKS aparte. **Los totales corregidos de la calculadora siguen pendientes de que alguien rehaga las estimaciones y pegue los enlaces:** las cifras de esta página son del cálculo con la lista de precios, no de la calculadora.

## Estimaciones guardadas en la calculadora (2026-11-06)

Región US East (N. Virginia), USD, mismo inventario que el detalle por servicio.

| Estimación | Enlace | Calculadora (USD/mes) | Esta página (USD/mes) | Diferencia |
|---|---|---:|---:|---:|
| **A · 24/7** | [calculator.aws](https://calculator.aws/#/estimate?id=957680211e8208e9adcfc4c47024dbe9c30b58cd) | 126,16 | 126,21 | −0,05 |
| **B · ventanas (24 h)** | [calculator.aws](https://calculator.aws/#/estimate?id=121c0155b311cecc97744b85cd2adba4ddd3411e) | 40,96 | 5,61 | +35,35 |
| **EKS · 730 h** | [calculator.aws](https://calculator.aws/#/estimate?id=82cdd28958e2a58e7f0874d3389e43cf8c34d504) | 86,86 | 86,86 | 0,00 |
| **EKS · 24 h** | [calculator.aws](https://calculator.aws/#/estimate?id=85eba026a307dbb5ff35ba73f5e64f9246a9c0e1) | 73,45 | 2,86 | +70,59 |

**A (24/7): coincide.** La diferencia de 0,05 USD está en CloudWatch (1,11 contra 1,16): la calculadora no deja ingresar los GB de logs almacenados y deriva el almacenamiento de un supuesto de compresión. Los demás servicios coinciden al centavo con la tabla de arriba.

**B (ventanas) y EKS a 24 h: no coinciden, y no se ajustaron para que coincidan.** La calculadora no ofrece horas ni utilización para varios servicios, así que los cobra el mes completo. La conciliación de B:

| Concepto | Calculadora | Esta página (24 h) | Diferencia |
|---|---:|---:|---:|
| Elastic Load Balancing (ALB y LCU) | 22,27 | 0,73 | +21,54 |
| IPv4 públicas (3) | 10,95 | 0,36 | +10,59 |
| RDS (cómputo 24 h más almacenamiento) | 2,68 | 0,46 | +2,22 |
| CloudWatch (alarma, ingesta y almacenamiento) | 1,11 | 0,09 | +1,02 |
| Resto (EC2 y EBS, Fargate, Spark, S3, ECR) | 4,0 | 4,0 | ≈ 0 |
| **Total** | **40,96** | **5,61** | **+35,35** |

- El ALB y las IPv4 no tienen campo de horas.
- El almacenamiento de RDS (2,30 USD) se cobra el mes completo; la calculadora no lo prorratea, y 2,68 es exactamente 0,38 de cómputo más 2,30 de disco. Este desglose lo inferí de los montos, no lo leí en la calculadora.
- Los logs y la alarma de CloudWatch tampoco se prorratean.
- Las sumas cierran con ≈ 0,02 USD de redondeo.
- En EKS a 24 h el plano de control (73,00 USD) se cobra el mes completo: la calculadora solo acepta un número entero de clústeres y rechazó 0,0329 clústeres. Con eso, 73,45 − (73,00 − 2,40) = 2,86.

**Qué significa para el criterio 1.** Hay enlaces públicos de las dos estimaciones y de EKS. La de ventanas, tal como la calcula la calculadora, **sobreestima** el costo de unas ventanas de 24 h porque cobra ALB, IPv4, disco de RDS, logs y el clúster de EKS el mes completo. El valor de 5,61 USD/mes sale de la lista de precios con horas reales y es el que debe usarse para comparar contra Cost Explorer; el de 40,96 sirve solo como cota superior de «todo el mes encendido salvo lo que sí permite horas».

## Detalle por servicio

| Servicio | Supuesto (24/7) | A · 24/7 (USD/mes) | B · ventanas (USD/mes) |
|---|---|---:|---:|
| EC2 NAT | t4g.micro × 730 h | 6.13 | 0.20 |
| EC2 RabbitMQ | t4g.small × 730 h | 12.26 | 0.40 |
| EC2 Airflow | t4g.medium × 730 h | 24.53 | 0.81 |
| EBS gp3 | 58 GB × 730/730 mes | 4.64 | 0.15 |
| RDS PostgreSQL db.t4g.micro | Single-AZ × 730 h | 11.68 | 0.38 |
| RDS almacenamiento gp3 | 20 GB × 730/730 mes | 2.30 | 0.08 |
| ALB | 1 ALB × 730 h | 16.42 | 0.54 |
| ALB LCU | 1 LCU × 730 h | 5.84 | 0.19 |
| ECS Fargate ARM | 4 tareas de 0.25 vCPU / 0.5 GB × 730 h | 28.84 | 0.95 |
| IPv4 públicas | 3 × 730 h | 10.95 | 0.36 |
| Spark (Fargate ARM, precio On-Demand) | 2 vCPU / 8 GB × 6 h | 0.56 | 0.56 |
| S3 almacenamiento | 5 GB | 0.12 | 0.12 |
| S3 solicitudes PUT | 100,000 solicitudes | 0.50 | 0.50 |
| S3 solicitudes GET | 200,000 solicitudes | 0.08 | 0.08 |
| ECR | 2 GB | 0.20 | 0.20 |
| CloudWatch alarma | 1 × 730/730 mes | 0.10 | 0.00 |
| CloudWatch ingesta de logs | 2 GB × 730/730 | 1.00 | 0.03 |
| CloudWatch almacenamiento de logs | 2 GB (persistente) | 0.06 | 0.06 |
| **Total sin EKS** | | **126.21** | **5.61** |

| EKS (aparte) | Supuesto (24/7) | 730 h (USD) | 24 h (USD) |
|---|---|---:|---:|
| EKS plano de control | 1 clúster × 730 h | 73.00 | 2.40 |
| EC2 nodo | t4g.small × 730 h | 12.26 | 0.40 |
| EBS gp3 del nodo | 20 GB × 730/730 mes | 1.60 | 0.05 |
| **Total EKS** | | **86.86** | **2.86** |


## Precios unitarios usados (todos de la lista oficial, us-east-1)

| Concepto | Precio | Archivo de la lista (versión) |
|---|---|---|
| EC2 `t4g.micro` / `t4g.small` / `t4g.medium` Linux | 0,0084 / 0,0168 / 0,0336 USD por hora | `AmazonEC2` (2026-10-29) |
| EBS gp3 | 0,08 USD por GB-mes | `AmazonEC2` (2026-10-29) |
| RDS PostgreSQL `db.t4g.micro` Single-AZ | 0,016 USD por hora | `AmazonRDS` (2026-10-29) |
| RDS almacenamiento gp3 (PostgreSQL) | 0,115 USD por GB-mes | `AmazonRDS` (2026-10-29) |
| ALB / LCU | 0,0225 USD por hora / 0,008 USD por LCU-hora | `AWSELB` (2026-11-02) |
| Fargate ARM | 0,03238 USD por vCPU-hora; 0,00356 USD por GB-hora | `AmazonECS` (2026-10-19) |
| IPv4 pública en uso | 0,005 USD por hora | `AmazonVPC` (2026-11-03) |
| S3 Standard | 0,023 USD por GB-mes (primeros 50 TB); PUT 0,005 USD por 1 000; GET 0,004 USD por 10 000 | `AmazonS3` (2026-10-15) |
| ECR | 0,10 USD por GB-mes | `AmazonECR` (2026-09-11) |
| CloudWatch | alarma estándar 0,10 USD por mes; ingesta de logs 0,50 USD por GB; almacenamiento de logs 0,03 USD por GB-mes | `AmazonCloudWatch` (2026-10-07) |
| EKS plano de control (soporte estándar) | 0,10 USD por clúster-hora | `AmazonEKS` (2026-10-27) |

## Supuestos (cámbialos en `Inventario`, en `src/sonoraplay/costos.py`)

1. **Se cobra por hora, solo mientras corre:** EC2, RDS, ALB, Fargate e IPv4. En B se multiplican por 24 h.
2. **Lo que desaparece con `terraform destroy` se prorratea por hora** (`horas / 730`): EBS, almacenamiento de RDS y la alarma. **Persistente en ambos escenarios:** S3 (5 GB, 100 000 PUT, 200 000 GET), ECR (2 GB) y el almacenamiento de logs.
3. **IPv4 públicas:** 3 (1 de la NAT y 2 del ALB, una por zona). RabbitMQ, Airflow y RDS son privadas.
4. **Fargate:** 4 tareas de 0,25 vCPU / 0,5 GB ARM, On-Demand. Los 20 GB de almacenamiento efímero por tarea están incluidos.
5. **Spark:** 2 vCPU / 8 GB, 6 h al mes, **cotizado al precio On-Demand**: la lista oficial no publica el precio de Fargate Spot, que varía a lo largo del día. Es un techo.
6. **Logs:** la ingesta (2 GB/mes en A) se escala con las horas encendidas en B, porque solo hay logs si algo corre. Si se prefieren 2 GB también en B, suma 0,97 USD al escenario B.
7. **Transferencia de datos: 0 USD.** Se asume menos de 100 GB/mes hacia internet (dentro de los primeros 100 GB gratuitos de AWS) y tráfico entre zonas despreciable. Una instancia NAT no cobra por GB procesado (a diferencia de un NAT Gateway). **Es un supuesto, no una medición:** debe revisarse con el tráfico real.
8. **RDS:** 20 GB gp3 de línea base y copias de 1 día dentro de lo incluido (ADR-0022).

## No cotizado (sin precio verificado en esta hoja)

AWS Budgets y SNS (persistentes, costo mínimo; SNS da gratis los primeros 1 000 correos), SSM Parameter Store estándar, KMS (la clave de EKS), CloudTrail y Fargate **Spot** (ver supuesto 5). Ningún total de arriba los incluye.

## Cómo crear las dos estimaciones en la calculadora (y comprobar)

1. Entra a [calculator.aws](https://calculator.aws/#/) → **Create estimate**. Región **US East (N. Virginia)**, USD.
2. Agrega, con **el mismo inventario en las dos estimaciones**:
   - **Amazon EC2** × 3 (Linux, On-Demand): `t4g.micro` con 8 GB gp3 (NAT), `t4g.small` con 20 GB gp3 (RabbitMQ), `t4g.medium` con 30 GB gp3 (Airflow).
   - **Amazon RDS for PostgreSQL**: `db.t4g.micro`, Single-AZ, On-Demand, 20 GB gp3.
   - **Application Load Balancer**: 1 ALB y 1 LCU.
   - **AWS Fargate**: 4 tareas, Linux **ARM**, 0,25 vCPU / 0,5 GB; y una tarea de 2 vCPU / 8 GB para Spark durante 6 h al mes.
   - **Amazon S3**: 5 GB Standard, 100 000 PUT, 200 000 GET. **Amazon ECR**: 2 GB.
   - **Amazon CloudWatch**: 1 alarma estándar, 2 GB de logs ingeridos y almacenados.
   - **Public IPv4**: 3 direcciones.
3. **Estimación A:** 730 h/mes (la calculadora usa 100 % de uso). **Estimación B:** utilización del servicio en **24 h al mes** (≈ 3,29 %); deja S3, ECR y el almacenamiento de logs sin reducir.
4. Cada estimación: **Save and share** → copia el enlace público y pégalo en la tabla de `docs/costos/eg32-aws-cost-analysis-v1-en-es.md`.
5. **EKS:** otra estimación **aparte**: EKS (1 clúster) + 1 `t4g.small` + 20 GB gp3, 24 h y 730 h.
6. Compara con esta página: los totales deberían coincidir con **126,21** y **5,61** USD (EKS: **86,86** y **2,86** USD). Una diferencia de más de unos centavos indica una opción distinta en la calculadora (por ejemplo, otro tipo de almacenamiento o tenencia): revísala.

## Cómo repetir el cálculo

```bash
# 1. Descarga las listas (versión de la región us-east-1 de cada oferta) en una carpeta:
#    https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<Oferta>/current/region_index.json
#    Ofertas: AmazonEC2, AmazonRDS, AWSELB, AmazonECS, AmazonS3, AmazonECR, AmazonCloudWatch, AmazonVPC, AmazonEKS
# 2. Calcula (falla si algún precio no es único, no lo adivina):
uv run python -m sonoraplay.costos --precios <carpeta>
```
`tests/test_costos.py` verifica las cuentas a mano con precios fijos.
