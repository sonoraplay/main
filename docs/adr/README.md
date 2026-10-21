# Registro de decisiones de arquitectura (ADR)

> Tarea **07 (EG-16)**. Criterio de aceptación: *"diagrama publicado y cada ADR pendiente asignado a su historia"*.
> Regla del equipo (Definition of Done): **el ADR se escribe dentro de la misma historia que lo origina**, no al final.
> Para crear uno nuevo, copia [0000-plantilla.md](0000-plantilla.md).

**Estados:** 🟡 Propuesto · 🟢 Aceptado · ⚪ Pendiente (se escribe en su historia) · 🔴 Rechazado / Reemplazado

| ADR | Decisión a tomar | Historia | Jira | Sprint | Responsable | Referencias | Estado |
|---|---|---|---|---|---|---|---|
| [0001](0001-arquitectura-base-aws.md) | Arquitectura base en AWS al menor costo justificable (horario de encendido en ADR-0020) | 07 | EG-16 | S1 | Joshua (los tres) | E-01 v1 | 🟢 |
| [0002](0002-zona-horaria-dia-mes.md) | Zona horaria que define el "día" y el "mes": **UTC** (aceptado 2026-10-02; se revisa si el docente responde distinto) | 02 | EG-11 | S1 | María Clara | RN-02, RN-04 | 🟢 |
| [0003](0003-duplicados-f1.md) | Pistas duplicadas en F1: una fila por `track_id` con género principal y tabla puente de géneros | 03 | EG-12 | S1 | María Clara | F1, RN-03, Q9 | 🟢 |
| [0004](0004-esquema-eventos-f2.md) | Esquema JSON de eventos F2 y deduplicación por `event_id` | 06 | EG-15 | S1 | Andrea | F2, RNF-04 | 🟢 |
| [0005](0005-umbrales-granjas.md) | Umbrales de las 3 señales de granja y periodo de exclusión | 09 | EG-18 | S1 | María Clara | RN-03, CA-03, CA-10 | 🟢 |
| [0006](0006-autenticacion-aislamiento-sellos.md) | Autenticación de sellos con JWT HS256 y aislamiento entre titulares (403 antes de leer la base) | 12 | EG-21 | S2 | Andrea | RN-11, CA-08, RF-05 | 🟢 |
| [0007](0007-cierre-mes-ajustes-reliquidacion.md) | Cierre de mes append-only, ajustes en la liquidación siguiente y redondeo por mayor residuo | 14 | EG-23 | S2 | Andrea y María Clara | RF-09, CA-07, RNF-02 | 🟢 |
| [0008](0008-pais-bolsa-dos-componentes.md) | País que define la bolsa (facturación) y bolsa de dos componentes con denominadores separados | 14 | EG-23 | S2 | Andrea y María Clara | RN-05, RN-06, RN-10, Q6, Q8 | 🟢 |
| [0009](0009-region-aws.md) | Región AWS: us-east-1 (frente a sa-east-1 y us-east-2) | 17 | EG-26 | S3 | Andrea | Tema 5, costos, HU 23 |🟢 |
| [0010](0010-instancia-nat.md) | Salida a internet: instancia NAT t4g.nano frente a NAT Gateway | 17 | EG-26 | S3 | Andrea | Tema 6, costos |🟢 |
| [0011](0011-terraform.md) | Infraestructura como código con Terraform, estado en S3 con bloqueo nativo (frente a scripts CLI y CloudFormation) | 17 | EG-26 | S3 | Andrea | E-06, E-12 |🟢 |
| 0012 | Cómputo de servicios y jobs: Fargate On-Demand, Fargate Spot y ARM64 | 18 | EG-27 | S3 | Andrea | Temas 8–9 y 16 | ⚪ |
| [0013](0013-rabbitmq-ec2-frente-amazon-mq.md) | RabbitMQ en EC2 `t4g.small` (1 nodo, colas classic durables) frente a Amazon MQ | 20 | EG-29 | S3 | Andrea | RNF-04, tema 10 |🟢 |
| 0014 | Formato y particionamiento del Data Lake (Parquet por año/mes/país) | 22 | EG-31 | S3 | María Clara | RNF-03, tema 15 | ⚪ |
| 0015 | Airflow en EC2 con CeleryExecutor frente a MWAA | 25 | EG-34 | S4 | Joshua | Temas 11–12 | ⚪ |
| 0016 | Manejo del skew en Spark (salting, broadcast join) | 30 | EG-39 | S5 | Joshua | RNF-01, E-13 | ⚪ |
| 0017 | CI/CD con OIDC y gestión de secretos en SSM Parameter Store | 31 | EG-40 | S5 | Andrea | CT-02, E-09 | ⚪ |
| 0018 | ECS frente a EKS, y EKS encendido solo durante su prueba en S5 y la demo | 32 | EG-41 | S5 | Joshua | Tema 19 | ⚪ |
| 0019 | Acceso de Power BI a RDS mediante túnel SSM | 35 | EG-44 | S6 | María Clara | RF-08, E-11 | ⚪ |
| [0022](0022-excepcion-plan-gratuito-rds-nat.md) | Excepción del plan gratuito: backups de RDS de 1 día y NAT t4g.micro hasta la última semana | 17 | EG-26 | S3 | Julián (aprobó el 2026-10-20) | Criterio 5 de la EG-26, ADR-0010, ADR-0020 | 🟢 |
| [0020](0020-ventanas-encendido-aws.md) | Entorno AWS apagado por defecto: ventanas de prueba en S3–S5 y encendido continuo solo en la última semana | 07 | EG-16 | S1 | María Clara (los tres) | ADR-0001, HU 17, 23, 38 | 🟢 |

## Resumen por historia

- **Sprint 1:** HU 02, 03, 06, 07 y 09 (6 ADR: 0001–0005 y 0020).
- **Sprint 2:** HU 12 y 14 (3 ADR).
- **Sprint 3:** HU 17, 18, 20 y 22 (6 ADR).
- **Sprint 4:** HU 25 (1 ADR).
- **Sprint 5:** HU 30, 31 y 32 (3 ADR).
- **Sprint 6:** HU 35 (1 ADR).
- Al cierre, la **HU 40 (EG-49)** reúne todos los ADR en el documento de arquitectura final.

## Supuestos de negocio que alimentan ADR pendientes (EG-11)

Las respuestas de [ambiguedades-rn.md](../analisis/ambiguedades-rn.md) (preguntas enviadas al docente el 2026-09-30) fijan supuestos que estos ADR deben recoger:

- **ADR-0003:** una fila canónica por `track_id` (Q9).
- **ADR-0005:** oyentes del artista medidos por mes (Q2); exclusión de la cuenta sospechosa por todo el mes de liquidación (Q3).
- **ADR-0007:** las reproducciones liberadas tras revisión se pagan como ajuste (Q3).
- **ADR-0008:** la bolsa la define el país de facturación (Q6) y la bolsa se divide en componente de suscripción (planes pagos) y de publicidad (plan gratuito) (Q8).

## Cómo mantener el registro

1. Al empezar una historia de la tabla, crea el archivo `NNNN-titulo.md` desde la plantilla y cambia su estado a 🟡.
2. Cuando otra persona del equipo lo revise en el PR, cambia el estado a 🟢.
3. Si una decisión cambia, no se borra: el ADR viejo pasa a 🔴 *Reemplazado por ADR-NNNN* y se escribe uno nuevo.
4. Si aparece una decisión nueva, se agrega al final de la tabla con su historia.
