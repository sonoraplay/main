"""EG-32 · Cotización de la arquitectura con la lista de precios oficial de AWS (us-east-1, USD).

Calcula los dos escenarios del criterio 2 con el mismo inventario (24/7 de 730 h y ventanas de
8 × 3 h = 24 h) y el costo de EKS por separado. Los precios **no** se escriben aquí: salen de los
archivos de la API pública de precios (``leer_precios``) y cada cifra del informe lleva su
unidad y origen. Es la misma fuente que usa la AWS Pricing Calculator, pero esto **no** la
reemplaza: el criterio 1 pide además el enlace a la estimación de la calculadora.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

HORAS_MES = Decimal(730)


@dataclass(frozen=True)
class Precios:
    """Precios unitarios en USD (cadenas de la lista oficial, sin redondear)."""

    ec2_hora: dict[str, Decimal]  # tipo de instancia Linux ARM -> USD/h
    ebs_gp3_gb_mes: Decimal
    rds_t4g_micro_pg_hora: Decimal
    rds_gp3_gb_mes: Decimal
    alb_hora: Decimal
    alb_lcu_hora: Decimal
    fargate_arm_vcpu_hora: Decimal
    fargate_arm_gb_hora: Decimal
    ipv4_publica_hora: Decimal
    s3_gb_mes: Decimal
    s3_put_solicitud: Decimal
    s3_get_solicitud: Decimal
    ecr_gb_mes: Decimal
    cw_alarma_mes: Decimal
    cw_logs_ingesta_gb: Decimal
    cw_logs_almacenamiento_gb_mes: Decimal
    eks_cluster_hora: Decimal


@dataclass(frozen=True)
class Inventario:
    """El inventario del proyecto tal como lo pidió la EG-32."""

    nat: str = "t4g.micro"
    nat_ebs_gb: int = 8
    rabbitmq: str = "t4g.small"
    rabbitmq_ebs_gb: int = 20
    airflow: str = "t4g.medium"
    airflow_ebs_gb: int = 30
    rds_gb: int = 20
    albs: int = 1
    lcu: int = 1
    tareas_fargate: int = 4
    tarea_vcpu: Decimal = Decimal("0.25")
    tarea_gb: Decimal = Decimal("0.5")
    spark_vcpu: int = 2
    spark_gb: int = 8
    spark_horas_mes: int = 6
    s3_gb: int = 5
    s3_put: int = 100_000
    s3_get: int = 200_000
    ecr_gb: int = 2
    alarmas: int = 1
    logs_gb_mes: int = 2
    ips_publicas: int = 3  # 1 de la NAT + 2 del ALB (una por zona)
    # EKS (se cotiza aparte): 1 nodo y su disco, como en infra/terraform/eks
    eks_nodo: str = "t4g.small"
    eks_disco_gb: int = 20


def cotizar(
    p: Precios, horas: int, inv: Inventario | None = None
) -> list[tuple[str, str, Decimal]]:
    """Costo mensual por línea para ``horas`` de encendido. Devuelve (servicio, supuesto, USD).

    - Lo que se cobra por hora (EC2, RDS, ALB, Fargate, IPv4) se multiplica por ``horas``.
    - Lo que se cobra por GB-mes y desaparece con ``terraform destroy`` (EBS, almacenamiento de
      RDS, alarma) se prorratea por hora: ``horas / 730``.
    - Persistentes (iguales en ambos escenarios): S3, ECR y el almacenamiento de logs.
    - Spark corre un número fijo de horas al mes en ambos escenarios.
    - La ingesta de logs se escala con las horas encendidas (solo hay logs si algo corre).
    """
    i = inv or Inventario()
    h = Decimal(horas)
    f = h / HORAS_MES
    filas: list[tuple[str, str, Decimal]] = []

    def add(servicio: str, supuesto: str, usd: Decimal) -> None:
        filas.append((servicio, supuesto, usd))

    add("EC2 NAT", f"{i.nat} × {horas} h", p.ec2_hora[i.nat] * h)
    add("EC2 RabbitMQ", f"{i.rabbitmq} × {horas} h", p.ec2_hora[i.rabbitmq] * h)
    add("EC2 Airflow", f"{i.airflow} × {horas} h", p.ec2_hora[i.airflow] * h)
    ebs = i.nat_ebs_gb + i.rabbitmq_ebs_gb + i.airflow_ebs_gb
    add("EBS gp3", f"{ebs} GB × {horas}/730 mes", p.ebs_gp3_gb_mes * ebs * f)
    add("RDS PostgreSQL db.t4g.micro", f"Single-AZ × {horas} h", p.rds_t4g_micro_pg_hora * h)
    add(
        "RDS almacenamiento gp3",
        f"{i.rds_gb} GB × {horas}/730 mes",
        p.rds_gp3_gb_mes * i.rds_gb * f,
    )
    add("ALB", f"{i.albs} ALB × {horas} h", p.alb_hora * i.albs * h)
    add("ALB LCU", f"{i.lcu} LCU × {horas} h", p.alb_lcu_hora * i.lcu * h)
    por_tarea = i.tarea_vcpu * p.fargate_arm_vcpu_hora + i.tarea_gb * p.fargate_arm_gb_hora
    add(
        "ECS Fargate ARM",
        f"{i.tareas_fargate} tareas de {i.tarea_vcpu} vCPU / {i.tarea_gb} GB × {horas} h",
        por_tarea * i.tareas_fargate * h,
    )
    add("IPv4 públicas", f"{i.ips_publicas} × {horas} h", p.ipv4_publica_hora * i.ips_publicas * h)
    spark_h = p.fargate_arm_vcpu_hora * i.spark_vcpu + p.fargate_arm_gb_hora * i.spark_gb
    add(
        "Spark (Fargate ARM, precio On-Demand)",
        f"{i.spark_vcpu} vCPU / {i.spark_gb} GB × {i.spark_horas_mes} h",
        spark_h * i.spark_horas_mes,
    )
    add("S3 almacenamiento", f"{i.s3_gb} GB", p.s3_gb_mes * i.s3_gb)
    add("S3 solicitudes PUT", f"{i.s3_put:,} solicitudes", p.s3_put_solicitud * i.s3_put)
    add("S3 solicitudes GET", f"{i.s3_get:,} solicitudes", p.s3_get_solicitud * i.s3_get)
    add("ECR", f"{i.ecr_gb} GB", p.ecr_gb_mes * i.ecr_gb)
    add("CloudWatch alarma", f"{i.alarmas} × {horas}/730 mes", p.cw_alarma_mes * i.alarmas * f)
    add(
        "CloudWatch ingesta de logs",
        f"{i.logs_gb_mes} GB × {horas}/730",
        p.cw_logs_ingesta_gb * i.logs_gb_mes * f,
    )
    add(
        "CloudWatch almacenamiento de logs",
        f"{i.logs_gb_mes} GB (persistente)",
        p.cw_logs_almacenamiento_gb_mes * i.logs_gb_mes,
    )
    return filas


def cotizar_eks(
    p: Precios, horas: int, inv: Inventario | None = None
) -> list[tuple[str, str, Decimal]]:
    """EKS aparte: plano de control + 1 nodo + su disco. No se suma a los totales principales."""
    i = inv or Inventario()
    h = Decimal(horas)
    return [
        ("EKS plano de control", f"1 clúster × {horas} h", p.eks_cluster_hora * h),
        ("EC2 nodo", f"{i.eks_nodo} × {horas} h", p.ec2_hora[i.eks_nodo] * h),
        (
            "EBS gp3 del nodo",
            f"{i.eks_disco_gb} GB × {horas}/730 mes",
            p.ebs_gp3_gb_mes * i.eks_disco_gb * h / HORAS_MES,
        ),
    ]


def total(filas: list[tuple[str, str, Decimal]]) -> Decimal:
    return sum((usd for _, _, usd in filas), Decimal(0))


# --- Lectura de la lista de precios oficial -------------------------------------------------


def _usd(d: dict, sku: str) -> Decimal:
    (oferta,) = d["terms"]["OnDemand"][sku].values()
    (dim,) = [x for x in oferta["priceDimensions"].values() if x["beginRange"] == "0"]
    return Decimal(dim["pricePerUnit"]["USD"])


def _unico(d: dict, **atributos: str) -> str:
    """El único SKU cuyos atributos coinciden; falla si hay 0 o varios (no se adivina)."""
    familia = atributos.pop("productFamily", None)
    skus = [
        s
        for s, p in d["products"].items()
        if all(p.get("attributes", {}).get(k) == v for k, v in atributos.items())
        and (familia is None or p.get("productFamily") == familia)
    ]
    if len(skus) != 1:
        raise ValueError(f"se esperaba 1 SKU para {atributos}; hay {len(skus)}")
    return skus[0]


def leer_precios(carpeta: Path) -> Precios:
    """Lee los archivos de ``https://pricing.us-east-1.amazonaws.com`` descargados en ``carpeta``
    (``AmazonEC2.json``, ``AmazonRDS.json``, ``AWSELB.json``, ``AmazonECS.json``,
    ``AmazonS3.json``, ``AmazonECR.json``, ``AmazonCloudWatch.json``, ``AmazonVPC.json``,
    ``AmazonEKS.json``; la versión de cada región)."""

    def carga(n: str) -> dict:
        return json.loads((carpeta / f"{n}.json").read_text(encoding="utf-8"))

    ec2, rds, elb, ecs = carga("AmazonEC2"), carga("AmazonRDS"), carga("AWSELB"), carga("AmazonECS")
    s3, ecr, cw, vpc, eks = (
        carga("AmazonS3"),
        carga("AmazonECR"),
        carga("AmazonCloudWatch"),
        carga("AmazonVPC"),
        carga("AmazonEKS"),
    )
    tipos = {}
    for t in ("t4g.micro", "t4g.small", "t4g.medium"):
        sku = _unico(
            ec2,
            instanceType=t,
            operatingSystem="Linux",
            tenancy="Shared",
            preInstalledSw="NA",
            capacitystatus="Used",
            usagetype=f"BoxUsage:{t}",
        )
        tipos[t] = _usd(ec2, sku)

    def por_uso(d: dict, usagetype: str, **extra: str) -> Decimal:
        return _usd(d, _unico(d, usagetype=usagetype, **extra))

    rds_inst = [
        s
        for s, p in rds["products"].items()
        if p["attributes"].get("usagetype") == "InstanceUsage:db.t4g.micro"
        and p["attributes"].get("databaseEngine") == "PostgreSQL"
        and p["attributes"].get("deploymentOption") == "Single-AZ"
    ]
    rds_gp3 = {
        _usd(rds, s)
        for s, p in rds["products"].items()
        if p["attributes"].get("usagetype") == "RDS:GP3-Storage"
        and p["attributes"].get("databaseEngine") == "PostgreSQL"
        and p["attributes"].get("deploymentOption") == "Single-AZ"
    }
    if len(rds_inst) != 1 or len(rds_gp3) != 1:
        raise ValueError("la lista de RDS no dio un precio único para PostgreSQL Single-AZ")
    return Precios(
        ec2_hora=tipos,
        ebs_gp3_gb_mes=por_uso(ec2, "EBS:VolumeUsage.gp3"),
        rds_t4g_micro_pg_hora=_usd(rds, rds_inst[0]),
        rds_gp3_gb_mes=next(iter(rds_gp3)),
        alb_hora=por_uso(elb, "LoadBalancerUsage", productFamily="Load Balancer-Application"),
        alb_lcu_hora=por_uso(elb, "LCUUsage", productFamily="Load Balancer-Application"),
        fargate_arm_vcpu_hora=por_uso(ecs, "USE1-Fargate-ARM-vCPU-Hours:perCPU"),
        fargate_arm_gb_hora=por_uso(ecs, "USE1-Fargate-ARM-GB-Hours"),
        ipv4_publica_hora=por_uso(vpc, "USE1-PublicIPv4:InUseAddress"),
        s3_gb_mes=por_uso(s3, "TimedStorage-ByteHrs", storageClass="General Purpose"),
        s3_put_solicitud=por_uso(s3, "Requests-Tier1"),
        s3_get_solicitud=por_uso(s3, "Requests-Tier2"),
        ecr_gb_mes=por_uso(ecr, "TimedStorage-ByteHrs"),
        cw_alarma_mes=_cw_alarma(cw),
        cw_logs_ingesta_gb=_cw_ingesta(cw),
        cw_logs_almacenamiento_gb_mes=_cw_almacenamiento(cw),
        eks_cluster_hora=por_uso(eks, "USE1-AmazonEKS-Hours:perCluster"),
    )


def _cw_alarma(cw: dict) -> Decimal:
    skus = [
        s
        for s, p in cw["products"].items()
        if p["attributes"].get("usagetype") == "CW:AlarmMonitorUsage"
        and p["attributes"].get("group") != "CW-MonthlyFree-Alarm"
    ]
    precios = {_usd(cw, s) for s in skus if "standard resolution" in _desc(cw, s)}
    if len(precios) != 1:
        raise ValueError("alarma estándar de CloudWatch: precio no único")
    return next(iter(precios))


def _cw_ingesta(cw: dict) -> Decimal:
    skus = [
        s
        for s, p in cw["products"].items()
        if p["attributes"].get("usagetype") == "USE1-DataProcessing-Bytes"
        and "Standard log class" in _desc(cw, s)
    ]
    precios = {_usd(cw, s) for s in skus}
    if len(precios) != 1:
        raise ValueError("ingesta de logs de CloudWatch: precio no único")
    return next(iter(precios))


def _cw_almacenamiento(cw: dict) -> Decimal:
    skus = [
        s
        for s, p in cw["products"].items()
        if p["attributes"].get("usagetype") == "USE1-TimedStorage-ByteHrs"
        and "log storage" in _desc(cw, s)
    ]
    precios = {_usd(cw, s) for s in skus}
    if len(precios) != 1:
        raise ValueError("almacenamiento de logs de CloudWatch: precio no único")
    return next(iter(precios))


def _desc(d: dict, sku: str) -> str:
    (oferta,) = d["terms"]["OnDemand"][sku].values()
    return " ".join(x["description"] for x in oferta["priceDimensions"].values())


# --- Informe --------------------------------------------------------------------------------


def _fmt(x: Decimal) -> str:
    return f"{x.quantize(Decimal('0.01'))}"


def informe(p: Precios) -> str:
    """Tablas Markdown de los dos escenarios y de EKS, con los precios unitarios usados."""
    a, b = cotizar(p, 730), cotizar(p, 24)
    ea, eb = cotizar_eks(p, 730), cotizar_eks(p, 24)
    out = [
        "| Servicio | Supuesto (24/7) | A · 24/7 (USD/mes) | B · ventanas (USD/mes) |",
        "|---|---|---:|---:|",
    ]
    for (s, sa, ua), (_, _, ub) in zip(a, b, strict=True):
        out.append(f"| {s} | {sa} | {_fmt(ua)} | {_fmt(ub)} |")
    out.append(f"| **Total sin EKS** | | **{_fmt(total(a))}** | **{_fmt(total(b))}** |")
    out += [
        "",
        "| EKS (aparte) | Supuesto (24/7) | 730 h (USD) | 24 h (USD) |",
        "|---|---|---:|---:|",
    ]
    for (s, sa, ua), (_, _, ub) in zip(ea, eb, strict=True):
        out.append(f"| {s} | {sa} | {_fmt(ua)} | {_fmt(ub)} |")
    out.append(f"| **Total EKS** | | **{_fmt(total(ea))}** | **{_fmt(total(eb))}** |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m sonoraplay.costos")
    ap.add_argument("--precios", type=Path, required=True, help="carpeta con los JSON de precios")
    print(informe(leer_precios(ap.parse_args(argv).precios)))


if __name__ == "__main__":
    main()
