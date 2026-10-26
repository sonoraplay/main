# ADR-0010 · Salida a internet de las subredes privadas: instancia NAT t4g.nano en lugar de NAT Gateway

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-14 |
| Historia que lo origina | HU 17 · EG-26 |
| Responsable | Andrea Zárate |
| Revisó | Julián: aprobó el [PR #8](https://github.com/sonoraplay/main/pull/8) el 2026-10-21 |
| Referencias | E-06, tema 6, ADR-0001, ADR-0009, ADR-0020, arquitectura v1 (secciones 2, 6 y 8) |

> **Nota (2026-10-21):** mientras la cuenta esté en el plan gratuito de AWS, que no permite `t4g.nano`, las ventanas usan `t4g.micro`. Ver [ADR-0022](0022-excepcion-plan-gratuito-rds-nat.md).

## 1. Contexto

El criterio 2 de la EG-26 pone el cómputo y los datos en **subredes privadas**: las tareas de Fargate, las EC2 de RabbitMQ y Airflow, y RDS. Aun así, varias de esas piezas necesitan salir a internet:

- ECS descarga las imágenes de **ECR**.
- Los contenedores envían logs a **CloudWatch Logs**.
- El agente de **SSM** abre las sesiones del equipo y el túnel de Power BI (flujo ⑫).
- Airflow trae **F6** (tasas de cambio) y **F7** (países) de internet (flujo ⑩).

El tráfico a S3 no necesita NAT: va por un **endpoint gateway**, que es gratis.

AWS ofrece dos formas de dar esa salida:
- el **NAT Gateway**, administrado y altamente disponible dentro de una AZ, que se cobra por hora y por GB procesado;
- una **instancia NAT**: una EC2 en una subred pública que reenvía y enmascara el tráfico.

ADR-0001 eligió la instancia NAT como parte de la opción C. Este ADR registra la comparación y cómo se implementó en Terraform.

## 2. Qué debe cumplir la decisión

- **Requisito:** criterio 2 de la EG-26. Solo el ALB y la NAT viven en subredes públicas.
- **Costo:** el menor costo justificable (ADR-0001). La salida se paga todas las horas mientras el entorno está prendido (ADR-0020).
- **Requisito:** volumen bajo. Por la NAT pasan imágenes, logs, sesiones de SSM y descargas pequeñas de F6/F7. Los datos de F2 van a S3 por el endpoint.
- **Requisito:** HU 17 y HU 38. `terraform apply` y `destroy` sin pasos manuales.
- **Seguridad:** principio 3 de la arquitectura. La NAT no acepta tráfico de internet ni tiene SSH: se administra con SSM.
- **Tema 6:** la VPC, las subredes, las tablas de rutas y la salida a internet se configuran explícitamente.

## 3. Opciones consideradas

Precios de lista en us-east-1 (ADR-0009). Se confirman en la HU 23.

| Opción | A favor | En contra | Costo aprox. USD/mes (730 h) |
|---|---|---|---|
| A · NAT Gateway (1, en una AZ) | Administrado; escala solo, hasta decenas de Gbps; sin parches | 0,045 USD/h ≈ 33 USD/mes, más 0,045 USD por GB procesado y su IPv4 pública. Es casi la mitad de lo que cuestan RDS y la EC2 de Airflow juntas | ≈ 37 + datos |
| B · NAT Gateway por AZ (2) | Sin punto único de falla entre AZ | Duplica A | ≈ 74 + datos |
| C · **Instancia NAT t4g.nano** | 0,0042 USD/h ≈ 3 USD/mes, más 8 GB de disco y su IPv4 pública. No cobra por GB procesado. Ejercita el tema 6 (reenvío, rutas y `source_dest_check`) | Punto único de falla. Hay que mantenerla (AMI, parches). Ancho de banda limitado (hasta ≈ 5 Gbps en ráfaga) | ≈ 7 (instancia, disco e IPv4) |
| D · Endpoints de interfaz para ECR, Logs y SSM, sin NAT | No hay salida a internet. Más seguro | ≈ 7 USD/mes por endpoint y AZ (≈ 40+ USD/mes). No resuelve F6/F7, que necesitan internet | ≈ 40+ |

## 4. Decisión

**Elegimos la opción C: una instancia NAT t4g.nano** en la primera subred pública. Las tablas de rutas privadas de las dos AZ apuntan a su interfaz de red. Cumple el criterio 2 por cerca de una quinta parte del costo de un NAT Gateway, y el tráfico que la cruza es poco (criterios de costo y de volumen de la sección 2).

Implementación (`infra/terraform/red.tf`):

- **AMI:** Amazon Linux 2023 ARM64, tomada del parámetro público de SSM. `ignore_changes = [ami]`, para que una AMI nueva no reemplace la NAT en medio de una ventana.
- **Reenvío:** `source_dest_check = false`. El *user data* activa `net.ipv4.ip_forward` y agrega una regla `MASQUERADE` para el rango de la VPC con `iptables-services`, que persiste tras un reinicio.
- **Seguridad:**
  - `sg-nat` acepta tráfico solo desde `10.0.0.0/16`;
  - no hay SSH ni par de llaves;
  - se administra con Session Manager (rol `sonoraplay-dev-nat-ec2`, solo con `AmazonSSMManagedInstanceCore`);
  - usa IMDSv2 y el disco está cifrado.
- **Recuperación:** una alarma de CloudWatch sobre `StatusCheckFailed_System` ejecuta `ec2:recover`. La instancia recuperada conserva su ID, su IP y su interfaz, así que las rutas no cambian.
- **IP pública:** se asigna al crearla (`associate_public_ip_address`); no hace falta una Elastic IP. Ninguna otra subred da IP pública por defecto (`map_public_ip_on_launch = false`).

## 5. Consecuencias

- **Positivas:**
  - Ahorra ≈ 30 USD al mes con todo prendido frente a A, y ≈ 7–8 USD en la semana de la demo.
  - No hay costo por GB.
  - Las tablas de rutas quedan listas para agregar una NAT por AZ si hiciera falta.
- **Negativas / lo que aceptamos:**
  - **Punto único de falla.** Si la NAT cae, se cortan las descargas de ECR, los logs, SSM y F6/F7 (arquitectura v1, sección 8). S3 sigue funcionando por el endpoint gateway, y RDS no depende de la NAT.
  - La AZ de la segunda subred privada sale por la NAT de la primera AZ, con tráfico entre AZ de bajo volumen.
  - El equipo es responsable de la AMI. Cada ventana crea la NAT con la AMI más reciente, así que los parches llegan solos con ADR-0020.
- **Riesgos y mitigación:**
  - *Falla del hardware.* Mitigación: la alarma de recuperación automática.
  - *Falla del sistema operativo o del user data* (por ejemplo, que `dnf` no tenga red). Mitigación: la prueba de salida de la sección 6 en cada ventana; si falla, `terraform apply -replace=aws_instance.nat`.
  - *Saturación del ancho de banda.* Mitigación: los datos grandes van a S3 por el endpoint. Si se satura, se sube el tipo de instancia (`var.nat_instance_type`).

## 6. Cómo sabremos que funciona

En cada ventana de prueba (ADR-0020), después de `terraform apply`:

1. Desde una instancia o tarea en una subred privada (por ejemplo, la EC2 de Airflow por Session Manager), `curl -sI https://aws.amazon.com` responde, y `curl -s https://checkip.amazonaws.com` devuelve la IP pública de la NAT.
2. `aws ec2 describe-instances` muestra la NAT en una subred `Tier=publica` con `SourceDestCheck=false`. Ninguna otra instancia está en una subred pública.
3. La alarma `sonoraplay-dev-nat-recuperacion` está en estado `OK`.
4. HU 23: el rubro de la NAT en Cost Explorer queda cerca de 0,01 USD por hora prendida.

## 7. Fuentes

- Instancias NAT (documentación de Amazon VPC): https://docs.aws.amazon.com/vpc/latest/userguide/VPC_NAT_Instance.html
- Comparación entre NAT Gateway e instancia NAT: https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-comparison.html
- Precios de Amazon VPC (NAT Gateway, IPv4 públicas, endpoints): https://aws.amazon.com/vpc/pricing/
- Recuperación automática de instancias EC2: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-recover.html
- [ADR-0001](0001-arquitectura-base-aws.md), [ADR-0009](0009-region-aws.md), [ADR-0020](0020-ventanas-encendido-aws.md).

---

## English — Decision summary

**Accepted (proposed October 14, 2026; approved October 21, 2026 in PR #8; EG-26).** Private subnets reach the internet through a **NAT instance** on ARM64, not a NAT Gateway: about one fifth of the cost for the project's low traffic (S3 goes through the free gateway endpoint). It has `source_dest_check = false`, iptables masquerading, no SSH (Session Manager only), IMDSv2, an encrypted disk, and a CloudWatch alarm that recovers the instance. While the account is on the AWS free plan, the type is `t4g.micro` instead of `t4g.nano` ([ADR-0022](0022-excepcion-plan-gratuito-rds-nat.md)).

**Traceability:** The Spanish sections above are the full decision record. This summary introduces no new decision.
