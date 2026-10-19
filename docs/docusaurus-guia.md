---
id: docusaurus-guia
title: Guía de Docusaurus · Docusaurus guide
sidebar_position: 3
---

# Documentación / Documentation

## Español

Este portal reutiliza la carpeta `docs/` existente y **no cambia** el funcionamiento de SonoraPlay.

1. Instala Node.js 20 o superior.
2. Ejecuta `npm install`.
3. Ejecuta `npm run docs:start` para abrir el portal local.
4. Ejecuta `npm run docs:build` antes de abrir un PR.
5. Escribe las nuevas entregas en Markdown bajo `docs/`, con su historia Jira y evidencias verificables. Incluye el contenido equivalente en inglés y español.

El selector de idioma está preparado, pero **los documentos históricos aún no tienen traducción completa**. El contenido en español es el original; la página `Overview · English` es un resumen equivalente de la introducción. No se debe presentar el resto como traducido.

**Publicación:** la configuración incluye la URL base prevista para GitHub Pages y existe un workflow de Docusaurus en `develop`, pero una compilación correcta no significa que el portal esté publicado. Joshua debe integrar el workflow en `main` y un administrador debe configurar **Settings → Pages → Build and deployment → GitHub Actions**. No se modifica `main` ni se activa Pages desde esta guía.

## English

This portal reuses the existing `docs/` directory and **does not alter** the SonoraPlay application.

1. Install Node.js 20 or newer.
2. Run `npm install`.
3. Run `npm run docs:start` to preview the portal locally.
4. Run `npm run docs:build` before opening a PR.
5. Add new Markdown deliverables under `docs/`, referencing their Jira story and verified evidence. Provide equivalent English and Spanish content.

The locale selector is configured, but **historical technical documents have not been fully translated**. Spanish is the source language; `Overview · English` provides an English overview. Do not claim the remaining pages are translated.

**Publishing:** the GitHub Pages base URL is preconfigured and a Docusaurus workflow exists on `develop`, but a successful build does not mean the portal is publicly deployed. Joshua must integrate the workflow into `main`, and an administrator must configure **Settings → Pages → Build and deployment → GitHub Actions**. This guide does not modify `main` or enable Pages.


## Lista de verificación de entrega / Delivery checklist

### Español

- [ ] Confirmar que el workflow de Docusaurus y la documentación aprobada están en `main` (responsable: Joshua).
- [ ] Confirmar que GitHub Pages utiliza **GitHub Actions** como fuente (requiere administrador).
- [ ] Comprobar un despliegue **build + deploy** exitoso desde `main`; una compilación de PR no basta.
- [ ] Abrir `https://joshuaq-rj.github.io/sonoraplay-proyect/` en una ventana privada y comprobar que es accesible sin iniciar sesión.
- [ ] Revisar portada, navegación lateral, imagen de arquitectura, enlaces internos y páginas de datos, servicios y ADR.
- [ ] Comprobar el selector de idiomas sin afirmar que todos los documentos históricos están traducidos.
- [ ] Guardar capturas de la URL pública y del workflow de despliegue, con fecha y commit.
- [ ] Marcar los componentes AWS como **diseño/propuesta** hasta disponer de evidencias reales de despliegue.

**Diagnóstico:** si la URL devuelve 404, revisar primero que Pages esté habilitado, que el workflow exista en `main` y que `baseUrl` sea `/sonoraplay-proyect/`. Si el sitio abre pero faltan páginas, revisar los enlaces relativos y el registro de compilación. No publicar secretos ni capturas con credenciales.

### English

- [ ] Confirm that the Docusaurus workflow and approved documentation have reached `main` (owner: Joshua).
- [ ] Confirm GitHub Pages uses **GitHub Actions** as its source (administrator required).
- [ ] Verify a successful **build + deploy** run from `main`; a PR build alone is insufficient.
- [ ] Open `https://joshuaq-rj.github.io/sonoraplay-proyect/` in a private window and verify access without signing in.
- [ ] Check the homepage, sidebar, architecture image, internal links, data, services, and ADR pages.
- [ ] Test the locale selector without claiming that all historical documents are translated.
- [ ] Save dated screenshots of the public URL and deployment workflow, including the commit identifier.
- [ ] Label AWS components as **design/proposal** until real deployment evidence is available.

**Troubleshooting:** for a 404, first check that Pages is enabled, the workflow exists on `main`, and `baseUrl` is `/sonoraplay-proyect/`. If the site loads but pages are missing, check relative links and build logs. Never publish secrets or credential-bearing screenshots.


## Cobertura de idiomas y estado / Language coverage and status

### Español

- **Traducción técnica completa añadida:** modelos de datos F3 y F4 (secciones equivalentes en inglés dentro de cada página).
- **Resumen técnico en inglés añadido:** arquitectura v1 y APIs de contratos y titulares; las tablas detalladas y ejemplos originales permanecen en español.
- **Documentos bilingües:** guía de Docusaurus, entrega del portal, EG-30 y ADR-0021.
- **Pendiente para cobertura completa:** traducción íntegra de eventos F2, análisis de ambigüedades, ADR históricos; revisión editorial de las nuevas secciones inglesas de simulador F2 y atribución offline y los detalles extensos de las APIs y arquitectura. No debe afirmarse que todo el portal está traducido.
- **Coherencia:** distinguir diseño AWS, código local y despliegue real. Las pruebas CI usan datos simulados para EG-30; no demuestran acceso a APIs externas ni a AWS.

### English

- **Full technical translation added:** F3 and F4 data models (equivalent English sections in each page).
- **English technical summaries added:** architecture v1 and contracts/rights-holder APIs; original detailed tables and examples remain in Spanish.
- **Bilingual documents:** Docusaurus guide, portal handoff, EG-30 and ADR-0021.
- **Remaining for full coverage:** complete translation of F2 events, ambiguity analysis, and historical ADRs; editorial review of the new English sections for the F2 simulator and offline attribution, and detailed API and architecture content. Do not claim the whole portal is translated.
- **Consistency:** distinguish AWS design, locally implemented code, and live deployment. EG-30 CI uses mocked data and does not establish external API or AWS availability.


### Actualización de cobertura / Coverage update (2026-10-16)

**Español:** se añadieron secciones inglesas a eventos F2 y resúmenes de decisión a ADR-0001–0008 y ADR-0020. El análisis de ambigüedades, originalmente en inglés, tiene ahora una guía de lectura en español. **La cobertura sigue siendo parcial**: los resúmenes ADR no sustituyen la traducción íntegra de sus alternativas, criterios y consecuencias; las secciones largas de las APIs y la arquitectura conservan detalles únicamente en español. No se han cambiado las decisiones aprobadas.

**English:** English sections were added to F2 events, and decision summaries to ADR-0001–0008 and ADR-0020. The ambiguity analysis, originally in English, now includes a Spanish reading guide. **Coverage remains partial**: ADR summaries do not replace full translations of alternatives, criteria, and consequences; detailed API and architecture sections still contain Spanish-only material. Approved decisions were not changed.
