# Atribución de reproducciones offline (RN-04 · EG-22)

Cómo una reproducción reconstruida desde F2 se asigna a un mes de liquidación. Complementa el paso 3 de [eventos-f2.md](eventos-f2.md#de-eventos-a-reproducciones) (corrección del reloj) y el cierre append-only de [ADR-0007](../adr/0007-cierre-mes-ajustes-reliquidacion.md).

- Código: `src/sonoraplay/reglas/atribucion.py` (funciones puras: sin archivos, base de datos ni reloj del sistema).
- Configuración: `AtribucionOfflineConfig` en `src/sonoraplay/config.py` (corte día 2 a las 23:59 UTC, tolerancia del reloj de 60 s).
- Pruebas: `tests/reglas/test_atribucion.py`, `tests/reglas/test_reloj_sesion.py` y `tests/reglas/test_sesiones.py`.
- Todo en UTC (ADR-0002). Un mes se representa con su primer día.

## Flujo

```
eventos F2 ─► reconstruir()                       ─► ReproduccionF2 ─► atribuir_reproduccion()
              ├─ deduplicar por event_id               inicio (corregido)    mes_reproduccion
              ├─ corregir_reloj_sesion()  (paso 3)     is_offline            mes_liquidacion
              └─ ordenar y armar tramos                sincronizado          normal | ajuste
```

```python
for rep in reconstruir(eventos, cfg_atribucion):
    r = atribuir_reproduccion(rep.inicio, rep.sincronizado, rep.is_offline, cfg_atribucion)
```

## 1. Corrección del reloj

### Por sesión: `corregir_reloj_sesion(eventos, cfg)`

Es la que usa `reconstruir()` antes de ordenar.

1. Si algún evento de la sesión es offline, la sesión **no se toca**: su `server_ts` es la sincronización, que puede llegar días después de la escucha, y usarlo movería la reproducción de mes.
2. Desfase = **mediana** de `server_ts − device_ts` de los eventos. La mediana evita que un evento atípico (un reintento muy tardío) arrastre a los demás.
3. Si `|desfase|` supera `tolerancia_reloj_segundos`, se suma **el mismo desfase** al `device_ts` de **todos** los eventos de la sesión. Corregir evento por evento distorsionaría la duración de los tramos (RN-01).

Ejemplo, `schemas/ejemplos/defectos/reloj_desfasado.json` (reloj 3 h atrasado):

| Evento | `device_ts` | `server_ts` | `device_ts` corregido |
|---|---|---|---|
| `start` | 11:00:00.000Z | 14:00:00.250Z | 14:00:00.250Z |
| `end` | 11:03:30.760Z | 14:03:31.010Z | 14:03:31.010Z |

El tramo mide 210 760 ms antes y después de la corrección.

### Por evento: `corregir_reloj_online(dispositivo, servidor, cfg, *, es_offline)`

Variante para un solo evento. Con `es_offline=True` devuelve el `device_ts` sin cambios. El parámetro es obligatorio a propósito, para que nadie corrija un evento offline por descuido.

## 2. Mes de liquidación: `atribuir_reproduccion(...)`

Recibe la hora de la escucha (ya corregida), la de sincronización, si es offline y la configuración. Devuelve `ResultadoAtribucion(mes_reproduccion, mes_liquidacion, tipo)`.

**Corte de un mes M:** día 2 de M a las 23:59 UTC, **incluido todo el minuto** (hasta 23:59:59.999).

| Caso | Mes de liquidación | Tipo |
|---|---|---|
| Online, o sincronizada en el mismo mes de la escucha | mes de la escucha | `normal` |
| Offline sincronizada antes o durante el corte del mes siguiente | mes de la escucha | `normal` |
| Offline sincronizada después de ese corte | **la primera liquidación todavía abierta** (abajo) | `ajuste` |

**Primera liquidación abierta** para un ajuste sincronizado en el mes S:

- si la sincronización es anterior o igual al corte de S (el día 2 a las 23:59 de S), es **S − 1**: la liquidación del mes anterior todavía no se ha cerrado;
- si no, es **S**;
- nunca antes del mes siguiente al de la escucha.

Una liquidación del mes M se cierra con el corte del día 2 de M + 1 y se paga el día 3.

### Ejemplos (escucha del 28 de septiembre)

| Sincronización | Mes de liquidación | Por qué |
|---|---|---|
| 2-oct 23:59:59 | septiembre (`normal`) | dentro del corte de septiembre |
| 3-oct 00:00 | octubre (`ajuste`) | septiembre ya cerró |
| 4-oct | octubre (`ajuste`) | octubre está abierta |
| **1-nov** | **octubre** (`ajuste`) | octubre se cierra el 2-nov a las 23:59: todavía está abierta |
| 3-nov 00:00 | noviembre (`ajuste`) | octubre ya cerró |

Cambio de año: una escucha del 28 de diciembre sincronizada el 1 de febrero va a **enero**; una del 20 de noviembre sincronizada el 2 de enero va a **diciembre**.

Un ajuste se paga con la bolsa del mes en que se liquida, no con la de su mes real ([ADR-0007](../adr/0007-cierre-mes-ajustes-reliquidacion.md), sección 5). La regla no escribe ni reabre ninguna liquidación: solo dice a cuál pertenece la reproducción.

## Seguimientos

- La estrategia de corrección del reloj de las sesiones **offline** sigue abierta: hoy se confía en su `device_ts`. Si un dispositivo offline tiene el reloj mal, la escucha puede caer en otro mes; se puede detectar comparando con el `device_ts` y el `server_ts` de los eventos online del mismo dispositivo.


---

## English — Offline playback attribution (RN-04 · EG-22)

This document specifies how an F2 playback is assigned to a settlement month. It complements the F2 session clock correction and the append-only closing policy in ADR-0007. **Code:** `src/sonoraplay/reglas/atribucion.py`; **configuration:** `AtribucionOfflineConfig`; **tests:** `tests/reglas/test_atribucion.py`, `test_reloj_sesion.py`, and `test_sesiones.py`. All dates and cutoffs are in UTC (ADR-0002).

### Session clock correction

`corregir_reloj_sesion` uses the median of `server_ts - device_ts` across the session. When the absolute offset exceeds the configured 60-second tolerance, the **same offset** is added to all session event timestamps, preserving continuous listening durations. Sessions containing any offline event are **not corrected**: their server timestamps may represent a later synchronization rather than playback time. `corregir_reloj_online` is the single-event variant; callers must explicitly pass `es_offline`.

### Settlement month and cutoff

`atribuir_reproduccion` returns `ResultadoAtribucion(mes_reproduccion, mes_liquidacion, tipo)`. Settlement month **M** closes on day 2 of **M+1** at 23:59 UTC, including the entire final minute.

| Situation | Settlement month | Type |
|---|---|---|
| Online, or synchronized in playback month | Playback month | `normal` |
| Offline synchronized by the next month's day-2 cutoff | Playback month | `normal` |
| Offline synchronized after that cutoff | First settlement month still open | `ajuste` |

For a late adjustment synchronized in month **S**, the first open settlement is **S−1** if synchronization is within S's day-2 cutoff; otherwise it is **S**. It is never earlier than the month following playback.

**September 28 playback examples:** synchronized October 2 at 23:59:59 → September (`normal`); October 3 or 4 → October (`ajuste`); November 1 → October (`ajuste`, still open); November 3 → November (`ajuste`). A December 28 playback synchronized February 1 is attributed to January.

A late adjustment is paid from the revenue pool of the **settlement month**, not the original playback month. This pure function does not reopen or modify a published settlement.

### Open limitation

Offline sessions currently trust the device timestamp. If the offline device clock is wrong, playback may be attributed to the wrong month; future detection may compare online events from the same device. This is an identified limitation, not a resolved behavior.
