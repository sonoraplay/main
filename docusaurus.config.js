// Portal de documentación. No despliega la aplicación ni modifica AWS.
const config = {
  title: 'SonoraPlay Regalías',
  tagline: 'Documentación de arquitectura, datos y ejecución',
  favicon: 'img/favicon.svg',
  url: 'https://joshuaq-rj.github.io',
  baseUrl: '/sonoraplay-proyect/',
  organizationName: 'JoshuaQ-rJ',
  projectName: 'sonoraplay-proyect',
  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',
  i18n: { defaultLocale: 'es', locales: ['es', 'en'], localeConfigs: { es: { label: 'Español' }, en: { label: 'English' } } },
  presets: [['classic', {
    docs: { path: 'docs', routeBasePath: '/', sidebarPath: './sidebars.js', showLastUpdateTime: false },
    blog: false,
    theme: { customCss: './src/css/custom.css' }
  }]],
  themes: ['@docusaurus/theme-mermaid'],
  markdown: { mermaid: true },
  themeConfig: {
    navbar: { title: 'SonoraPlay', items: [
      { type: 'docSidebar', sidebarId: 'tutorialSidebar', position: 'left', label: 'Documentación' },
      { type: 'localeDropdown', position: 'right' },
      { href: 'https://github.com/JoshuaQ-rJ/sonoraplay-proyect', label: 'GitHub', position: 'right' }
    ] },
    footer: { style: 'dark', copyright: 'SonoraPlay · Proyecto académico de ingeniería de datos' }
  }
};
module.exports = config;
