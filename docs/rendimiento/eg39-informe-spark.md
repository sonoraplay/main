---
title: "EG-39 · Informe de rendimiento de Spark (E-13)"
---

# EG-39 · Informe de rendimiento de Spark (entregable E-13, **parcial**)

> **Estado: medición real, pero parcial.** Se midió el job Silver y una etapa de liquidación *proxy* con un mes sintético de **40 000 reproducciones** (≈ 80 000 eventos), en `local[2]` con 6 GB, PySpark 4.0.1. Eso **no es** el volumen completo del mes ni una tarea de Fargate, y no cumple por sí solo el criterio de < 1 h. Lo que sí es sólido: el efecto *relativo* de cada ajuste a esta escala, con resultado idéntico verificado.

## Cómo se midió

- **Arnés:** `src/sonoraplay/spark/medicion/` (`generar`, `medir`, `informe`). El generador crea un mes con popularidad sesgada (200 artistas, exponente 3,0), 1 % de reintentos y 0,5 % de pistas fuera del catálogo; semilla 42.
- **Una variante cambia una sola cosa** respecto de la línea base (AQE apagado, sin difusión, 200 particiones de shuffle). Cada variante corrió **2 repeticiones** y el orden de ejecución fue **aleatorio** (semilla 7: `sal, cache, difusion, base, aqe, poda, particiones`) para no favorecer a ninguna. Las dos repeticiones de cada variante coinciden en menos de 1 %.
- **Resultado idéntico (criterio 4):** cada corrida calcula una huella independiente del orden del Silver y de la liquidación; las 7 variantes dieron la misma que la base (`problemas: []`).
- **Dos etapas:** *Silver* (leer Bronze, reconstruir sesiones, reglas, escribir Parquet) y *liquidación proxy* (unir las pagables con el catálogo y agrupar por titular y país). La liquidación proxy se sustituirá por el job de la EG-37 cuando se mida contra el Silver real.

## Resultados (medianas, segundos)

| Variante | Qué cambia | Silver | Liquidación | Total | vs base |
|---|---|---:|---:|---:|---:|
| `base` | AQE off, 200 particiones, sin difusión | 245,4 | 78,5 | **323,9** | — |
| `particiones` | `shuffle.partitions` = 8 | 196,7 | 65,5 | 262,3 | **−19 %** |
| `aqe` | Adaptive Query Execution | 199,5 | 66,2 | 265,7 | **−18 %** |
| `cache` | Silver en memoria para la etapa siguiente | 249,4 | 4,2 | 253,5 | **−22 %** (solo la etapa 2) |
| `difusion` | Catálogo difundido (broadcast) | 245,3 | 78,6 | 323,9 | 0 % |
| `sal` | Sal (16 cubetas) en la unión por pista | 255,5 | 85,6 | 341,0 | +5 % |
| `poda` | Poda de particiones por `fecha` (corrida aparte, rango de 10 días) | 115,3 | 34,7 | 150,0 | +4 % (vs 144,5 s de la base en esa corrida) |

La fila `poda` sale de una corrida aparte (`--hasta 2026-09-10`, solo `base` y `poda`), porque el filtro de fecha solo tiene sentido si se procesa un rango; en la corrida principal no se pasó `--hasta` y por eso `poda` era idéntica a `base`. En ese rango (días 1 a 10, 13 113 reproducciones) la poda no ayudó: 150,0 s frente a 144,5 s de la base, con la misma salida. A esta escala el costo no está en leer archivos sino en el Python por sesión. No se concluye que la poda sea inútil con el mes completo y archivos más grandes.

## Lectura

1. **La etapa Silver domina:** ≈ 76 % del tiempo de la base (245 de 324 s). Reconstruir sesiones con `applyInPandas` ejecuta Python por sesión; ahí está el costo.
2. **El mayor beneficio viene de no usar 200 particiones de shuffle** con un volumen chico: `particiones` (−19 %) y `aqe` (−18 %, que las une solo) atacan lo mismo y no se suman entre sí. Con 4 núcleos de trabajo, 200 particiones son casi todas diminutas y cada una paga arranque de Python.
3. **`cache` no acelera Silver** (249 vs 245 s, dentro del ruido y con el costo de materializar); su ganancia es entera en la etapa 2 (78,5 → 4,2 s) porque reutiliza el Silver ya calculado. Solo vale si hay etapas posteriores que lo reutilicen en el mismo job.
4. **`difusion` no cambia nada** a esta escala (catálogo de 10 000 pistas): la unión no es el cuello de botella.
5. **`sal` empeora (+5 %)**: con 200 artistas y exponente 3,0 el sesgo no basta para que repartir la clave compense el costo de multiplicar el catálogo por 16. No se descarta con datos reales más sesgados.
6. **Rendimiento observado:** la base procesó 40 000 reproducciones en 324 s (≈ 123 reproducciones/s de extremo a extremo en `local[2]`). No se extrapola al mes completo: el volumen real no está definido en el repositorio, y el comportamiento no tiene por qué ser lineal.


