# EG-36 — Spark fraud detection / Detección de fraude en Spark

## English — implementation and acceptance status

**Branch:** feature/EG-36-spark-fraud (based on develop). **Not merged.**

**Source of truth:** RN-03 / HU09, EG-11 decisions Q2/Q3/Q4, ADR-0002 and ADR-0005, and the existing pure functions in sonoraplay.reglas.fraude.

**Processing order:** verified Bronze → Silver (RN-01, RN-02, RN-04) → EG-36 Spark fraud evaluation → eligible Gold rows → F3 billing country and plan → F1 rights holder → F4 contract percentage → RN-05–RN-10 allocation → RDS/Gold publication. The production Gold CLI now evaluates fraud before calling liquidar. No changes were made to Silver's output contract.

**Signals:** (1) more than 20 listened hours in any rolling 24-hour window, computed using the accepted pure Python overlap algorithm per distributed account/month group; (2) more than 70% of monthly plays to one artist with fewer than 1,000 distinct monthly listeners; (3) a device shared by more than five accounts in the month. Thresholds are strict and configurable via ReglasFraudeConfig.

**Monthly treatment:** signals use the UTC playback month; flagged accounts' plays are held for the entire relevant settlement month, including offline plays. The original Silver records remain unchanged. Gold must only use pagable_gold, and its reconciliation compares the eligible set rather than all RN-01/RN-02-valid plays. No held play may enter a rights-holder allocation.

**F1 mapping:** the artist is the existing canonical artista_principal in catalogo_f1.parquet; it is intentionally separate from titular_id, which determines royalty ownership. Missing, null, blank or duplicated artist mappings fail the settlement rather than silently paying potentially fraudulent plays.

**Compatibility:** liquidar now requires fraud verification by default. Historical EG-37 tests explicitly pass fraude_verificado=False for isolated legacy behavior; production callers must not use that opt-out. Any supplied fraud-decision columns are validated by preparar_gold.

