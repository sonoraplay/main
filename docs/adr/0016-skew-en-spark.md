# ADR-0016 · Manejo del sesgo (skew) en Spark: ajustar particiones y AQE primero; sal solo si se mide el sesgo

| Campo | Valor |
|---|---|
| Estado | **Propuesto** (evidencia parcial: ver §6) |
| Fecha | 2026-11-03 |
| Historia que lo origina | HU 30 · EG-39 |
| Responsable | Julián |
| Revisó | Pendiente |
| Referencias | RNF-01, E-13, temas 15–16, [informe](../rendimiento/eg39-informe-spark.md), ADR-0014 |

## 1. Contexto

La liquidación debe correr en menos de 1 hora (RNF-01) en una tarea pequeña de Fargate. Los artistas populares concentran muchas reproducciones, lo que puede dejar particiones desbalanceadas (sesgo) en uniones y agregaciones por pista o artista. Se midió un mes sintético sesgado de 40 000 reproducciones con cada ajuste por separado.

## 2. Qué debe cumplir la decisión

- **Requisito:** RNF-01 (< 1 h) y salida idéntica a la base (EG-39 criterio 4).
- **Costo:** una tarea de 2 vCPU / 8 GB que corre y se apaga; menos tiempo es menos costo.
- **Simplicidad:** no añadir complejidad (sal) que a la escala medida no ayuda.

## 3. Opciones consideradas (medidas a 40 000 reproducciones, `local[2]`)

| Opción | Efecto medido sobre el total | Comentario |
|---|---:|---|
| Ajustar `shuffle.partitions` al tamaño de la tarea | −19 % | Gratuita; 200 es excesivo para pocas reproducciones |
| Adaptive Query Execution | −18 % | Une particiones pequeñas y puede dividir las sesgadas; no requiere ajustar a mano |
| Caché del Silver para etapas posteriores | −22 % en el total (todo en la etapa 2) | Útil solo si otras etapas lo reutilizan en el mismo job |
| Difusión (broadcast) del catálogo | 0 % | Inofensiva con catálogo pequeño; no era el cuello |
| Sal en la clave de pista | +5 % (peor) | Multiplica el catálogo; no compensa con este sesgo |
| Poda de particiones por fecha | +4 % (sin efecto) | Medida en un rango de 10 días; el costo está en el Python por sesión, no en leer archivos |

## 4. Decisión propuesta

1. Activar **AQE** y fijar `shuffle.partitions` según el tamaño de la tarea (no el valor por defecto de 200).
2. **Difundir el catálogo** en las uniones: no cuesta y escala si crece la tabla.
3. **No usar sal por defecto.** Se adopta únicamente si, con datos reales, Spark UI muestra una tarea cuya duración o tamaño supera varias veces la mediana de su etapa (sesgo medido) y AQE no lo corrige.
4. Mantener el filtro por la columna de partición `fecha` (no cuesta), sin esperar una mejora a esta escala.
5. Cachear el Silver solo si el job ejecuta etapas posteriores que lo reutilizan.

## 5. Consecuencias

- El grueso del tiempo está en reconstruir sesiones con `applyInPandas` (≈ 76 % de la base); optimizar eso (menos Python por sesión) rendiría más que afinar uniones. Queda fuera de esta decisión.
- Los parámetros dependen del volumen: hay que repetir la medición con el volumen completo.

## 6. Pendiente de comprobar

Este ADR **no** afirma que se cumpla RNF-01. Falta: la línea base con el volumen completo del mes, la medición en una tarea de 2 vCPU / 8 GB de Fargate Spot, el estudio del sesgo con datos reales (Spark UI) y el costo por corrida. Silver (EG-35) cambiará su forma de escribir y la etapa de liquidación medida es un *proxy* de la EG-37.
