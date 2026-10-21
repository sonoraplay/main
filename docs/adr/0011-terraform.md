# ADR-0011 · Infraestructura como código con Terraform (estado en S3 con bloqueo nativo)

| Campo | Valor |
|---|---|
| Estado | Propuesto |
| Fecha | 2026-10-14 |
| Historia que lo origina | HU 17 · EG-26 |
| Responsable | Andrea Zárate |
| Revisó | Pendiente (revisor del PR) |
| Referencias | E-06, E-12, temas 5–7, ADR-0001, ADR-0017, ADR-0020, penalizaciones de −10 % (infraestructura sin destruir) y −15 % (credencial expuesta) |

## 1. Contexto

El entregable E-06 pide la infraestructura como código. ADR-0020 lleva ese requisito más lejos: el entorno se **crea y se destruye en cada ventana de prueba** (Sprints 3 a 5) y una vez más después de la demo. Si queda algo sin destruir, la penalización es de −10 %. Por eso la herramienta tiene que:

- crear todo lo de la EG-26 en un solo paso: VPC, NAT, Security Groups, S3, RDS e IAM;
- destruirlo sin huérfanos (criterio 1);
- llevar la cuenta de lo que creó, para que `destroy` sepa qué borrar.

Hay dos complicaciones:
- La contraseña de RDS no puede quedar en el repositorio (penalización de −15 %) y debe vivir en SSM Parameter Store (criterio 5).
- El equipo es de tres personas, y dos podrían ejecutar un `apply` a la vez.

## 2. Qué debe cumplir la decisión

- **Requisito:** E-06 y HU 17 / HU 38. `apply` y `destroy` reproducibles. Cada recurso lleva `Project=sonoraplay` (criterio 1).
- **Penalización:** −10 % si queda infraestructura sin destruir. La herramienta debe saber qué creó.
- **Penalización:** −15 % por una credencial expuesta. Ni el código ni el estado deben guardar la contraseña de RDS en texto plano.
- **Costo:** el estado y el bloqueo deben costar casi nada entre ventanas (ADR-0020).
- **Equipo:** dos personas no deben aplicar cambios a la vez sobre el mismo estado. El código se revisa en PR, con validación automática en el CI.
- **Tema 5–7:** IAM, VPC, S3 y RDS deben quedar declarados y legibles para la evaluación.

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · Scripts de AWS CLI (bash) | Sin herramientas nuevas | No hay estado. `destroy` hay que escribirlo a mano, en orden inverso y sin olvidar nada, y es justo donde está la penalización de −10 %. No son idempotentes: correrlos dos veces falla o duplica recursos | 0 |
| B · AWS CloudFormation | Nativo de AWS, sin estado que guardar (lo lleva AWS) y `delete-stack` borra todo | YAML/JSON verboso. Los errores aparecen al desplegar, no antes. No tiene un equivalente directo a los atributos write-only para la contraseña. El equipo no lo ha usado | 0 |
| C · AWS CDK | Código en Python, el lenguaje del equipo | Genera CloudFormation (los mismos límites que B) y suma Node.js y un *bootstrap* de CDK con su propio bucket y roles | ≈ 0 |
| D · **Terraform**, estado en S3 con bloqueo nativo | Declarativo, con `plan` antes de aplicar. `destroy` usa el estado, así que borra exactamente lo creado. `default_tags` etiqueta todo. Los atributos *write-only* y los recursos efímeros mantienen la contraseña fuera del estado. `fmt`, `validate` y Checkov corren en el CI sin credenciales | Hay que guardar el estado: un bucket que se crea una vez (*bootstrap*). Es otra herramienta, aunque el curso la usa | ≈ 0,01 (bucket del estado) |

## 4. Decisión

**Elegimos la opción D: Terraform ≥ 1.11 con el proveedor `hashicorp/aws` 6.x.** Es la única opción que tiene a la vez un `destroy` basado en estado, que protege contra la penalización de −10 %, y secretos fuera del estado, que protegen contra la de −15 %, con un costo casi nulo (sección 2).

Cómo queda organizado (`infra/terraform/`):

- **Dos stacks:**
  - `bootstrap/` crea una sola vez el bucket del estado, con versionado, cifrado, Block Public Access, solo TLS y `prevent_destroy`. Es uno de los recursos persistentes de ADR-0020.
  - La raíz contiene el entorno que se crea y se destruye en cada ventana: `red.tf`, `security_groups.tf`, `s3.tf`, `rds.tf` e `iam.tf`.
- **Estado remoto:**
  - backend `s3` con `use_lockfile = true` (bloqueo nativo de S3, sin tabla de DynamoDB) y `encrypt = true`;
  - el nombre del bucket va en `backend.hcl`, que no se versiona; hay un ejemplo en `backend.hcl.example`.
