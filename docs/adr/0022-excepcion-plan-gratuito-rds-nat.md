# ADR-0022 · Excepción del plan gratuito de AWS: backups de RDS de 1 día y NAT t4g.micro mientras dure el plan

| Campo | Valor |
|---|---|
| Estado | **Aceptado** (excepción aprobada por Julián el 2026-10-20, revisión del PR #4) |
| Fecha | 2026-10-21 |
| Historia que lo origina | HU 17 · EG-26 (criterio 5) |
| Responsable | Equipo de infraestructura (EG-26) |
| Revisó | Julián: aprobó la excepción de C5 en su revisión del [PR #4](https://github.com/sonoraplay/main/pull/4) |
| Referencias | [ADR-0010](0010-instancia-nat.md), [ADR-0020](0020-ventanas-encendido-aws.md), [evidencia de la EG-26](../infraestructura/eg26-evidencia-aws.md), commit `1057f25`, HU 38 (EG-47) |

## 1. Contexto

El criterio 5 de la EG-26 pide RDS con **7 días** de backups automáticos, y ADR-0010 eligió una instancia NAT **t4g.nano**.

En la ventana del 19 de octubre, la cuenta del proyecto estaba en el **plan gratuito** de AWS, y el primer `apply` falló por dos restricciones de ese plan:

- RDS rechaza más de 1 día de backups (`FreeTierRestrictionError`);
- no se pueden lanzar instancias `t4g.nano`.

El commit `1057f25` dejó `rds_backup_retention_days = 1` y `nat_instance_type = "t4g.micro"`, y con eso la ventana cumplió los demás criterios. El criterio 5 queda en ⚠️ hasta que alguien decida si se acepta la excepción.

## 2. Qué debe cumplir la decisión

- **Requisito:** el criterio 5 de la EG-26 y el entregable E-06 deben quedar cumplidos o con la excepción registrada y aprobada.
- **Costo:** el menor costo justificable (ADR-0001, ADR-0020). Los créditos del plan gratuito cubren las ventanas de prueba.
- **Datos:** según ADR-0020, los datos de una ventana se regeneran con el seed y `destruccion_limpia = true` borra los backups en cada `destroy`. Ningún backup sobrevive a la ventana.
- **Reversibilidad:** volver a 7 días y `t4g.nano` no debe exigir cambios de código.

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. |
|---|---|---|---|
| A · **Excepción temporal**: 1 día de backups y NAT `t4g.micro` mientras la cuenta esté en el plan gratuito | Sin gastar dinero fuera de los créditos. Las ventanas duran horas y se destruyen el mismo día, así que 7 días de retención no aportan nada en ellas | El criterio 5 no se cumple literalmente durante las ventanas. La NAT `t4g.micro` cuesta el doble que la `t4g.nano` | 0 USD extra en ventanas; NAT ≈ 0,0084 USD/h frente a ≈ 0,0042 USD/h |
| B · Pasar la cuenta a plan pago ya | Cumple el criterio 5 y ADR-0010 tal como están escritos. Los créditos se conservan | Sale del plan gratuito antes de necesitarlo; un error de destrucción se paga con dinero | Backups dentro de los 20 GB gratuitos por instancia; NAT `t4g.nano` |
| C · Repetir la ventana en otra cuenta con plan pago | Evidencia del criterio 5 con 7 días | Segunda cuenta que administrar, otra ventana y otra evidencia | Igual que B, más el tiempo de la ventana |

## 4. Decisión

**Elegimos la opción A como excepción temporal.** Mientras la cuenta esté en el plan gratuito, las ventanas usan 1 día de backups y NAT `t4g.micro`. **Antes del encendido continuo de la última semana (ADR-0020)**, o cuando la cuenta pase a plan pago, se vuelve a `rds_backup_retention_days = 7` y `nat_instance_type = "t4g.nano"`. Solo cambian esas dos variables; el código queda igual.

Con ADR-0020, los backups no sobreviven a una ventana, así que 7 días de retención no protegen nada hasta que la plataforma quede prendida de forma continua. A partir de ese momento sí importan, y la excepción termina.

## 5. Consecuencias

- **Positivas:** las ventanas de S3–S5 siguen sin costo fuera de los créditos, y el cambio a la configuración final son dos variables.
- **Negativas / lo que aceptamos:** durante las ventanas, la recuperación a un punto en el tiempo de RDS cubre 1 día y no 7. La NAT cuesta ≈ 0,004 USD/h más.
- **Riesgos y mitigación:** olvidar volver a 7 días antes de la última semana. Mitigación: el runbook de la HU 38 (EG-47) incluye el paso y su verificación (`BackupRetentionPeriod = 7`), y las variables lo explican en su descripción.

## 6. Cómo sabremos que funciona

- En las ventanas con plan gratuito, `aws rds describe-db-instances` devuelve `BackupRetentionPeriod = 1`, y el resto de la evidencia de la EG-26 se mantiene.
- En el encendido continuo, el mismo comando devuelve `7` y la NAT es `t4g.nano` (`aws ec2 describe-instances`).

## Nota del 2026-10-22 · NAT en `t4g.small` en la ventana de la EG-27

Según el reporte de la ventana del 22 de octubre, **no había capacidad de `t4g.micro` en `us-east-1a`**, así que la instancia NAT quedó en **`t4g.small`** (verificado con `aws ec2 describe-instances`: `sonoraplay-dev-nat`, `t4g.small`, `us-east-1a`). Esto es distinto de la restricción del plan gratuito de esta excepción: aquí la causa es falta de capacidad de AWS en la zona.

- **Costo:** `t4g.small` ≈ 0,0168 USD/h, el doble de `t4g.micro` (≈ 0,0084) y cuatro veces `t4g.nano` (≈ 0,0042). Para una ventana de 3 h son unos 0,03 USD más que con `t4g.micro`.
- **Configuración:** no hace falta cambiar código. `nat_instance_type` ya es una variable; se pasa `-var nat_instance_type=t4g.small` al `apply` cuando la zona no tenga capacidad. El valor por defecto sigue siendo `t4g.micro`.
- **Reversión:** igual que en la sección 4. Antes del encendido continuo de la última semana, `nat_instance_type = "t4g.nano"`.
- **Verificación:** el comando de la sección 6 puede devolver `t4g.small` en una ventana concreta; es válido siempre que la causa quede anotada en la evidencia de esa ventana.
- **Pendiente:** decidir si conviene fijar una zona alternativa o un tipo de reserva, en lugar de reintentar a mano. No se decidió aquí.

## 7. Fuentes

- Amazon RDS, retención de backups: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.BackupRetention.html
- AWS Free Tier y planes de la cuenta: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html
- Precios de Amazon EC2 (t4g): https://aws.amazon.com/ec2/pricing/on-demand/
- [Evidencia en AWS de la EG-26](../infraestructura/eg26-evidencia-aws.md), sección «Puntos abiertos».

---

## English — Decision summary

**Accepted (recorded October 21, 2026; EG-26).** Julián approved the exception on October 20, 2026 in his review of PR #4. While the AWS account is on the **free plan**, which rejects RDS backup retention above 1 day and `t4g.nano` instances, test windows use **1-day RDS backups** and a **`t4g.micro` NAT instance**. Because ADR-0020 destroys everything after each window (including automated backups), 7-day retention adds no protection during windows. Before the continuous final-week deployment, or when the account moves to a paid plan, the team restores `rds_backup_retention_days = 7` and `nat_instance_type = "t4g.nano"`. Only those two variables change. The EG-47 runbook must include this step.
