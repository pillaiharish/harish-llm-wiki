import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: "Harish LLM Wiki",
  description: "Personal static learning wiki",
  
  // Clean URLs (no .html)
  cleanUrls: true,
  
  // Output directory (relative to docs/)
  outDir: '../../dist',
  
  // Ignore dead links since resource/concept pages are generated dynamically
  ignoreDeadLinks: true,
  
  // Theme configuration
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Resources', link: '/resources/' },
      { text: 'Timeline', link: '/timeline' },
      { text: 'Concepts', link: '/concepts/' },
      { text: 'Tags', link: '/tags/' },
      { text: 'Gaps', link: '/gaps' }
    ],

    sidebar: {
      '/resources/': [
        {
          text: 'Resources',
          items: [
            { text: 'All Resources', link: '/resources/' },
          ]
        }
      ],
      '/concepts/': [
        {
          text: 'Concepts',
          items: [
            { text: 'All Concepts', link: '/concepts/' },
          ]
        }
      ],
      '/tags/': [
        {
          text: 'Tags',
          items: [
            { text: 'All Tags', link: '/tags/' },
          ]
        }
      ]
    },

    socialLinks: [
      // Add your social links here if desired
    ],
    
    search: {
      provider: 'local'
    },
    
    footer: {
      message: 'Generated with Harish LLM Wiki',
      copyright: 'Copyright © 2024-2026'
    },
    
    editLink: {
      pattern: 'https://github.com/pillaiharish/harish-llm-wiki/edit/main/site/docs/:path',
      text: 'Edit this page on GitHub'
    }
  },
  
  // Markdown configuration
  markdown: {
    lineNumbers: true,
    config: (md) => {
      // Add custom markdown plugins here if needed
    }
  },
  
  // Head tags
  head: [
    ['meta', { name: 'theme-color', content: '#3c3c3c' }],
    ['meta', { name: 'og:type', content: 'website' }],
    ['meta', { name: 'og:title', content: 'Harish LLM Wiki' }],
    ['meta', { name: 'og:description', content: 'Personal static learning wiki' }],
  ]
})
