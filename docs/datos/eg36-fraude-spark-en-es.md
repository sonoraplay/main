# EG-36 — Spark fraud detection / Detección de fraude en Spark

## English — implementation and acceptance status

**Branch:** feature/EG-36-spark-fraud (based on develop). **Not merged.**

**Source of truth:** RN-03 / HU09, EG-11 decisions Q2/Q3/Q4, ADR-0002 and ADR-0005, and the existing pure functions in sonoraplay.reglas.fraude.

**Processing order:** verified Bronze → Silver (RN-01, RN-02, RN-04) → EG-36 Spark fraud evaluation → eligible Gold rows → F3 billing country and plan → F1 rights holder → F4 contract percentage → RN-05–RN-10 allocation → RDS/Gold publication. The production Gold CLI now evaluates fraud before calling liquidar. No changes were made to Silver's output contract.

**Signals:** (1) more than 20 listened hours in any rolling 24-hour window, computed using the accepted pure Python overlap algorithm per distributed account/month group; (2) more than 70% of monthly plays to one artist with fewer than 1,000 distinct monthly listeners; (3) a device shared by more than five accounts in the month. Thresholds are strict and configurable via ReglasFraudeConfig.

**Monthly treatment:** signals use the UTC playback month; flagged accounts' plays are held for the entire relevant settlement month, including offline plays. The original Silver records remain unchanged. Gold must only use pagable_gold, and its reconciliation compares the eligible set rather than all RN-01/RN-02-valid plays. No held play may enter a rights-holder allocation.

**F1 mapping:** the artist is the existing canonical artista_principal in catalogo_f1.parquet; it is intentionally separate from titular_id, which determines royalty ownership. Missing, null, blank or duplicated artist mappings fail the settlement rather than silently paying potentially fraudulent plays.

**Compatibility:** existing EG-37 unit callers of liquidar retain the legacy path unless they explicitly request fraude_verificado=True. This is for backwards compatibility only; the production CLI sets it to True. Do not use the legacy path for real settlement.

**Acceptance evidence still required:** execute tests/spark/test_fraude_eg36.py with PySpark 4.0.1 and the existing Spark suite, verify a real F1 Parquet read, reconcile withheld play IDs against published Gold/RDS, measure retained USD under the actual country/component pool, run the full monthly DAG in AWS, and record CI URLs and logs. CA-10 detection ≥95% and false positives &lt;2% require labelled EG-51 simulator data and belong to EG-43. These metrics are not asserted here.

**Risk / open point:** the accepted ADR defines signals per UTC playback month and exclusion per settlement month. Offline events with playback months outside the supplied Silver snapshot must be included for a complete account-level evaluation. Do not claim acceptance until the source window is verified. Grouped pandas evaluation also needs a volume/performance test.

## Español — implementación y estado de aceptación

**Rama:** feature/EG-36-spark-fraud (nace de develop). **Sin fusionar.**

**Fuentes:** RN-03 / HU09, decisiones EG-11 Q2/Q3/Q4, ADR-0002, ADR-0005 y las funciones puras existentes en sonoraplay.reglas.fraude.

**Orden:** Bronze verificado → Silver (RN-01, RN-02, RN-04) → evaluación Spark EG-36 → registros elegibles para Gold → país/plan F3 → titular F1 → contrato F4 → reparto RN-05–RN-10 → publicación en RDS/Gold. El CLI productivo de Gold ahora evalúa fraude antes de liquidar. No se modificó el contrato de salida de Silver.

**Señales:** más de 20 horas en una ventana móvil de 24 h; más del 70% de reproducciones mensuales hacia un artista con menos de 1.000 oyentes distintos; o un dispositivo usado por más de cinco cuentas. Los límites exactos no disparan la señal.

**Exclusión:** la detección utiliza el mes UTC de reproducción y retiene todo el mes de liquidación de la cuenta afectada, incluidos eventos offline. Silver conserva las reproducciones originales. Gold utiliza pagable_gold y su conciliación solo compara reproducciones realmente elegibles. Las retenidas no participan en el reparto.

**Catálogo:** artista_principal identifica al artista de la señal de concentración; titular_id identifica al beneficiario económico. No son intercambiables. Si falta la correspondencia del artista, el cálculo falla de forma segura.

