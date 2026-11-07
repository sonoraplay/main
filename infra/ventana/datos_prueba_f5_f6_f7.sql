-- Datos SINTÉTICOS de F5 (publicidad), F6 (cierres de tasas) y F7 (países) para la ventana de pruebas
-- de septiembre 2026. En producción los llenan los DAG diarios desde las fuentes reales; aquí solo
-- permiten que Gold arme las bolsas. No son cifras reales y no deben usarse como tales.
INSERT INTO fuente_f7_paises(pais, region, monedas) VALUES
 ('CO','LATAM','{COP}'),('PE','LATAM','{PEN}'),('CL','LATAM','{CLP}'),
 ('MX','LATAM','{MXN}'),('AR','LATAM','{ARS}'),('BR','LATAM','{BRL}') ON CONFLICT DO NOTHING;
INSERT INTO fuente_f5_publicidad(mes, pais, moneda, ingresos_publicidad) VALUES
 ('2026-09-01','CO','COP',40000000),('2026-09-01','PE','PEN',12000),('2026-09-01','CL','CLP',9000000),
 ('2026-09-01','MX','MXN',60000),('2026-09-01','AR','ARS',3000000),('2026-09-01','BR','BRL',25000)
 ON CONFLICT DO NOTHING;
INSERT INTO fuente_f6_cierres(moneda, fecha_cierre, fecha_observacion, unidades_por_usd, proveedor, extraido_en_utc) VALUES
 ('COP','2026-09-30','2026-09-30',4000,'prueba',now()),('PEN','2026-09-30','2026-09-30',3.7,'prueba',now()),
 ('CLP','2026-09-30','2026-09-30',950,'prueba',now()),('MXN','2026-09-30','2026-09-30',18,'prueba',now()),
 ('ARS','2026-09-30','2026-09-30',1000,'prueba',now()),('BRL','2026-09-30','2026-09-30',5.2,'prueba',now())
 ON CONFLICT DO NOTHING;