## Medición a 400 000 reproducciones (línea base)

Segunda medición, **10 veces mayor**: un mes sintético de **400 000 reproducciones** (≈ 800 000 eventos, 40 000 usuarios, mismo generador y semilla 42), variante `base`, **1 repetición**, `local[2]` con 6 GB, PySpark 4.0.1, en una máquina de 4 vCPU. Resultado: `res_base.json`.

| Etapa | Segundos |
|---|---:|
| Silver | 1 893,4 |
| Liquidación (proxy) | 623,9 |
| **Total** | **2 517,3 (≈ 42 min)** |

- **Escala mejor que lineal:** 10 veces más datos costaron 7,8 veces más tiempo (324 s con 40 000). Rendimiento de extremo a extremo: ≈ 159 reproducciones/s (antes 123).
- **Capacidad en este tamaño de tarea:** a ese ritmo, 2 núcleos procesan ≈ **570 000 reproducciones por hora**. Un mes de hasta ese volumen cabría en la meta de < 1 h (RNF-01); uno mayor no, salvo con los ajustes de arriba (AQE o menos particiones, ≈ −18 %), que **no** se volvieron a medir a esta escala.
- **No se midieron más variantes a esta escala.** La corrida de `aqe` falló al arrancar por un error de uso mío (el arnés exige incluir `base` en `--variantes`) y no se repitió. Es una sola repetición: sin varianza.

### Costo por corrida (cota superior, Fargate bajo demanda)

Precios de la lista oficial de AWS (us-east-1, ARM): **0,03238 USD por vCPU-hora y 0,00356 USD por GB-hora**. Una tarea de 2 vCPU y 8 GB cuesta **0,0932 USD/hora**. Fargate Spot no aparece en la lista de precios, así que esto es una cota superior: Spot sería menor.

| Concepto | Cálculo | USD |
|---|---|---:|
| Una corrida completa del mes (Silver + liquidación) | 0,699 h × 0,0932 | **0,065** |
| Silver diario durante un mes (30 corridas, cada una reconstruye el mes hasta la fecha, volumen medio = mitad del mes) | 30 × 0,5 × 0,526 h × 0,0932 | ≈ 0,74 |
| Liquidación mensual (1 corrida) | 0,173 h × 0,0932 | ≈ 0,016 |
| **Total aproximado del mes** | | **≈ 0,75** |

Estos costos suponen un mes de 400 000 reproducciones y escala lineal dentro del mes; el volumen real del proyecto no está definido en el repositorio. Es un orden de magnitud, no un presupuesto.

## Lo que NO está hecho (criterios de la EG-39)

| Criterio | Estado |
|---|---|
| 1 · Línea base con el volumen completo del mes | 🟡 400 000 reproducciones (42 min en `local[2]`); el volumen "completo" real no está definido en el repositorio |
| 2 · Impacto individual de cada ajuste | ✅ a esta escala; falta repetirlo con más volumen |
| 3 · Liquidación completa < 1 h en 2 vCPU / 8 GB de Fargate Spot | 🟡 42 min con 400 000 reproducciones en `local[2]` (≈ 570 000/h); **no** medido en Fargate |
| 4 · Salida idéntica a la línea base | ✅ Verificado por huella en las 7 variantes |
| 5 · Informe con Spark UI y costo por corrida; ADR-0016 | 🟡 Esta tabla y el ADR-0016 (*Propuesto*). Los registros de Spark UI (13 MB) se guardaron en la máquina de la medición y **no** están en el repositorio. El costo por corrida está calculado arriba con precios oficiales de Fargate (cota superior bajo demanda; Spot no está en la lista) |

Además, la etapa de liquidación es un *proxy* y Silver (EG-35, PR #38) sigue en borrador y cambiará su forma de escribir (reconstruir el mes hasta la fecha), lo que modificará lo que hay que medir.

## Cómo repetirlo

```bash
uv run --with pyspark==4.0.1 python -m sonoraplay.spark.medicion generar --destino /tmp/eg39 --reproducciones 40000 --usuarios 4000
uv run --with pyspark==4.0.1 python -m sonoraplay.spark.medicion medir --datos /tmp/eg39 --salida /tmp/eg39/res.json --repeticiones 2 --orden-aleatorio 7 --evento-log /tmp/eg39/historial
uv run --with pyspark==4.0.1 python -m sonoraplay.spark.medicion informe /tmp/eg39/res.json --precio-vcpu-h <USD> --precio-gb-h <USD>
```
