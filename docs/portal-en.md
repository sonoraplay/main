---
id: portal-en
title: Overview · English
sidebar_position: 2
---

# SonoraPlay Royalties

SonoraPlay is an academic data engineering project that validates music streaming events and calculates royalties by rights holder, country, and accounting period.

## What is documented?

This portal exposes the repository's existing documentation: business-rule analysis, architecture, data models, services, architecture decision records (ADRs), and the local end-to-end walking skeleton.

## Run locally

You need Git, Docker Desktop or Docker Engine with Compose, and a `.env` file copied from `.env.example`. Set secure database and JWT secrets, and never commit them.

```bash
git clone https://github.com/JoshuaQ-rJ/sonoraplay-proyect.git
cd sonoraplay-proyect
git checkout develop
cp .env.example .env
docker compose --profile esqueleto up -d --build
docker compose ps -a
docker compose logs esqueleto
```

Local APIs: http://localhost:8000/docs and http://localhost:8001/docs.

Refer to [the local walking skeleton](./esqueleto.md) and the repository README for the complete procedure.

**Scope:** the documentation portal does not imply that AWS resources are deployed. Infrastructure acceptance requires actual deployment evidence.

**Translation status:** existing technical documents are currently authored mainly in Spanish. English versions should be added progressively, keeping the same technical meaning.
