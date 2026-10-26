# ADR-0009 · Región de AWS: us-east-1 (Norte de Virginia)

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-14 |
| Historia que lo origina | HU 17 · EG-26 |
| Responsable | Andrea Zárate |
| Revisó | Julián: aprobó el [PR #8](https://github.com/sonoraplay/main/pull/8) el 2026-10-21 |
| Referencias | E-06, tema 5, ADR-0001, ADR-0020, arquitectura v1 (sección 7), HU 23 |

## 1. Contexto

Toda la infraestructura de la EG-26 (VPC, NAT, S3, RDS, IAM) y la de las historias siguientes vive en **una sola región**. La región fija el precio por hora de cada recurso, la latencia hacia los usuarios y qué servicios hay disponibles.

SonoraPlay es ficticia, pero sus usuarios y sellos están en Latinoamérica: Colombia, México, Perú y Argentina aparecen en F3. Las dos candidatas naturales son:

- **us-east-1** (Norte de Virginia): la región más grande y en general la más barata.
- **sa-east-1** (São Paulo): la única región de AWS en Sudamérica disponible para el proyecto.

El costo de la arquitectura v1 (≈ 115–120 USD al mes con todo prendido; ≈ 30–40 USD para el proyecto con ADR-0020) **ya se calculó con precios de us-east-1**.

La carga es casi toda **por lotes**: el consumidor escribe en S3, Spark procesa y la liquidación corre el día 3. La única parte interactiva es la API de sellos (RF-05), que consulta un reporte mensual. No es una aplicación sensible a decenas de milisegundos.

## 2. Qué debe cumplir la decisión

- **Costo:** el menor costo justificable (ADR-0001). El precio por hora pesa porque los servicios están activos durante cada ventana (ADR-0020).
- **Requisito:** HU 23. El costo real debe quedar dentro de ±20 % del estimado, y el estimado está hecho en us-east-1.
- **Requisito:** todos los servicios de la arquitectura v1 deben existir en la región, incluidas las instancias Graviton (t4g y ARM64 en Fargate) y Fargate Spot.
- **Negocio:** la API de sellos (RF-05) debe responder en un tiempo razonable desde Latinoamérica. No hay un SLA de latencia en el enunciado.
- **Negocio:** residencia de datos. Hasta donde sabemos, el enunciado no exige que los datos queden en Latinoamérica. Si el docente lo exigiera, esta decisión cambia.
- **Equipo:** la documentación, los ejemplos y los precios de referencia del curso usan us-east-1.

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. USD/mes (todo prendido) |
|---|---|---|---|
| A · **us-east-1** (Norte de Virginia) | La más barata para EC2, RDS, Fargate y transferencia. Ya es la base del costo estimado (arquitectura v1, sección 7). Tiene todos los servicios y tipos de instancia, y es donde salen primero | Más lejos de los usuarios del sur del continente. Los datos quedan en EE. UU. | ≈ 115–120 (estimado actual) |
| B · sa-east-1 (São Paulo) | Más cerca de los usuarios del Cono Sur. Los datos quedan en Sudamérica | En general es de las regiones más caras: en EC2, RDS y Fargate suele costar del orden de un 50 % más que us-east-1 (se confirma con la calculadora en la HU 23). Obliga a rehacer el estimado. Para Colombia y México no es necesariamente más cercana, porque buena parte del tráfico de la región pasa por Miami | ≈ 170–180 (estimado con el sobrecosto aproximado) |
| C · us-east-2 (Ohio) | Precios parecidos a us-east-1 y menos congestión histórica | No mejora la latencia hacia Latinoamérica. El material del curso y el estimado usan us-east-1 | ≈ 115–120 |

## 4. Decisión

**Elegimos la opción A: us-east-1.** Es la más barata entre las que tienen todos los servicios (criterio de costo de ADR-0001). Además mantiene válido el estimado contra el que se mide la HU 23. La latencia adicional no afecta a una carga por lotes ni a una API que consulta reportes mensuales.

En Terraform la región es una variable (`var.region`, por defecto `us-east-1`) y no aparece fija en ningún nombre ni ARN: todos se arman con `var.region`. Cambiarla es cambiar una variable y volver a crear el entorno, que de todos modos se destruye después de cada ventana (ADR-0020).

## 5. Consecuencias

- **Positivas:**
  - Menor costo por hora en todas las ventanas.
  - El estimado de la arquitectura v1 sigue siendo válido para la HU 23.
  - Están disponibles las instancias Graviton (t4g) y ARM64 en Fargate, que fijó ADR-0001.
- **Negativas / lo que aceptamos:**
  - La API de sellos responde desde EE. UU. Para un sello en Buenos Aires o Santiago, la latencia es mayor que desde São Paulo.
  - Los datos (ficticios) quedan fuera de Latinoamérica.
- **Riesgos y mitigación:**
  - *El docente exige residencia de datos en Latinoamérica.* Mitigación: `terraform apply -var region=sa-east-1` en una ventana nueva, y rehacer el estimado de la HU 23. Este ADR pasaría a *Reemplazado*.
  - *Una caída regional de us-east-1 durante la demo.* Mitigación: aceptado. La recuperación ante desastres en otra región es "Won't" (arquitectura v1, sección 6), y el entorno se puede recrear con Terraform.

## 6. Cómo sabremos que funciona

- `terraform plan` sin `-var region` crea todo en us-east-1, y ningún archivo `.tf` contiene la región escrita a mano fuera de `var.region` (se revisa en el PR con `grep -r "us-east-1" infra/terraform`; solo aparecen los valores por defecto de las variables, del script de huérfanos y del ejemplo de backend).
- HU 23: el costo real de la última semana en Cost Explorer queda dentro de ±20 % del estimado de la arquitectura v1.

## 7. Fuentes

- Regiones y zonas de disponibilidad de AWS: https://docs.aws.amazon.com/global-infrastructure/latest/regions/aws-regions.html
- Precios de Amazon EC2 bajo demanda (por región): https://aws.amazon.com/ec2/pricing/on-demand/
- Precios de Amazon RDS para PostgreSQL: https://aws.amazon.com/rds/postgresql/pricing/
- AWS Pricing Calculator: https://calculator.aws/
- [ADR-0001](0001-arquitectura-base-aws.md), [ADR-0020](0020-ventanas-encendido-aws.md) y la [arquitectura v1](../arquitectura/arquitectura-v1.md).

---

## English — Decision summary

**Accepted (proposed October 14, 2026; approved October 21, 2026 in PR #8; EG-26).** The project runs in **us-east-1**: it is the cheapest region that offers every service in the architecture, and it keeps the HU 23 cost estimate valid. The extra latency from Latin America does not matter for batch jobs or for an API that serves monthly reports. The region is a Terraform variable (`var.region`) and never appears hard-coded in names or ARNs.

**Traceability:** The Spanish sections above are the full decision record. This summary introduces no new decision.
