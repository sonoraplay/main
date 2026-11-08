# EG-36 — Spark fraud detection / Detección de fraude en Spark

## English — implementation and acceptance status

**Branch:** feature/EG-36-spark-fraud (based on develop). **Not merged.**

**Source of truth:** RN-03 / HU09, EG-11 decisions Q2/Q3/Q4, ADR-0002 and ADR-0005, and the existing pure functions in sonoraplay.reglas.fraude.

**Processing order:** verified Bronze → Silver (RN-01, RN-02, RN-04) → EG-36 Spark fraud evaluation → eligible Gold rows → F3 billing country and plan → F1 rights holder → F4 contract percentage → RN-05–RN-10 allocation → RDS/Gold publication. The production Gold CLI now evaluates fraud before calling liquidar. No changes were made to Silver's output contract.

**Signals:** (1) more than 20 listened hours in any rolling 24-hour window, computed using the accepted pure Python overlap algorithm per distributed account/month group; (2) more than 70% of monthly plays to one artist with fewer than 1,000 distinct monthly listeners; (3) a device shared by more than five accounts in the month. Thresholds are strict and configurable via ReglasFraudeConfig.

**Monthly treatment:** signals use the UTC playback month; flagged accounts' plays are held for the entire relevant settlement month, including offline plays. The original Silver records remain unchanged. Gold must only use pagable_gold, and its reconciliation compares the eligible set rather than all RN-01/RN-02-valid plays. No held play may enter a rights-holder allocation.

**F1 mapping:** the artist is the existing canonical artista_principal in catalogo_f1.parquet; it is intentionally separate from titular_id, which determines royalty ownership. Missing, null, blank or duplicated artist mappings fail the settlement rather than silently paying potentially fraudulent plays.

**Compatibility:** existing EG-37 unit callers of liquidar retain the legacy path unless they explicitly request fraude_verificado=True. This is for backwards compatibility only; the production CLI sets it to True. Do not use the legacy path for real settlement.

**Acceptance evidence still required:** execute tests/spark/test_fraude_eg36.py with PySpark 4.0.1 and the existing Spark suite, verify a real F1 Parquet read, reconcile withheld play IDs against published Gold/RDS, measure retained USD under the actual country/component pool, run the full monthly DAG in AWS, and record CI URLs and logs. CA-10 detection ≥95% and false positives <2% require labelled EG-51 simulator data and belong to EG-43. These metrics are not asserted here.

**Risk / open point:** the accepted ADR defines signals per UTC playback month and exclusion per settlement month. Offline events with playback months outside the supplied Silver snapshot must be included for a complete account-level evaluation. Do not claim acceptance until the source window is verified. Grouped pandas evaluation also needs a volume/performance test.

## Español — implementación y estado de aceptación

**Rama:** feature/EG-36-spark-fraud (nace de develop). **Sin fusionar.**

**Fuentes:** RN-03 / HU09, decisiones EG-11 Q2/Q3/Q4, ADR-0002, ADR-0005 y las funciones puras existentes en sonoraplay.reglas.fraude.

**Orden:** Bronze verificado → Silver (RN-01, RN-02, RN-04) → evaluación Spark EG-36 → registros elegibles para Gold → país/plan F3 → titular F1 → contrato F4 → reparto RN-05–RN-10 → publicación en RDS/Gold. El CLI productivo de Gold ahora evalúa fraude antes de liquidar. No se modificó el contrato de salida de Silver.

**Señales:** más de 20 horas en una ventana móvil de 24 h; más del 70% de reproducciones mensuales hacia un artista con menos de 1.000 oyentes distintos; o un dispositivo usado por más de cinco cuentas. Los límites exactos no disparan la señal.

**Exclusión:** la detección utiliza el mes UTC de reproducción y retiene todo el mes de liquidación de la cuenta afectada, incluidos eventos offline. Silver conserva las reproducciones originales. Gold utiliza pagable_gold y su conciliación solo compara reproducciones realmente elegibles. Las retenidas no participan en el reparto.

**Catálogo:** artista_principal identifica al artista de la señal de concentración; titular_id identifica al beneficiario económico. No son intercambiables. Si falta la correspondencia del artista, el cálculo falla de forma segura.

**Compatibilidad:** se conserva el modo antiguo de liquidar para las pruebas existentes de EG-37; el CLI productivo exige fraude_verificado=True. No debe utilizarse el modo antiguo para una liquidación real.

**Pendiente para aceptar:** ejecutar la suite Spark, leer F1 Parquet real, conciliar play_id retenidos con Gold/RDS, medir dinero retenido con las bolsas reales, probar el DAG mensual en AWS y conservar evidencia CI. CA-10 (≥95% de detección, <2% falsos positivos) requiere etiquetas del simulador EG-51 y se valida en EG-43. Todavía no se afirma cumplimiento.

**Riesgo:** los eventos offline pueden exigir una ventana Silver más amplia para evaluar todos los meses UTC de reproducción. También falta medir memoria y duración de los grupos pandas.