- **Etiquetas:** `default_tags` del proveedor agrega `Project`, `Environment` y `ManagedBy` a todos los recursos. El volumen raíz de la NAT, al que `default_tags` no llega, se etiqueta de forma explícita.
- **Contraseña de RDS:**
  - la genera `ephemeral "random_password"`;
  - llega a RDS con `password_wo` y a SSM con `value_wo` (SecureString);
  - ninguno de esos valores se guarda en el plan ni en el estado;
  - para rotarla se sube `rds_password_version`.
- **Destroy limpio:** `destruccion_limpia = true` (por defecto) activa `force_destroy` en los buckets, `skip_final_snapshot` y `delete_automated_backups` en RDS, y desactiva la protección contra borrado. `verificar-huerfanos.sh` comprueba después que no quede nada con `Project=sonoraplay`.
- **Proveedores fijados:** `.terraform.lock.hcl` se versiona y el CI usa Terraform 1.16.6.
- **CI:** el job `terraform` corre `fmt -check`, `validate` (sin backend ni credenciales) y Checkov. Checkov tiene excepciones justificadas en `.checkov.yaml`. El CI **nunca** ejecuta `apply`: lo hace una persona del equipo en cada ventana. El despliegue con OIDC llega con ADR-0017 (EG-40).

## 5. Consecuencias

- **Positivas:**
  - Cada ventana es `apply` → prueba → `destroy` con los mismos comandos.
  - Lo que se va a crear o borrar se ve en `plan` antes de tocar AWS.
  - La contraseña nunca pasa por el repositorio ni por el estado.
  - El CI detecta errores de sintaxis y de seguridad antes de la revisión.
- **Negativas / lo que aceptamos:**
  - El bucket del estado se crea a mano una vez (`bootstrap`), con estado local, y sobrevive a todas las ventanas por diseño (ADR-0020).
  - Los atributos write-only exigen Terraform ≥ 1.11 en todas las máquinas del equipo.
  - Si un `apply` falla después de crear RDS y antes de guardar el parámetro de SSM, la contraseña de SSM y la de RDS pueden quedar distintas. Se arregla subiendo `rds_password_version`.
- **Riesgos y mitigación:**
  - *Alguien crea recursos a mano en la consola.* `destroy` no los conoce. Mitigación: regla del equipo, nada fuera de Terraform (ADR-0020); `verificar-huerfanos.sh` y AWS Budgets (HU 23) los delatan.
  - *Dos `apply` simultáneos.* Mitigación: el bloqueo nativo de S3 rechaza el segundo.
  - *El estado se daña o se borra.* Mitigación: el versionado del bucket conserva las versiones anteriores durante 30 días.
  - *Se pierde el estado con el entorno prendido.* Mitigación: todo lleva `Project=sonoraplay`, así que se puede encontrar y borrar con la API de etiquetas.

## 6. Cómo sabremos que funciona

- **CI de cada PR:** `terraform fmt -check`, `terraform validate` en los dos stacks y Checkov sin fallos.
- **Primera ventana de prueba (criterio 1 de la EG-26):**
  1. `terraform apply` crea todo sin errores.
  2. Comprobaciones:
     - `aws rds describe-db-instances` muestra `PubliclyAccessible=false` y `BackupRetentionPeriod=7`;
     - `aws s3api get-public-access-block` y `get-bucket-encryption` responden en las tres capas;
     - `aws ssm get-parameter --name /sonoraplay/rds/password --with-decryption` devuelve la contraseña;
     - `grep` sobre el estado no la encuentra.
  3. `terraform destroy` termina sin errores.
  4. `./verificar-huerfanos.sh` imprime `OK`.
- Se guarda la evidencia (salidas de `apply`, `destroy` y del script) en la HU 17.

## 7. Fuentes

- Terraform, backend S3 (incluye `use_lockfile`): https://developer.hashicorp.com/terraform/language/backend/s3
- Terraform, valores efímeros y atributos write-only: https://developer.hashicorp.com/terraform/language/manage-sensitive-data/ephemeral
- Proveedor AWS, `default_tags`: https://registry.terraform.io/providers/hashicorp/aws/latest/docs#default_tags
- Proveedor AWS, `aws_db_instance` (`password_wo`): https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/db_instance
- Checkov: https://www.checkov.io/
- [ADR-0001](0001-arquitectura-base-aws.md), [ADR-0020](0020-ventanas-encendido-aws.md).

---

## English — Decision summary

**Proposed (October 14, 2026; EG-26).** Infrastructure is code with **Terraform ≥ 1.11** and the `hashicorp/aws` 6.x provider. It is the only option with both a state-based `destroy` (protects against the −10 % penalty for leftover resources) and secrets kept out of the state through ephemeral resources and write-only attributes (protects against the −15 % penalty). State lives in a versioned, encrypted S3 bucket with native S3 locking (`use_lockfile`). A one-time `bootstrap/` stack creates that bucket, and the root stack is created and destroyed in each test window (ADR-0020). CI runs `fmt`, `validate` and Checkov.

**Traceability:** The Spanish sections above are the full decision record. This summary introduces no new decision.
