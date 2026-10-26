import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(
  defineConfig({
    title: 'ContextCortex',
    description: 'High-Performance Syntax-Aware Code RAG & MCP Server',
    base: '/contextcortex/',
    cleanUrls: true,
    lastUpdated: true,
    srcExclude: ['superpowers/**', 'TEST_COVERAGE.md', 'REQUIREMENTS.md'],
    head: [
      ['link', { rel: 'icon', type: 'image/svg+xml', href: '/contextcortex/logo.svg' }]
    ],
    themeConfig: {
      logo: '/logo.svg',
      siteTitle: 'ContextCortex',
      outline: {
        level: [2, 3],
        label: 'On this page'
      },
      nav: [
        { text: 'Guide', link: '/guide/' },
        { text: 'User Guide', link: '/guide/user-guide' },
        { text: 'Architecture', link: '/architecture/' },
        { text: 'Requirements', link: '/requirements/' },
        { text: 'Reference', link: '/reference/mcp-tools' }
      ],
      sidebar: {
        '/guide/': [
          {
            text: 'Documentation Guide',
            items: [
              { text: 'Overview', link: '/guide/' },
              { text: 'Getting Started', link: '/guide/getting-started' },
              { text: 'Configuration', link: '/guide/configuration' }
            ]
          },
          {
            text: 'User Guide (Dashboard & Features)',
            collapsed: false,
            items: [
              { text: 'User Guide Hub', link: '/guide/user-guide' },
              { text: '1. Overview Dashboard', link: '/guide/user-guide/overview' },
              { text: '2. Codebase Navigator', link: '/guide/user-guide/navigator' },
              { text: '3. Search & Inspector', link: '/guide/user-guide/search' },
              { text: '4. Git Repositories', link: '/guide/user-guide/git-repositories' },
              { text: '5. Local Paths & Vaults', link: '/guide/user-guide/local-paths' },
              { text: '6. Storage & PDF Ingestion', link: '/guide/user-guide/local-storage' },
              { text: '7. Settings & Discovery', link: '/guide/user-guide/settings' },
              { text: '8. Diagnostics & Logs', link: '/guide/user-guide/diagnostics' },
              { text: '9. Appearance & Themes', link: '/guide/user-guide/themes' }
            ]
          }
        ],
        '/architecture/': [
          {
            text: 'System Architecture',
            items: [
              { text: 'Architecture Overview', link: '/architecture/' },
              { text: 'System Design & Components', link: '/architecture/system-design' },
              { text: 'Data Pipeline & Ingestion', link: '/architecture/data-pipeline' },
              { text: 'MCP Protocol & Security', link: '/architecture/mcp-protocol' },
              { text: 'Database & Storage Schema', link: '/architecture/database-schema' }
            ]
          }
        ],
        '/requirements/': [
          {
            text: 'Software Requirements (SRS)',
            items: [
              { text: 'SRS Specification', link: '/requirements/' },
              { text: 'Functional Requirements', link: '/requirements/functional' },
              { text: 'Non-Functional Requirements', link: '/requirements/non-functional' },
              { text: 'Verification & Test Matrix', link: '/requirements/verification' }
            ]
          }
        ],
        '/reference/': [
          {
            text: 'Reference Manual',
            items: [
              { text: 'MCP Tools & Resources', link: '/reference/mcp-tools' },
              { text: 'Admin REST API', link: '/reference/rest-api' },
              { text: 'Developer & Contributor Guide', link: '/reference/developer' }
            ]
          }
        ]
      },
      socialLinks: [
        { icon: 'github', link: 'https://github.com/spelech/contextcortex' }
      ],
      footer: {
        message: 'Released under the MIT License.',
        copyright: 'Copyright © 2025-2026 Steven T. Pelech.'
      },
      search: {
        provider: 'local'
      }
    },
    mermaid: {
      fontFamily: 'var(--vp-font-family-base), -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      flowchart: {
        htmlLabels: true,
        padding: 16,
        wrappingWidth: 260
      },
      sequence: {
        boxMargin: 10,
        boxTextMargin: 8,
        noteMargin: 10,
        messageMargin: 35,
        width: 180
      }
    }
  })
)
