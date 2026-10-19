# ADR-0003 · Una fila por `track_id` en el catálogo F1, con género principal y tabla puente de géneros

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-02 |
| Historia que lo origina | HU 03 · EG-12 |
| Responsable | María Clara |
| Revisó | Aprobado en el PR #7 (fusionado el 2026-10-02) |
| Referencias | F1, RN-03, Q9 de EG-11 ([ambiguedades-rn.md](../analisis/ambiguedades-rn.md)) |

## 1. Contexto

F1 es el catálogo de pistas: un CSV público de Spotify con 114.000 filas y 21 columnas. La exploración ([notebooks/01_exploracion_f1.ipynb](../../notebooks/01_exploracion_f1.ipynb)) mostró que **una fila no es una pista**, sino una pista dentro de un género:

| Hecho | Cifra |
|---|---|
| Filas | 114.000 |
| `track_id` únicos | 89.741 |
| `track_id` que aparecen 2 o más veces | 16.641 (ocupan 40.900 filas) |
| Filas sobrantes | 24.259 |
| … de ellas, duplicados exactos (mismo `track_id` y mismo género) | 450 |
| Máximo de repeticiones de una pista | 9 géneros |
| Columnas que cambian entre filas del mismo `track_id` | solo `popularity`, en 720 pistas (diferencia máxima: 44 puntos) |
| Repetidas con empate en la popularidad máxima | 15.767 de 16.641 |
| Pares (nombre, artistas) con 2 o más `track_id` distintos | 4.657 pares, 13.054 pistas (p. ej. *Rockin' Around The Christmas Tree* de Brenda Lee: 45 `track_id`) |
| Filas inválidas | 1 (fila 65900: sin `artists`, `album_name` ni `track_name`, y `duration_ms = 0`) |

Si el catálogo se usa tal cual, una misma pista cuenta varias veces: los joins con las reproducciones de F2 (que llegan con `track_id`) multiplican las filas y las regalías se duplican. La pregunta Q9 de EG-11 fijó el supuesto «una fila canónica por `track_id`»; este ADR decide cómo.

## 2. Qué debe cumplir la decisión

- **Negocio:** cada reproducción de F2 debe unirse con **una sola** pista y, por ella, con **un solo** titular; si no, las regalías se pagan dos veces.
- **Negocio (RN-03):** la señal 2 de granja cuenta oyentes por **artista**; el artista de cada pista tiene que ser estable y único.
- **Requisito:** el catálogo limpio es reproducible (semilla 42) y cada pista tiene exactamente un `titular_id` (criterios 2, 3 y 5 de EG-12).
- **Datos:** no perder información útil: los géneros adicionales sirven para reportes y para el dashboard.
- **Costo:** ninguno; la decisión solo afecta código y datos.

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · Dejar los duplicados como pistas distintas | Cero trabajo; conserva el CSV tal cual | `track_id` deja de ser clave; el join con F2 multiplica las reproducciones (hasta ×9) y duplica regalías; incumple el criterio 1 de EG-12 | 0 |
| B · Una fila por `track_id` con género principal + tabla puente `track_generos` | `track_id` es clave primaria; joins 1 a 1 con F2; conserva todos los géneros en la tabla puente; regla simple y determinista | Hay que elegir un género principal, y en 15.767 casos se decide por desempate alfabético (arbitrario pero reproducible) | 0 |
| C · Unificar también por (nombre, artistas) | Catálogo más compacto (8.397 filas menos que B) | Las reproducciones de F2 llegan con `track_id`: habría que mantener una tabla de equivalencias; mezcla versiones distintas (remasterizaciones, en vivo, álbum frente a sencillo) que pueden tener otro titular o duración; el criterio de «misma canción» es frágil | 0 |

## 4. Decisión

**Elegimos la opción B** porque deja `track_id` como clave única para unir con F2 (cada reproducción → una pista → un titular) y no pierde los géneros adicionales. **Descartamos C** porque F2 identifica las pistas por `track_id`, no por nombre: unir pistas con distinto `track_id` obligaría a traducir identificadores y podría mezclar grabaciones con titulares distintos.

Reglas (en `src/sonoraplay/catalogo/limpiar_f1.py`):

1. Se elimina la columna índice sobrante (`Unnamed: 0`), se recortan espacios (8 valores `"Terra "`) y se fijan los tipos.
2. Se descartan las filas sin `track_id`, `artists` o `track_name`, o con `duration_ms <= 0`.
3. Se deja una fila por `track_id`. `genero_principal` = género de la fila con mayor `popularity`; si hay empate, el primero en orden alfabético. Las demás columnas se toman de esa misma fila.
4. `track_generos (track_id, genero)` guarda todos los géneros de cada pista, sin repetir.
5. Las pistas con distinto `track_id` **no** se unen aunque compartan nombre y artista.
6. `artista_principal` = texto de `artists` antes del primer `;`. Cada artista principal recibe un único titular (`asignar_titulares.py`), así que todas sus pistas comparten titular.

### Resultado sobre el F1 completo

| Paso | Filas |
|---|---|
| Filas leídas | 114.000 |
| Descartadas (1 sin `artists`/`track_name` y con duración 0) | 1 |
| Fusionadas (450 duplicados exactos + 23.809 géneros adicionales) | 24.259 |
| **Pistas finales (`track_id` únicos)** | **89.740** |
| Pistas con 2 o más géneros | 16.299 |
| Filas de `track_generos` | 113.549 |
| Artistas principales | 17.648 |
| Titulares | 1.500 (todos con al menos un artista) |
| Titular más grande | 2.118 artistas y 11.405 pistas (mediana: 4 artistas) |

Los titulares se reparten con pesos tipo Zipf (1/k): los 10 titulares más grandes concentran el 35 % de las pistas. Ese sesgo es intencional y alimenta el trabajo de skew en Spark (tema 15, ADR-0016).

## 5. Consecuencias

- **Positivas:** `track_id` es clave primaria del catálogo y de la futura tabla de pistas; los joins con F2 no multiplican filas; el resultado es idéntico en cada corrida (semilla 42, verificado con `assert_frame_equal`).
- **Negativas / lo que aceptamos:** el género principal es arbitrario en 15.767 pistas (desempate alfabético). Solo afecta reportes por género, no el dinero. Las 13.054 pistas homónimas quedan como pistas distintas, y en los reportes pueden verse como «la misma canción repetida».
- **Sesgo de `genero_principal`:** por los 15.767 empates de popularidad, `genero_principal` queda sesgado hacia el orden alfabético (por ejemplo, entre `alt-rock` y `rock` gana siempre `alt-rock`). Por eso **los análisis por género deben usar la tabla puente `track_generos`, no `genero_principal`**: en particular el modelo dimensional (EG-31) y los tableros de Power BI (EG-44). `genero_principal` sirve solo como etiqueta de visualización.
- **Popularidad:** en las 720 pistas cuya popularidad cambia entre filas, el catálogo conserva la de la fila elegida, que es la máxima. Las popularidades menores se descartan.
- **Riesgos y mitigación:** si F2 trajera un `track_id` que no está en el catálogo (por ejemplo, el de la fila descartada), la reproducción no tendría titular; la validación de F2 (EG-15) debe marcarla en vez de perderla en silencio. Si el docente responde distinto a Q9, este ADR pasa a *Reemplazado*.

## 6. Cómo sabremos que funciona

Pruebas de `tests/catalogo/test_catalogo_f1.py` sobre `data/samples/f1_muestra.csv` (200 filas con los casos difíciles a propósito):

- `track_id` único tras unificar (criterio 1).
- Género principal correcto, con empate y sin él; `track_generos` conserva todos los géneros.
- La fila inválida se descarta; las dos pistas homónimas con distinto `track_id` siguen separadas.
- Cada pista tiene un titular y todas las de un artista comparten titular (criterios 2 y 5); 1.500 titulares únicos y ninguno vacío.
- Dos ejecuciones dan DataFrames idénticos (criterio 3).

## 7. Fuentes

- Dataset F1 (*Spotify Tracks Dataset*, Kaggle): https://www.kaggle.com/datasets/maharshipandya/-spotify-tracks-dataset
- pandas — `DataFrame.drop_duplicates` y `sort_values(kind="mergesort")` (orden estable): https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.drop_duplicates.html
- Python — `uuid.uuid5` (identificadores deterministas): https://docs.python.org/3/library/uuid.html#uuid.uuid5
- Python — `random.Random` (generador con semilla): https://docs.python.org/3/library/random.html


---

## English — Decision summary

**Accepted (October 2, 2026; EG-12).** Keep exactly one catalog row per `track_id`; choose its primary genre from the row with highest popularity (alphabetical tie-breaker), while preserving all distinct genres in the `track_generos` bridge. Discard invalid catalog rows and do **not** merge different track IDs merely because names and artists match. `artista_principal` is the text before the first semicolon in `artists`; rights-holder assignment is based on that value.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