**Acceptance evidence:** CI [run 42516907872](https://github.com/sonoraplay/main/actions/runs/42516907872) executed 35 Spark Gold tests, including the 10,000-account Spark/Python parity test, successfully; the overall run had a lint failure corrected in a later commit, so final CI is still pending. A Spark Gold/PostgreSQL integration test verifies held plays are absent from published royalty rows in ephemeral CI PostgreSQL, not production RDS. Pure Python CA-10 metrics (TP=500, FP=1, TN=9499, FN=0) are in [run 42510450696](https://github.com/sonoraplay/main/actions/runs/42510450696). Still required: capture Spark confusion-matrix output, real F1 Parquet evidence, retained USD using actual pools, full monthly DAG in AWS, offline-window completeness and grouped-pandas performance.

**Risk / open point:** the accepted ADR defines signals per UTC playback month and exclusion per settlement month. Offline events with playback months outside the supplied Silver snapshot must be included for a complete account-level evaluation. Do not claim acceptance until the source window is verified. Grouped pandas evaluation also needs a volume/performance test.

## Español — implementación y estado de aceptación

**Rama:** feature/EG-36-spark-fraud (nace de develop). **Sin fusionar.**

**Fuentes:** RN-03 / HU09, decisiones EG-11 Q2/Q3/Q4, ADR-0002, ADR-0005 y las funciones puras existentes en sonoraplay.reglas.fraude.

**Orden:** Bronze verificado → Silver (RN-01, RN-02, RN-04) → evaluación Spark EG-36 → registros elegibles para Gold → país/plan F3 → titular F1 → contrato F4 → reparto RN-05–RN-10 → publicación en RDS/Gold. El CLI productivo de Gold ahora evalúa fraude antes de liquidar. No se modificó el contrato de salida de Silver.

**Señales:** más de 20 horas en una ventana móvil de 24 h; más del 70% de reproducciones mensuales hacia un artista con menos de 1.000 oyentes distintos; o un dispositivo usado por más de cinco cuentas. Los límites exactos no disparan la señal.

**Exclusión:** la detección utiliza el mes UTC de reproducción y retiene todo el mes de liquidación de la cuenta afectada, incluidos eventos offline. Silver conserva las reproducciones originales. Gold utiliza pagable_gold y su conciliación solo compara reproducciones realmente elegibles. Las retenidas no participan en el reparto.

**Catálogo:** artista_principal identifica al artista de la señal de concentración; titular_id identifica al beneficiario económico. No son intercambiables. Si falta la correspondencia del artista, el cálculo falla de forma segura.

**Compatibilidad:** liquidar exige verificar fraude por defecto. Las pruebas históricas EG-37 usan explícitamente fraude_verificado=False solo para comprobar el comportamiento aislado anterior; producción no debe usar esa excepción. preparar_gold valida los campos de fraude cuando existen.

**Evidencia de aceptación:** la ejecución CI [42516907872](https://github.com/sonoraplay/main/actions/runs/42516907872) aprobó 35 pruebas Spark Gold, incluida la paridad Spark/Python de 10.000 cuentas; el CI global tuvo un fallo de lint corregido después y sigue pendiente la ejecución final. Una prueba Spark Gold/PostgreSQL comprueba la ausencia de reproducciones retenidas en regalías publicadas en PostgreSQL efímero de CI, no en RDS productivo. Las métricas Python CA-10 (VP=500, FP=1, VN=9499, FN=0) constan en [42510450696](https://github.com/sonoraplay/main/actions/runs/42510450696). Faltan registrar la matriz de confusión Spark, F1 Parquet real, USD retenidos con bolsas reales, DAG mensual AWS, completitud de ventana offline y rendimiento de grupos pandas.

**Riesgo:** los eventos offline pueden exigir una ventana Silver más amplia para evaluar todos los meses UTC de reproducción. También falta medir memoria y duración de los grupos pandas.

## English — financial verification and false-positive policy

**Decision verified against the accepted ADR-0005:** do not change the three strict RN-03 thresholds or silently exempt a six-member family sharing one device. ADR-0005 explicitly accepts this edge case for manual review. CA-10 is a measured target (&lt;2% false-positive rate), not a promise of zero false positives. A held legitimate account is not permanently denied royalties: ADR-0007 requires append-only adjustment after review.

**Gold formula verified:** `repartir_bolsa` uses Decimal, separate country/component denominators, and each rights holder receives `pool * eligible_count / total_eligible_count * contract_percentage / 100`. Held accounts do not contribute to either numerator or denominator. The remaining eligible shares may increase; this follows RN-05–RN-10 and RNF-02, not a financial defect. The new test verifies an exact USD 50.00 royalty from a USD 100.00 subscription pool and 50% contract after excluding four farm plays, without altering the accepted formula.

**Additional safety fix:** liquidar enforces preparar_gold by default, even when no fraud columns exist (fail closed). A legacy opt-out must be explicit in isolated tests. If fraud columns exist, preparar_gold is enforced regardless of the opt-out.

**CA-10 evaluation:** `medir_ca10` produces TP, FP, TN, FN, recall and false-positive rate from independently labelled EG-51 accounts; it fails on missing predictions or unknown labels and accepts only recall ≥95% and FPR &lt;2%. Its unit tests verify the boundary, **not** actual EG-51 performance. A labelled end-to-end simulator run remains required before acceptance.

## Español — verificación financiera y política de falsos positivos

**Decisión contrastada con ADR-0005:** no se cambian los tres umbrales estrictos RN-03 ni se exceptúa silenciosamente a una familia de seis miembros que comparte dispositivo. El ADR aceptado reconoce expresamente ese caso y lo envía a revisión. CA-10 exige medir una tasa de falsos positivos inferior al 2%, no garantiza cero. Si una cuenta legítima se libera, sus regalías se pagan como ajuste append-only según ADR-0007.

**Fórmula Gold contrastada:** `repartir_bolsa` utiliza Decimal y denominadores independientes por país y componente; la regalía es `bolsa * reproducciones_elegibles_del_titular / total_elegibles * porcentaje_contractual / 100`. Las cuentas retenidas no suman en numerador ni denominador. Puede aumentar la participación de los titulares elegibles restantes; es el comportamiento previsto por RN-05–RN-10 y RNF-02, no un error de cálculo. La prueba añadida comprueba USD 50,00 exactos con bolsa USD 100,00 y contrato del 50%, tras excluir cuatro reproducciones fraudulentas, sin cambiar la fórmula aceptada.

**Corrección de seguridad:** liquidar obliga a pasar por preparar_gold por defecto, incluso si faltan columnas de fraude (fallo seguro). La excepción histórica debe ser explícita y limitada a pruebas aisladas. Si existen columnas de fraude, preparar_gold se ejecuta incluso con la excepción.

**Medición CA-10:** `medir_ca10` calcula VP, FP, VN, FN, sensibilidad y tasa de falsos positivos con etiquetas independientes EG-51. Rechaza predicciones faltantes y exige sensibilidad ≥95% y falsos positivos &lt;2%. Sus pruebas comprueban los límites matemáticos, **no** el rendimiento real del simulador. Falta ejecutar el circuito completo con etiquetas antes de aceptar.
