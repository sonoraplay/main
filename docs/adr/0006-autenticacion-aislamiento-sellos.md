# ADR-0006 · Autenticación de sellos con JWT HS256 y aislamiento por titular (403 antes de leer la base)

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-09 |
| Historia que lo origina | HU 12 · EG-21 |
| Responsable | Andrea |
| Revisó | Joshua — aprobado el 2026-10-13, validado en la práctica por el esqueleto de la EG-24 (PR #25) |
| Referencias | RN-11, CA-08, RF-05, RNF-02, CT-02, ADR-0001, ADR-0007, ADR-0017 |

## 1. Contexto

La API de titulares es la **única API pública** de SonoraPlay: corre en Fargate detrás del ALB, que solo acepta HTTPS ([arquitectura v1](../arquitectura/arquitectura-v1.md), flujo ①–③). Por ella cada sello, distribuidora o sociedad de gestión consulta su reporte de regalías: reproducciones válidas, participación en la bolsa, % contractual y regalía en USD por mes y país (RF-05).

RN-11 exige que un titular vea **solo sus propios datos**, y CA-08 lo convierte en prueba: con el token del sello A, pedir los datos del sello B devuelve **403**. Además, la respuesta no debe permitir averiguar si B existe: si "B no existe" diera 404 y "B existe pero no es tuyo" diera 403, cualquier sello podría enumerar a sus competidores.

Hay que decidir cómo se autentica un sello y dónde se aplica el aislamiento. El volumen es pequeño (unos 1.500 titulares en F1, decenas de consultas al día), no existe un portal de usuarios y la arquitectura ya descartó guardar sesiones en DynamoDB ("la API no guarda sesión: usa un token firmado").

## 2. Qué debe cumplir la decisión

- **Negocio:** RN-11 y CA-08: A nunca recibe filas de B; A pidiendo B → 403, con el mismo cuerpo exista o no B.
- **Negocio:** sin credencial, o con una credencial vencida o alterada → 401.
- **Requisito:** CT-02 / arquitectura principio 4: ningún secreto en el repositorio; los secretos viven en SSM Parameter Store (ADR-0017). Una credencial expuesta cuesta −15 %.
- **Requisito:** la prueba de aislamiento corre en el CI sin servicios externos (sin AWS, sin red).
- **Costo:** ningún servicio nuevo encendido 24/7; presupuesto del proyecto ajustado (ADR-0001, ADR-0020).
- **Equipo:** se implementa y se prueba dentro de un sprint, con FastAPI (ya usado en EG-20).

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · **JWT HS256 con secreto compartido** (PyJWT) | Sin estado: la API valida firma y vencimiento sin consultar la base, así el aislamiento se decide **antes** de leer datos. Una librería pequeña, pruebas 100 % locales. Un solo parámetro SecureString en SSM | Quien tiene el secreto puede **emitir** tokens, no solo validarlos: la API y el emisor comparten la misma llave. Sin revocación individual antes de `exp` | 0 (SSM estándar es gratis) |
| B · JWT RS256 (clave privada para emitir, pública para validar) | La API solo guarda la clave pública: si se filtra, no permite emitir tokens. Rotación con `kid` y JWKS | Dos llaves que generar, guardar y rotar; el emisor es el mismo equipo que opera la API, así que la separación de llaves no protege a nadie más hoy. Misma falta de revocación | 0 |
| C · API key por sello, guardada como hash en la base | Revocación inmediata (borrar la fila). Fácil de entender para el sello | Requiere tabla y DDL nuevos, y una **consulta a la base en cada petición** antes de poder decidir el 403. Con estado: se aleja del diseño sin sesión de la arquitectura. Hay que escribir a mano el hashing y la comparación en tiempo constante | 0 |
| D · Amazon Cognito (user pool + JWT RS256 emitido por AWS) | Login, MFA, revocación y rotación administrados. Estándar OIDC | Un servicio más que configurar en Terraform (EG-26) y que no se puede probar en el CI sin simularlo. Los sellos tendrían que registrarse y hacer login para una consulta mensual. Excede el alcance de 5 puntos | 0 en la capa gratuita (hasta 10.000 MAU), pero más horas del equipo |

**Dónde se aplica el aislamiento.** Se evaluó también usar *Row-Level Security* de PostgreSQL (`SET app.titular_id` por conexión). Protege incluso ante un bug en el `WHERE`, pero el 403 de CA-08 igual hay que decidirlo en la API, y RLS complica el pool de conexiones. Queda como defensa en profundidad para más adelante.

## 4. Decisión

**Elegimos la opción A (JWT HS256)** porque cumple RN-11 y CA-08 sin estado ni consultas previas a la base, sus pruebas corren completas en el CI y no añade costo ni servicios. Las ventajas de B y D (separar quien emite de quien valida, revocación administrada) no aportan mientras el único emisor sea el propio equipo; si eso cambia, se migra a B sin tocar el contrato HTTP (sección 5).

### 4.1 Token

| Claim | Valor | Validación |
|---|---|---|
| `sub` | `titular_id` (UUID, como string) | Obligatorio y debe ser un UUID válido |
| `iss` | `"sonoraplay"` | Obligatorio e igual |
| `aud` | `"api-titulares"` | Obligatorio e igual (un token emitido para otro servicio no sirve aquí) |
| `iat` | Fecha de emisión | Obligatorio |
| `exp` | Vencimiento | Obligatorio; vencido → 401 |

- Algoritmo fijado en el servidor: `algorithms=["HS256"]`. Se rechazan `alg: none` y cualquier otro algoritmo.
- Cualquier fallo → **401** con `WWW-Authenticate: Bearer`. El cuerpo no repite el error interno de PyJWT.
- El secreto sale de `API_TITULARES_JWT_SECRET`. Si falta, mide menos de 32 bytes (RFC 7518 §3.2) o es el valor de ejemplo de `.env.example`, **la app no arranca** y dice por qué. No hay valor por defecto.

### 4.2 Cómo se cumple CA-08

1. La dependencia de autenticación valida el token y obtiene `sub` (401 si falla).
2. En `GET /titulares/{titular_id}/reportes`, si `titular_id` ≠ `sub` → **403** `{"detail": "No tiene permiso para consultar este titular"}`. Esto ocurre **antes de abrir una sesión de base de datos**, así que la respuesta es idéntica (mismo código, mismo cuerpo) exista o no el titular pedido, y no hay diferencia de tiempo que medir.
3. La consulta siempre filtra `WHERE titular_id = :sub`; el `titular_id` del path solo se usa para compararlo.
4. `GET /me/reportes` toma el titular directamente del token; es la forma recomendada para los sellos, porque no hay ningún identificador que manipular.
5. Un titular sin filas recibe 200 con una lista vacía: para su propio `sub`, no hay nada que ocultar.

### 4.3 Emisión, rotación y SSM

- **Emisión:** no hay portal. Un integrante del equipo con acceso a SSM emite el token con `python -m sonoraplay.api_titulares.tokens --titular <uuid> --horas N` y lo entrega al sello por un canal privado. El script solo imprime el token y no lo guarda.
- **Desarrollo:** cada persona genera un secreto aleatorio local en su `.env` (que está en `.gitignore`); las pruebas usan un secreto de prueba con `monkeypatch`.
- **AWS (ADR-0017, EG-40):** parámetro SecureString `/sonoraplay/api-titulares/jwt-secret`. La definición de tarea de ECS lo inyecta como variable de entorno con `secrets.valueFrom`; el rol de ejecución solo tiene `ssm:GetParameters` sobre ese ARN. El valor nunca pasa por Terraform ni por el repositorio.
- **Rotación:** se genera un secreto nuevo, se actualiza el parámetro y se fuerza un nuevo despliegue del servicio. Todos los tokens anteriores dejan de valer al instante: se vuelven a emitir. Para una rotación sin corte, el paso siguiente es aceptar dos secretos con `kid` durante la transición (no se implementa en EG-21).

## 5. Consecuencias

- **Positivas:** aislamiento verificable con pruebas en el CI; ninguna consulta a la base para rechazar a un intruso; sin servicios nuevos; `/docs` muestra el botón *Authorize* (esquema `HTTPBearer`).
- **Negativas / lo que aceptamos:**
  - **No hay revocación individual:** un token filtrado vale hasta su `exp`. Mitigación: vencimientos cortos y rotación del secreto (que invalida todos los tokens).
  - El secreto que valida también permite **emitir**: si se filtra, se pueden falsificar tokens de cualquier sello. Por eso vive solo en SSM y en el `.env` local de cada persona.
  - Los tokens no tienen roles ni alcances: un token equivale a "el titular `sub` lee sus reportes". Una cuenta de administración que lea varios titulares necesitaría otro diseño.
- **Riesgos y mitigación:**
  - *Secreto commiteado por error* → gitleaks en pre-commit y en el CI; `.env.example` solo trae un valor claramente falso que la app rechaza.
  - *Un bug en la consulta que olvide el filtro por titular* → pruebas de CA-08 que comparan filas devueltas contra los datos de B; como mejora, rol de base de datos de solo lectura para la API y, más adelante, RLS.
  - *Necesidad futura de emisores externos* → migrar a RS256 (opción B) o Cognito (opción D); el contrato HTTP (`Authorization: Bearer`, 401/403) no cambia.

## 6. Cómo sabremos que funciona

- `tests/api_titulares/test_aislamiento_ca08.py` (corre en el job `test` del CI):
  - el token de A pidiendo B → 403;
  - el token de A pidiendo un UUID inexistente → 403 con **el mismo cuerpo exacto**;
  - ninguna de las dos respuestas contiene datos de B.
- `tests/api_titulares/test_auth.py`: sin encabezado, token vencido, firma inválida, `aud` o `iss` incorrectos, `alg` distinto y `sub` que no es UUID → 401 con `WWW-Authenticate: Bearer`.
- La app no arranca sin `API_TITULARES_JWT_SECRET`, con uno corto o con el de ejemplo.
- `git grep API_TITULARES_JWT_SECRET` solo encuentra lecturas desde el entorno y el valor falso de `.env.example`; gitleaks no reporta hallazgos.

## 7. Fuentes

- Enunciado del proyecto: RN-11, CA-08, RF-05, CT-02.
- RFC 7519, JSON Web Token: https://www.rfc-editor.org/rfc/rfc7519
- RFC 7518 §3.2, HMAC con SHA-2 (longitud mínima de la clave): https://www.rfc-editor.org/rfc/rfc7518#section-3.2
- RFC 6750 §3, encabezado `WWW-Authenticate: Bearer`: https://www.rfc-editor.org/rfc/rfc6750#section-3
- PyJWT, validación de claims: https://pyjwt.readthedocs.io/en/stable/usage.html
- FastAPI, seguridad con `HTTPBearer`: https://fastapi.tiangolo.com/reference/security/
- Amazon ECS, secretos desde SSM Parameter Store: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-ssm-paramstore.html
- Amazon Cognito, precios: https://aws.amazon.com/cognito/pricing/


---

## English — Decision summary

**Accepted (October 9, 2026; EG-21).** Rights-holder API authentication uses HS256 JWT with required `sub`, `iss`, `aud`, `iat`, and `exp`. Invalid tokens produce 401. A path rights-holder ID that differs from the token subject produces **403 before any database query**, preventing cross-holder disclosure. A strong non-default signing secret is required at startup. The design favors low cost and local testability; production deployment and credential distribution require separate verification.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
