"""EG-32 · La cotización por lista de precios: cuentas hechas a mano con precios fijos."""

from decimal import Decimal

from sonoraplay import costos as c

D = Decimal

# Precios de la lista oficial de AWS (us-east-1), publicada el 2026-10-29 (EC2) y 2026-11-02 (ELB).
P = c.Precios(
    ec2_hora={"t4g.micro": D("0.0084"), "t4g.small": D("0.0168"), "t4g.medium": D("0.0336")},
    ebs_gp3_gb_mes=D("0.08"),
    rds_t4g_micro_pg_hora=D("0.016"),
    rds_gp3_gb_mes=D("0.115"),
    alb_hora=D("0.0225"),
    alb_lcu_hora=D("0.008"),
    fargate_arm_vcpu_hora=D("0.03238"),
    fargate_arm_gb_hora=D("0.00356"),
    ipv4_publica_hora=D("0.005"),
    s3_gb_mes=D("0.023"),
    s3_put_solicitud=D("0.000005"),
    s3_get_solicitud=D("0.0000004"),
    ecr_gb_mes=D("0.10"),
    cw_alarma_mes=D("0.10"),
    cw_logs_ingesta_gb=D("0.50"),
    cw_logs_almacenamiento_gb_mes=D("0.03"),
    eks_cluster_hora=D("0.10"),
)


def linea(filas, servicio):
    return next(usd for s, _, usd in filas if s == servicio)


def test_escenario_24_7_cuentas_a_mano():
    f = c.cotizar(P, 730)
    assert linea(f, "EC2 NAT") == D("0.0084") * 730  # 6.132
    assert linea(f, "EC2 Airflow") == D("0.0336") * 730  # 24.528
    assert linea(f, "EBS gp3") == D("0.08") * 58  # 8 + 20 + 30 GB durante todo el mes
    # 4 tareas × (0,25 × 0,03238 + 0,5 × 0,00356) × 730
    assert linea(f, "ECS Fargate ARM") == D("4") * (D("0.008095") + D("0.00178")) * 730
    assert linea(f, "IPv4 públicas") == D("0.005") * 3 * 730  # 1 de la NAT + 2 del ALB
    assert c.total(f).quantize(D("0.01")) == D("126.21")


def test_escenario_ventanas_prorratea_lo_que_se_destruye_y_conserva_lo_persistente():
    a, b = c.cotizar(P, 730), c.cotizar(P, 24)
    # Persistentes: iguales en los dos escenarios.
    for persistente in (
        "S3 almacenamiento",
        "S3 solicitudes PUT",
        "S3 solicitudes GET",
        "ECR",
        "CloudWatch almacenamiento de logs",
        "Spark (Fargate ARM, precio On-Demand)",
    ):
        assert linea(a, persistente) == linea(b, persistente), persistente
    # Por hora y por GB-mes que desaparece con destroy: escalan con 24/730.
    esperado = D("0.08") * 58 * D(24) / D(730)  # 0,152548
    assert abs(linea(b, "EBS gp3") - esperado) < D("1e-9")
    assert linea(b, "EC2 RabbitMQ") == D("0.0168") * 24
    assert c.total(b).quantize(D("0.01")) == D("5.61")


def test_las_ventanas_cuestan_una_fraccion_del_24_7():
    assert c.total(c.cotizar(P, 24)) < c.total(c.cotizar(P, 730)) / 20


def test_eks_se_cotiza_aparte_y_no_entra_en_los_totales_principales():
    nombres = {s for s, _, _ in c.cotizar(P, 730)}
    assert not any("EKS" in n for n in nombres)
    e = c.cotizar_eks(P, 24)
    assert linea(e, "EKS plano de control") == D("2.4")  # 24 h × 0,10 USD
    assert c.total(c.cotizar_eks(P, 730)).quantize(D("0.01")) == D("86.86")


def test_el_informe_incluye_ambos_escenarios_y_eks():
    texto = c.informe(P)
    assert "126.21" in texto and "5.61" in texto and "86.86" in texto and "2.86" in texto
