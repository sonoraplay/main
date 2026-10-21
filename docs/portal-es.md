---
id: portal-es
slug: /
title: Inicio · Español
sidebar_position: 1
---

# SonoraPlay Regalías

SonoraPlay es un proyecto académico de ingeniería de datos para validar reproducciones musicales y calcular regalías por titular de derechos, país y período.

## ¿Qué contiene este portal?

La documentación existente del repositorio se presenta aquí sin duplicarla: análisis de reglas, arquitectura, datos, servicios, decisiones ADR y el esqueleto local de punta a punta.

## Ejecución local

Necesitas Git, Docker Desktop o Docker Engine con Compose, y un archivo `.env` creado a partir de `.env.example`. Configura contraseñas y el secreto JWT sin subirlos al repositorio.

```bash
git clone https://github.com/JoshuaQ-rJ/sonoraplay-proyect.git
cd sonoraplay-proyect
git checkout develop
cp .env.example .env
docker compose --profile esqueleto up -d --build
docker compose ps -a
docker compose logs esqueleto
```

APIs locales: http://localhost:8000/docs y http://localhost:8001/docs.

Consulta [Esqueleto local](./esqueleto.md) y el README del repositorio para las instrucciones completas.

**Alcance:** este portal documenta el proyecto; no demuestra que AWS esté desplegado. Las verificaciones de infraestructura deben registrarse con evidencias reales.
