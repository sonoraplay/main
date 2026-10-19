# ADR-0001 · Arquitectura base en AWS: servicios 24/7 al menor costo justificable

| Campo | Valor |
|---|---|
| Estado | Aceptado · el horario de encendido lo modifica [ADR-0020](0020-ventanas-encendido-aws.md) |
| Fecha | 2026-09-30 |
| Historia que lo origina | HU 07 · EG-16 |
| Responsable | Joshua (lidera) · María Clara · Andrea |
| Revisó | Andrea — aprobado el 2026-10-02 |
| Referencias | E-01 v1, temas 5–10 y 16, RNF-01, RNF-04, CT-02 |

## 1. Contexto

SonoraPlay necesita una plataforma en AWS que reciba eventos sin perderlos, los procese con Spark, liquide el día 3 en menos de 1 hora y exponga una API a los sellos. Los servicios siempre activos lo están **mientras el entorno está prendido**; cuándo se prende lo decide [ADR-0020](0020-ventanas-encendido-aws.md). El enunciado pide el **menor costo justificable** y cubrir los 20 temas del programa.

Como referencia se revisó una arquitectura web genérica de AWS (ELB + EC2 con Auto Scaling + RDS + Memcache + DynamoDB + SES + S3).

## 2. Qué debe cumplir la decisión

- **Temas obligatorios:** VPC y EC2 (6), S3 y RDS (7), ECR y ECS (8), Fargate y ALB (9), RabbitMQ (10), Airflow con Celery (11–12), Spark en Fargate (16) y EKS (19).
- **RNF-04:** cero eventos perdidos.
- **RNF-01:** liquidación en menos de 1 hora.
- **RN-11 / CA-08:** cada sello ve solo lo suyo.
- **Costo:** mientras el entorno está prendido, los servicios siempre activos pagan todas las horas, así que el precio por hora pesa más que el precio por uso.
- **Penalizaciones:** credenciales expuestas (−15%) e infraestructura sin destruir (−10%).

## 3. Opciones consideradas

| Opción | A favor | En contra | USD/mes aprox. |
|---|---|---|---|
| A · Todo en una EC2 con docker compose | La más barata | No cubre los temas 7–9 ni la separación de capas; un punto único de falla | 30–40 |
| B · Stack "administrado" (NAT Gateway, Amazon MQ, MWAA, Fargate On-Demand para todo) | Menos mantenimiento | MWAA y Amazon MQ multiplican el costo por hora | > 450 |
| C · **Híbrido:** Fargate para servicios, EC2 pequeñas para RabbitMQ y Airflow, instancia NAT, Spot donde se tolera interrupción, ARM64 | Cubre todos los temas a bajo costo | Más mantenimiento en las EC2; la instancia NAT es un punto único de falla | ≈ 115–120 |

## 4. Decisión

**Elegimos la opción C**, detallada en [arquitectura-v1.md](../arquitectura/arquitectura-v1.md). Es la más barata que cumple todos los temas y los requisitos RNF-01 y RNF-04. De la arquitectura de referencia se mantienen el ALB, RDS con backups, S3 y las notificaciones (Budgets + SNS). Se reemplaza EC2 con Auto Scaling por ECS Fargate. Se descartan DynamoDB, Memcache y SES porque ninguna regla ni requisito los justifica.

## 5. Consecuencias

- **Positivas:** con todo prendido cuesta ≈ 115–120 USD al mes (≈ 27 USD por semana); con [ADR-0020](0020-ventanas-encendido-aws.md), el proyecto cuesta ≈ 30–40 USD sin EKS. Todos los temas tienen un lugar natural y solo el ALB es público.
- **Negativas:** el equipo mantiene dos EC2 (RabbitMQ y Airflow). RDS es Single-AZ.
- **Riesgos:** las interrupciones de Spot se mitigan con ACK manual y reintentos de Airflow. Si la NAT cae se cortan F6/F7, las descargas de ECR, los logs de CloudWatch y SSM; el tráfico a S3 sigue por el endpoint. Hay alarma con recuperación automática (arquitectura v1.1, sección 8). EKS se enciende solo durante su prueba en el Sprint 5 y en la demo (ADR-0020).
- **Decisiones que se derivan:** ADR-0009 a ADR-0019 del [registro](README.md) y [ADR-0020](0020-ventanas-encendido-aws.md) (horario de encendido).
- **Revisión 1.1 (2026-10-05):** sumó CloudTrail, ACM, Cloud Map, el Internet Gateway y los Security Groups, sin cambiar la opción, por ≈ 1 USD al mes.

## 6. Cómo sabremos que funciona

- `terraform apply` levanta todo y `terraform destroy` lo elimina sin residuos (HU 17 y 38).
- El costo real de la primera semana en AWS queda dentro de ±20% del estimado (HU 23).
- La API responde por la URL del ALB y sus logs aparecen en CloudWatch (HU 18).

## 7. Fuentes

- AWS Well-Architected Framework, pilar de optimización de costos: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html
- Precios de AWS Fargate (incluye Spot y ARM): https://aws.amazon.com/fargate/pricing/
- Precios de Amazon VPC (NAT Gateway, IPv4 públicas): https://aws.amazon.com/vpc/pricing/
- Precios de Amazon MQ: https://aws.amazon.com/amazon-mq/pricing/
- Precios de Amazon MWAA: https://aws.amazon.com/managed-workflows-for-apache-airflow/pricing/


---

## English — Decision summary

**Accepted (September 30, 2026; EG-16).** The team selected a cost-conscious hybrid AWS architecture to ingest playback events, run Spark settlement, protect each rights holder's reports, and meet the course's mandatory service coverage. Always-on services are active **only while the environment is provisioned and running**; ADR-0020 supersedes the original continuous-operation assumption with limited testing windows. This decision describes a design, not proof of deployed infrastructure.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
