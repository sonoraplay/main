# ADR-0017 · CI/CD con OIDC y secretos en SSM Parameter Store

| Campo | Valor |
|---|---|
| Estado | **Propuesto** (pendiente de revisión por Julián y María Clara) |
| Fecha | 2026-11-03 |
| Historia que lo origina | HU 31 · EG-40 |
| Responsable | Andrea |
| Revisó | Pendiente |
| Referencias | CT-02, E-09, temas 17–18, ADR-0011, ADR-0012, ADR-0020 |

## 1. Contexto

El pipeline debe publicar imágenes en ECR y actualizar ECS desde GitHub Actions. Guardar llaves de AWS como secretos del repositorio las deja vigentes hasta que alguien las rote y amplía el daño si se filtran. El equipo ya guarda los secretos de la aplicación en SSM Parameter Store (`/sonoraplay/*`).

## 2. Qué debe cumplir la decisión

- **Requisito (EG-40):** sin llaves de AWS guardadas; rol por OIDC.
- **Seguridad:** mínimo privilegio y solo desde `main` de este repositorio.
- **Costo:** SSM estándar y OIDC no cuestan.
- **Operación:** el rol sobrevive al `destroy` de las ventanas (ADR-0020).

## 3. Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| **A · OIDC + rol IAM acotado; secretos de la aplicación en SSM (elegida)** | Credenciales de vida corta, sin rotación manual, condicionadas a repo y rama; el entorno ya usa SSM | Un solo proveedor OIDC por cuenta; hay que guardar el ARN del rol como variable de GitHub |
| B · Usuario IAM con llaves en secretos de GitHub | Simple | Llaves de larga vida; incumple el criterio de la EG-40 |
| C · Secrets Manager | Rotación automática | Cobra por secreto y por llamada; SSM basta |

## 4. Decisión

OIDC con el rol `sonoraplay-dev-github-deploy` (`infra/terraform/cicd/`), asumible solo por el workflow de la rama `main` de `sonoraplay/main`. Permite: publicar en `sonoraplay/*` de ECR, registrar definiciones de tarea, actualizar los servicios de ECS del clúster y `iam:PassRole` solo de los roles `sonoraplay-dev-*` hacia `ecs-tasks`. Los secretos de la aplicación siguen en SSM (`/sonoraplay/...`) y nunca entran a una imagen ni al repositorio (gitleaks lo vigila).

## 5. Consecuencias

- El workflow `deploy.yml` se omite si no existe la variable `AWS_DEPLOY_ROLE_ARN`.
- Un despliegue que falle se revierte solo por el circuit breaker de `ecs.tf`.
- Quien despliegue desde su equipo sigue usando `publicar-imagen.sh` con su sesión.

## 6. Pendiente de comprobar

Este ADR no afirma que el rol se haya creado ni que el workflow haya corrido contra AWS. Falta: `apply` del stack `cicd`, configurar la variable, hacer un merge a `main` y ver las imágenes en ECR y el servicio actualizado; y provocar un despliegue fallido para ver el rollback.
