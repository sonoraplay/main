# Entrega del portal / Documentation portal handoff

## Español

**Objetivo:** publicar documentación accesible del proyecto para la entrega del 16 de octubre de 2026.

### Requisitos para publicar

1. Joshua revisa e integra el PR de Docusaurus y este cambio a `develop`; luego integra `develop` en `main` según el proceso del equipo. **No se publica desde PR ni desde `develop`.**
2. En GitHub, un administrador abre **Settings → Pages → Build and deployment → Source: GitHub Actions**. Esto requiere permisos de administración.
3. Tras integrar el workflow en `main`, ejecutar **Actions → Docusaurus → Run workflow** sobre `main`, o publicar una modificación de documentación en `main`.
4. Verificar la URL esperada, **solo después de un despliegue exitoso**: https://joshuaq-rj.github.io/sonoraplay-proyect/ .
5. Probar inicio, enlaces de la barra lateral, imágenes, páginas de arquitectura y servicios y selector de idioma. Revisar enlaces externos y registrar capturas de evidencia.
6. Confirmar con el TL si GitHub Pages sirve como dominio. Si se asigna otro dominio, actualizar `url`, `baseUrl`, `organizationName` y `projectName` según el destino real y configurar DNS y GitHub Pages antes de publicarlo.

**Nota de idiomas:** el portal tiene portadas en español e inglés, pero la mayoría de documentos técnicos originales permanecen en español; el selector de idioma no implica que todas las páginas estén traducidas.

**Nota de arquitectura:** las páginas existentes documentan decisiones y diseño, no garantizan que AWS o las APIs estén publicados. La arquitectura final debe ser confirmada por Joshua y Andrea antes de marcarla como definitiva.

### Evidencia de aceptación

- URL pública que abra desde un navegador sin sesión de GitHub.
- Ejecución de Actions con `build` y `deploy` exitosos.
- Capturas de portada, arquitectura, datos y servicios.
- Tabla de fuentes con enlaces a repositorios y endpoints **verificados**, sin inventar dominios.
- Confirmación de Joshua sobre la versión final de infraestructura.

## English

**Goal:** publish an accessible documentation portal for the October 16, 2026 deadline.

### Publishing prerequisites

1. Joshua reviews and merges the Docusaurus PR and this change into `develop`, then integrates `develop` into `main` following the team's process. **Neither pull requests nor `develop` publish the site.**
2. A repository administrator opens **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. After the workflow reaches `main`, use **Actions → Docusaurus → Run workflow** on `main`, or push a documentation change to `main`.
4. Verify the expected URL **only after successful deployment**: https://joshuaq-rj.github.io/sonoraplay-proyect/ .
5. Test home, sidebar links, images, architecture and service pages, language selector and external links. Save evidence screenshots.
6. Confirm with the instructor whether GitHub Pages is acceptable. If a custom domain is assigned, update the Docusaurus deployment settings and configure DNS and Pages accordingly.

**Language note:** Spanish and English overview pages exist, but most original technical pages are still in Spanish; language selection does not imply complete translation.

**Architecture note:** existing pages document design decisions, not proof of deployed AWS resources or APIs. Joshua and Andrea must confirm the final architecture before it is marked final.

### Acceptance evidence

- Public URL accessible without GitHub authentication.
- Successful Actions `build` and `deploy` jobs.
- Screenshots of home, architecture, data and services.
- Source inventory with **verified** repository and endpoint links.
- Joshua's confirmation of the final infrastructure version.