**Compatibilidad:** se conserva el modo antiguo de liquidar para las pruebas existentes de EG-37; el CLI productivo exige fraude_verificado=True. No debe utilizarse el modo antiguo para una liquidación real.

**Pendiente para aceptar:** ejecutar la suite Spark, leer F1 Parquet real, conciliar play_id retenidos con Gold/RDS, medir dinero retenido con las bolsas reales, probar el DAG mensual en AWS y conservar evidencia CI. CA-10 (≥95% de detección, &lt;2% falsos positivos) requiere etiquetas del simulador EG-51 y se valida en EG-43. Todavía no se afirma cumplimiento.

**Riesgo:** los eventos offline pueden exigir una ventana Silver más amplia para evaluar todos los meses UTC de reproducción. También falta medir memoria y duración de los grupos pandas.

## English — financial verification and false-positive policy

**Decision verified against the accepted ADR-0005:** do not change the three strict RN-03 thresholds or silently exempt a six-member family sharing one device. ADR-0005 explicitly accepts this edge case for manual review. CA-10 is a measured target (&lt;2% false-positive rate), not a promise of zero false positives. A held legitimate account is not permanently denied royalties: ADR-0007 requires append-only adjustment after review.

**Gold formula verified:** `repartir_bolsa` uses Decimal, separate country/component denominators, and each rights holder receives `pool * eligible_count / total_eligible_count * contract_percentage / 100`. Held accounts do not contribute to either numerator or denominator. The remaining eligible shares may increase; this follows RN-05–RN-10 and RNF-02, not a financial defect. The new test verifies an exact USD 50.00 royalty from a USD 100.00 subscription pool and 50% contract after excluding four farm plays, without altering the accepted formula.

**Additional safety fix:** when a DataFrame contains any fraud decision columns, `liquidar` now enforces `preparar_gold` even if an older caller omits the new flag. This prevents an accidental bypass while retaining compatibility for legacy tests that have no fraud fields.

**CA-10 evaluation:** `medir_ca10` produces TP, FP, TN, FN, recall and false-positive rate from independently labelled EG-51 accounts; it fails on missing predictions or unknown labels and accepts only recall ≥95% and FPR &lt;2%. Its unit tests verify the boundary, **not** actual EG-51 performance. A labelled end-to-end simulator run remains required before acceptance.

## Español — verificación financiera y política de falsos positivos

**Decisión contrastada con ADR-0005:** no se cambian los tres umbrales estrictos RN-03 ni se exceptúa silenciosamente a una familia de seis miembros que comparte dispositivo. El ADR aceptado reconoce expresamente ese caso y lo envía a revisión. CA-10 exige medir una tasa de falsos positivos inferior al 2%, no garantiza cero. Si una cuenta legítima se libera, sus regalías se pagan como ajuste append-only según ADR-0007.

**Fórmula Gold contrastada:** `repartir_bolsa` utiliza Decimal y denominadores independientes por país y componente; la regalía es `bolsa * reproducciones_elegibles_del_titular / total_elegibles * porcentaje_contractual / 100`. Las cuentas retenidas no suman en numerador ni denominador. Puede aumentar la participación de los titulares elegibles restantes; es el comportamiento previsto por RN-05–RN-10 y RNF-02, no un error de cálculo. La prueba añadida comprueba USD 50,00 exactos con bolsa USD 100,00 y contrato del 50%, tras excluir cuatro reproducciones fraudulentas, sin cambiar la fórmula aceptada.

**Corrección de seguridad:** si el DataFrame incluye campos de decisión de fraude, `liquidar` obliga a usar `preparar_gold` incluso si un llamador antiguo no activa explícitamente la bandera. Así no se salta accidentalmente la exclusión y se mantienen las pruebas antiguas sin campos de fraude.

**Medición CA-10:** `medir_ca10` calcula VP, FP, VN, FN, sensibilidad y tasa de falsos positivos con etiquetas independientes EG-51. Rechaza predicciones faltantes y exige sensibilidad ≥95% y falsos positivos &lt;2%. Sus pruebas comprueban los límites matemáticos, **no** el rendimiento real del simulador. Falta ejecutar el circuito completo con etiquetas antes de aceptar.
