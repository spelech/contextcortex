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
    themeConfig: {
      logo: '/assets/theme_midnight_blue.png',
      siteTitle: 'ContextCortex',
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
              { text: 'User Guide (Screenshots)', link: '/guide/user-guide' },
              { text: 'Configuration', link: '/guide/configuration' }
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
        copyright: 'Copyright © 2025-2026 Steven T. Pelech. ASD-STE100 Compliant Documentation.'
      },
      search: {
        provider: 'local'
      }
    },
    mermaid: {
      // Mermaid configuration
    }
  })
)
