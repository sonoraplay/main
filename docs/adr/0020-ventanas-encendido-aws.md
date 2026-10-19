# ADR-0020 · Entorno AWS apagado por defecto: ventanas de prueba en S3–S5 y encendido continuo solo en la última semana

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-09 |
| Historia que lo origina | HU 07 · EG-16 (corrección de la arquitectura v1) |
| Responsable | María Clara (propone) · Joshua · Andrea |
| Revisó | Andrea — aprobado en el PR #14 (fusionado el 2026-10-09) |
| Referencias | [ADR-0001](0001-arquitectura-base-aws.md), [arquitectura v1.2](../arquitectura/arquitectura-v1.md), HU 17 (EG-26), HU 23 (EG-32), HU 32 (EG-41), HU 38, penalización de −10 % por no destruir la infraestructura |

## 1. Contexto

[ADR-0001](0001-arquitectura-base-aws.md) eligió la opción C (híbrida), pero la describió **encendida durante todo el proyecto**. Eso contradice la estrategia que acordó el equipo: la infraestructura se crea y se destruye con Terraform, se prende solo en ventanas cortas de prueba y queda prendida de forma continua únicamente en la última semana, hasta la demo.

Con todo prendido, la opción C cuesta ≈ 115–120 USD al mes. Dejarla prendida las 6 semanas del proyecto costaría ≈ 165–170 USD sin EKS, y la mayor parte de ese dinero pagaría horas en las que nadie usa la plataforma.

Esta decisión **no cambia los servicios** de ADR-0001 ni de la arquitectura v1: solo decide cuándo están encendidos.

## 2. Qué debe cumplir la decisión

- **Costo:** el menor costo justificable que pide el enunciado.
- **Requisito:** HU 17 / HU 38, `terraform apply` y `terraform destroy` reproducibles y sin residuos.
- **Requisito:** HU 23, el costo real queda dentro de ±20 % del estimado.
- **Penalización:** −10 % si la infraestructura no se destruye después de la demo.
- **Negocio:** la liquidación del día 3 (RF-04, RNF-01) debe poder demostrarse.
- **Datos:** perder RDS entre ventanas no puede perder información que no se pueda regenerar.

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. USD (todo el proyecto) |
|---|---|---|---|
| A · Prendido 24/7 las 6 semanas | Nada que recrear; RDS conserva sus datos y backups | Paga semanas sin uso; un olvido de `destroy` al final cuesta lo mismo que hoy | ≈ 165–170 + EKS |
| B · **Apagado por defecto**, con ventanas cortas en S3–S5 y encendido continuo solo en S6 | Paga solo las horas de prueba y la semana de la demo; cada ventana ensaya `apply` y `destroy` | Hay que re-sembrar RDS en cada ventana; el día 3 se demuestra con una fecha lógica | ≈ 30–40 + EKS |
| C · Prendido solo el día de la demo | El más barato | No deja tiempo para corregir fallas que aparecen en AWS; la HU 23 no tendría una semana real que medir | ≈ 5–10 + EKS |

## 4. Decisión

**Elegimos la opción B.** Es la más barata que permite probar `apply` / `destroy` antes de la demo (HU 17, HU 38), medir una semana real de costo (HU 23) y demostrar la liquidación del día 3 (RF-04).

1. Por defecto el entorno está **destruido**. Entre ventanas solo quedan recursos de costo casi nulo: el bucket del estado de Terraform, ECR, SSM Parameter Store, Budgets y el bucket de CloudTrail.
2. Cada ventana de prueba es `terraform apply` → prueba → `terraform destroy` **el mismo día**.
3. En el Sprint 6 el entorno queda prendido hasta la demo y luego se destruye, con evidencia.
4. EKS se prende solo durante su prueba en el Sprint 5 y en la demo ([ADR-0018](README.md)).
5. RDS se recrea en cada ventana y se carga con el seed reproducible (EG-13 / EG-28). S3 puede conservarse porque cuesta centavos.
6. El DAG del día 3 se dispara a mano con `airflow dags trigger --logical-date`.
7. En la arquitectura, **"24/7"** pasa a significar "activo mientras el entorno está prendido".

## 5. Consecuencias

- **Positivas:**
  - El costo del proyecto baja a ≈ 30–40 USD sin EKS.
  - Cada ventana ensaya `apply` y `destroy`, así que la destrucción final (y la penalización de −10 %) deja de ser un paso que se hace por primera vez el día de la demo.
- **Negativas / lo que aceptamos:**
  - Hay que re-sembrar RDS en cada ventana.
  - El día 3 se demuestra con una fecha lógica, no esperando al día 3 real del mes.
  - Los backups automáticos de RDS solo duran lo que dura la ventana.
- **Riesgos y mitigación:**
  - *Olvidar un `destroy`* → AWS Budgets con aviso por SNS.
  - *Recursos creados a mano fuera de Terraform* que `destroy` no borra → regla del equipo: nada fuera de Terraform.
  - *Fallas que solo aparecen en AWS y se descubren tarde* → para eso están las ventanas de S3–S5.

## 6. Cómo sabremos que funciona

- Cada ventana deja evidencia de `terraform apply` y `terraform destroy`.
- El costo real de la última semana queda dentro de ±20 % del estimado en Cost Explorer (HU 23).
- Fuera de las ventanas, el costo diario en Cost Explorer es ≈ 0 USD.

## 7. Fuentes

- AWS Well-Architected Framework, pilar de optimización de costos: https://docs.aws.amazon.com/wellarchitected/latest/cost-optimization-pillar/welcome.html
- Terraform, comando `destroy`: https://developer.hashicorp.com/terraform/cli/commands/destroy
- Apache Airflow, CLI `dags trigger`: https://airflow.apache.org/docs/apache-airflow/stable/cli-and-env-variables-ref.html#trigger
- [ADR-0001](0001-arquitectura-base-aws.md) y la [arquitectura v1](../arquitectura/arquitectura-v1.md).


---

## English — Decision summary

**Accepted (October 9, 2026; EG-16).** The AWS environment is **off by default**. Terraform provisions it for short test windows during Sprints 3–5, with continuous operation planned only for the final demonstration week, followed by destruction. This changes the operating schedule in ADR-0001 without changing the selected services. Figures in this ADR are planning estimates, **not observed AWS charges**. Verify actual provisioned resources, billing, and teardown separately.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
