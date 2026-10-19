---
sidebar_position: 1
title: "EG-26 · Evidencia en AWS"
---

# EG-26 · IAM, VPC, S3 por capas y RDS: evidencia en AWS

**Sprint 3 · HU 17 · Entregable E-06.** Esta página reúne la prueba de que el Terraform de la EG-26 crea la infraestructura base en AWS, cumple los criterios de aceptación y se destruye sin dejar recursos huérfanos.

| Dato | Valor |
|---|---|
| Fecha de la ventana | 19 oct 2026, de 09:46 a 11:23 (hora de Bogotá) |
| Cuenta / región | `6498****9012` / `us-east-1` |
| Código | Rama `feature/EG-26-iam-vpc-s3-rds`, commit `1057f25` (PR #26) |
| Ejecución | AWS CloudShell, Terraform 1.16.6 |
| Política | Ventana de encendido: `apply` → verificar → `destroy` el mismo día ([ADR-0020](../adr/0020-ventanas-encendido-aws.md)) |

Las imágenes muestran la salida real de los comandos. El ID de la cuenta está enmascarado, y ninguna imagen contiene la contraseña de RDS.

## Resumen por criterio

| Criterio | Resultado | Evidencia |
|---|---|---|
| **C1** · `apply` y `destroy` sin huérfanos | ✅ | CloudTrail, historial del estado y `Destroy complete! Resources: 104 destroyed.` |
| **C2** · VPC en 2 AZ con subredes públicas y privadas | ✅ | 4 subredes /24 en us-east-1a y us-east-1b; solo la NAT en una subred pública |
| **C3** · Un rol de mínimo privilegio por servicio, sin llaves | ✅ | 13 roles, 0 usuarios IAM; el consumidor escribe en Bronze y no en Gold |
| **C4** · Bronze, Silver y Gold privados y cifrados | ✅ | Block Public Access completo y `AES256` |
| **C5** · RDS privada, backups de 7 días, credenciales en SSM | ⚠️ | Privada y cifrada, contraseña como `SecureString`; **backups de 1 día** por el plan gratuito (ver la nota) |
| **C6** · ADR-0009, 0010 y 0011 | ✅ | Escritos en el PR #26 |

## 1. Creación (`apply`)

Primero se crea, una sola vez, el bucket donde Terraform guarda su estado. Es el único recurso que se queda entre ventanas.

![Bootstrap del bucket del estado](./img/eg26-00-bootstrap.png)

CloudTrail, el registro de auditoría de AWS, muestra cada recurso creado por el `apply` en unos 10 minutos. RDS es lo que más tarda.

![CloudTrail: creación](./img/eg26-01-cloudtrail-creacion.png)

## 2. Verificación de los criterios

### C2 · Red

Cuatro subredes en dos zonas de disponibilidad. La única máquina es la instancia NAT (ADR-0010), en una subred pública.

![C2: subredes y NAT](./img/eg26-04-c2-red.png)

### C3 · IAM

Cada servicio de ECS tiene un rol de ejecución y uno de tarea, y la cuenta no tiene usuarios IAM, así que no hay access keys. La simulación de políticas confirma el mínimo privilegio: el consumidor puede escribir en Bronze, y Gold le queda denegado.

![C3: roles y simulación de políticas](./img/eg26-05-c3-iam.png)

### C4 · Data Lake por capas

![C4: Block Public Access y cifrado](./img/eg26-06-c4-s3.png)

### C5 · RDS y SSM

La base no tiene IP pública, está cifrada y vive en una sola zona. Las credenciales están en SSM Parameter Store; la contraseña es `SecureString` y se lista sin descifrar.

![C5: RDS y parámetros SSM](./img/eg26-07-c5-rds.png)

:::warning Nota sobre los backups (C5)
La cuenta está en el **plan gratuito** de AWS, que rechaza RDS con más de 1 día de backups (`FreeTierRestrictionError`) y no permite instancias `t4g.nano`. Por eso el commit `1057f25` usa `rds_backup_retention_days = 1` y la NAT `t4g.micro`. Con un plan pago basta volver a poner 7 días y `t4g.nano`, sin más cambios. Pendiente: confirmarlo con el instructor y actualizar el ADR-0010.
:::

![Plan de la cuenta](./img/eg26-09-plan-cuenta.png)

## 3. Destrucción el mismo día (`destroy`)

El `destroy` borra los 104 recursos del stack. Los buckets se vacían antes de borrarse y RDS no deja snapshot final (`destruccion_limpia = true`).

![terraform destroy](./img/eg26-08-destroy.png)

CloudTrail confirma el borrado de cada recurso entre las 11:19 y las 11:23 (hora de Bogotá).

![CloudTrail: destrucción](./img/eg26-02-cloudtrail-destruccion.png)

El estado de Terraform tiene versionado en S3, así que se ve su historia completa: crece con el `apply` y queda vacío (325 bytes) después del `destroy`.

![Historial del estado de Terraform](./img/eg26-03-estado-terraform.png)

### Sin huérfanos

Después del `destroy` se revisó cada servicio directamente: EC2, EBS, RDS (instancias, snapshots, backups automáticos, parameter y subnet groups), VPC, subredes, endpoints, interfaces de red, IP elásticas, security groups, CloudWatch, SSM e IAM. **No quedó ninguno.** Solo queda el bucket del estado, que es persistente por diseño.

:::info Por qué `verificar-huerfanos.sh` listó recursos
El script consulta la API de etiquetas de AWS (Resource Groups Tagging), que tarda varios minutos en olvidar lo que se borró. Justo después del `destroy` todavía nombraba la NAT y su volumen, que ya no existían. La revisión servicio por servicio y CloudTrail son la prueba confiable.
:::

## 4. Hallazgos de la ventana

| Hallazgo | Causa | Arreglo |
|---|---|---|
| RDS y la NAT no se crearon en el primer `apply` | Restricciones del plan gratuito | NAT `t4g.micro` y backups de 1 día (commit `1057f25`) |
| Una regla de SG falló | La descripción tenía `%`, que AWS no acepta | Cambiado a "porcentaje" (commit `1057f25`) |
| `password authentication failed` tras un `apply` parcial | La contraseña efímera se regenera en cada `apply` y SSM no se reescribe | Inmediato: `terraform apply -var rds_password_version=2`. De fondo: `depends_on` del parámetro hacia RDS |
| El parameter group aparece cambiado en cada plan | AWS guarda `rds.force_ssl` como `pending-reboot` | Agregar `apply_method = "pending-reboot"` en `rds.tf` |
| CloudShell sin espacio | `$HOME` tiene 1 GB y el proveedor de AWS pesa cientos de MB | Código y proveedores en `/tmp` con `TF_PLUGIN_CACHE_DIR` |

## 5. Prueba adicional: el pipeline sobre la infraestructura

En la ventana del 15 de octubre se corrió el esqueleto ([EG-24](../esqueleto.md)) contra la RDS privada, desde un entorno de CloudShell dentro de la VPC (subred privada y SG `airflow`):

- se cargaron 10.000 usuarios, 8.712 suscripciones, 69.227 pagos, 50 titulares y 208 contratos;
- se publicó la liquidación de 2026-09 para Colombia en `reporte_regalias`;
- se subieron `f1/` y `f2/fecha=2026-09-30/` al bucket Bronze.

Eso confirma que la red privada, la NAT, el endpoint de S3, la regla `airflow → rds` y las credenciales en SSM funcionan juntos.

## Cómo repetir la ventana

```bash
# Parte 1: crear y verificar (unos 15 min)
bash ventana-eg26-parte1-crear.sh
# Parte 2: destruir el mismo día
bash ventana-eg26-parte2-destruir.sh
```

Los dos scripts se corren en AWS CloudShell (us-east-1) y guardan la evidencia en `~/evidencia-eg26`. La guía completa está en el [README de `infra/terraform`](https://github.com/JoshuaQ-rJ/sonoraplay-proyect/tree/develop/infra/terraform).
