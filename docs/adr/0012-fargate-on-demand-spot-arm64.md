# ADR-0012 · Cómputo en Fargate ARM64: On-Demand para las APIs y Spot para lo que tolera interrupciones

| Campo | Valor |
|---|---|
| Estado | **Aceptado** (aprobado por Julián el 2026-10-22 al fusionar el [PR #24](https://github.com/sonoraplay/main/pull/24)) |
| Fecha | 2026-10-21 |
| Historia que lo origina | HU 18 · EG-27 |
| Responsable | Andrea |
| Revisó | Julián: aprobó el ADR el 2026-10-22 al fusionar el PR #24, incluida la operación en HTTP sin dominio, solo con datos sintéticos, mientras no haya certificado de ACM (sección 5) |
| Referencias | RF-05, RN-11, RNF-04, temas 8–9 y 16, [ADR-0001](0001-arquitectura-base-aws.md), [ADR-0006](0006-autenticacion-aislamiento-sellos.md), ADR-0013 (EG-29), [ADR-0020](0020-ventanas-encendido-aws.md) |

## 1. Contexto

La arquitectura v1 (ADR-0001) pone en ECS Fargate:

- las dos APIs (titulares y contratos F4);
- el simulador F2;
- el consumidor F2 → Bronze;
- los jobs de Spark.

La EG-27 despliega la primera de ellas, la API de titulares, detrás de un ALB. Para eso hay que fijar dos cosas que se repiten en cada servicio: la **arquitectura de CPU** (x86 o ARM64/Graviton) y la **capacidad** (Fargate On-Demand o Fargate Spot).

Fargate cobra por vCPU-hora y GB-hora mientras la tarea corre. Spot usa capacidad sobrante con hasta 70 % de descuento, pero AWS puede detener la tarea con un aviso de 2 minutos. Desde septiembre de 2024 Spot también funciona con Graviton (ARM64).

## 2. Qué debe cumplir la decisión

- **Negocio (RF-05, RN-11):** los sellos consultan su reporte por la API. Una caída de la API es visible para el cliente.
- **Requisito (RNF-04):** ninguna interrupción puede perder eventos F2.
- **Requisito (RNF-01):** la liquidación mensual termina en menos de 1 hora. Un job interrumpido debe poder reintentarse dentro de ese margen.
- **Costo:** el menor costo justificable (ADR-0001), con el entorno prendido solo en ventanas (ADR-0020).
- **Equipo:** las imágenes ya se construyen en Mac con Apple Silicon (ARM64 nativo). Los Dockerfile usan `python:3.12-slim`, que es multiarquitectura.

## 3. Opciones consideradas

Costo de una tarea de 0,25 vCPU y 0,5 GB prendida 730 h, en us-east-1, a precios de lista:

| Opción | A favor | En contra | USD/mes por tarea |
|---|---|---|---|
| A · Todo On-Demand x86 | Sin sorpresas; cualquier imagen sirve | La más cara; no aprovecha Graviton | ≈ 9,0 |
| B · Todo On-Demand ARM64 | ≈ 20 % menos que x86, sin interrupciones | Paga precio completo en servicios que sí toleran cortes | ≈ 7,2 |
| C · Todo Spot ARM64 | La más barata | La API puede quedar caída hasta que haya capacidad (con 1 tarea, sin respaldo) | ≈ 2–3 (variable) |
| **D · Mixta: On-Demand ARM64 para las APIs y Spot ARM64 para simulador, consumidor y Spark** | Cada servicio paga lo justo según cuánto le duele una interrupción | Dos estrategias de capacidad que mantener | API ≈ 7,2 · el resto ≈ 2–3 |
| E · ECS sobre EC2 (sin Fargate) | Más barato a gran escala | Hay que administrar instancias; no cumple el tema 9 (Fargate) | — |

Precios de lista: ARM64 a 0,03238 USD/vCPU-h y 0,00356 USD/GB-h; x86 a 0,04048 y 0,004445. Se confirman con AWS Pricing Calculator en la HU 23 (EG-32).

## 4. Decisión

**Elegimos la opción D:** todo en **ARM64 (Graviton)**, y la capacidad según el daño que hace una interrupción.

| Servicio | Capacidad | Por qué |
|---|---|---|
| API de titulares (EG-27) | **On-Demand** | La consultan los sellos (RF-05); un corte de Spot la dejaría sin servicio |
| API de contratos F4 | **On-Demand** | Spark la consulta durante la liquidación; un corte retrasaría RNF-01 |
| Consumidor F2 | **Spot** | El ACK se envía después de guardar: si AWS detiene la tarea, lo no confirmado vuelve a la cola. Probado en la EG-29 con SIGKILL y con reinicio del broker (ADR-0013) |
| Simulador F2 | **Spot** | Con publisher confirms, lo no confirmado se vuelve a publicar |
| Jobs de Spark | **Spot** | Airflow reintenta el job; la liquidación de < 1 h deja margen para un reintento |

El clúster `sonoraplay-dev` registra los dos proveedores de capacidad, `FARGATE` y `FARGATE_SPOT`. Cada servicio elige el suyo en `capacity_provider_strategy`.

## 5. Consecuencias

- **Positivas:**
  - ≈ 20 % menos en todo el cómputo por usar ARM64, y hasta 70 % menos en los tres servicios Spot.
  - La API no depende de la disponibilidad de Spot.
- **Negativas / lo que aceptamos:**
  - Las imágenes deben construirse para `linux/arm64`. En Mac es nativo. En GitHub Actions (EG-40) se usará un runner ARM o QEMU con `docker buildx`.
  - En el plan actual la API corre con **1 tarea**: un reemplazo por falla deja unos segundos sin servicio. Con `api_titulares_tareas = 2` hay respaldo, al doble de costo.
- **Riesgos y mitigación:**
  - **Spot sin capacidad:** las tareas Spot quedan pendientes. Se puede cambiar el peso a `FARGATE` sin tocar el código.
  - **HTTPS sin dominio:** el ALB solo puede terminar TLS con un certificado de ACM, y eso exige un dominio. Mientras el equipo no lo tenga, las ventanas usan HTTP en el puerto 80; el token viaja sin cifrar, así que **solo se usan datos sintéticos**. Con `certificado_acm_arn`, el puerto 80 redirige a 443 (ADR-0006). **Pendiente a coordinar con Julián:** dominio y certificado.
  - **Imágenes desde subred privada:** la tarea baja la imagen de ECR y manda logs por la instancia NAT. Los endpoints de interfaz (ecr.api, ecr.dkr, logs) evitarían la NAT, pero cuestan ≈ 7 USD/mes cada uno, más que la NAT (ADR-0010).

## 6. Cómo sabremos que funciona

En la siguiente ventana de AWS (ADR-0020), `infra/scripts/verificar-eg27.sh` comprueba los criterios 2 a 5 de la EG-27:

- la tarea usa una definición versionada (`family:N`) en subredes privadas sin IP pública;
- `GET /health` por la URL del ALB responde 200, y el target group chequea `/health`;
- al detener una tarea, ECS la reemplaza y la API vuelve a responder 200;
- los logs aparecen en `/ecs/sonoraplay/api-titulares` con retención de 7 días.

`describe-tasks` debe mostrar `cpuArchitecture = ARM64` y `capacityProviderName = FARGATE`.

## 7. Fuentes

- AWS Fargate, precios (On-Demand, Spot y ARM): https://aws.amazon.com/fargate/pricing/
- Amazon ECS, proveedores de capacidad de Fargate: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-capacity-providers.html
- Amazon ECS con Graviton en Fargate Spot (sep. 2024): https://aws.amazon.com/about-aws/whats-new/2024/09/amazon-ecs-graviton-based-spot-compute-fargate/
- Amazon ECS, health checks de contenedor y del ALB: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/healthcheck.html
- Amazon ECS, deployment circuit breaker: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html
- Elastic Load Balancing, health checks del target group: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html

---

## English — Decision summary

**Accepted (proposed October 21, 2026; approved October 22, 2026 by merging PR #24; EG-27).** All ECS Fargate workloads run on **ARM64 (Graviton)**, about 20 % cheaper than x86 at list price. Capacity follows how much an interruption hurts:

- **Fargate On-Demand** for the two APIs: the rights holder API serves the labels (RF-05), and Spark queries the contracts API during settlement.
- **Fargate Spot** (up to 70 % off) for the F2 simulator, the F2 consumer and the Spark jobs. Manual ACK, publisher confirms and Airflow retries make an interruption safe (RNF-04, RNF-01; tested in EG-29).

Without a domain there is no ACM certificate yet, so test windows serve HTTP on port 80 with synthetic data only. With `certificado_acm_arn`, port 80 redirects to 443 (ADR-0006).

**Traceability:** The Spanish sections above are the full decision record. This summary introduces no new decision.
