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
      { text: 'Topics', link: '/topics/' },
      { text: 'Learn', link: '/learn/' },
      { text: 'Explorer', link: '/explorer/' },
      { text: 'Graph', link: '/graph/' },
      { text: 'Review', link: '/review/' },
      { text: 'Revision', link: '/revision/' },
      { text: 'Sources', link: '/sources/' },
      { text: 'Timeline', link: '/timeline' },
      { text: 'Concepts', link: '/concepts/' },
      { text: 'Tags', link: '/tags/' },
      { text: 'Gaps', link: '/gaps' },
      { text: 'Chunks', link: '/chunks/' }
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
      '/topics/': [
        {
          text: 'Topics',
          items: [
            { text: 'Topic Map', link: '/topics/' },
          ]
        }
      ],
      '/learn/': [
        {
          text: 'Learn',
          items: [
            { text: 'All Chapters', link: '/learn/' },
          ]
        }
      ],
      '/review/': [
        {
          text: 'Review',
          items: [
            { text: 'Dashboard', link: '/review/' },
            { text: 'Weak Notes', link: '/review/weak-notes' },
            { text: 'Fallback Notes', link: '/review/fallback-notes' },
            { text: 'Failed Notes', link: '/review/failed-notes' },
            { text: 'Missing Citations', link: '/review/missing-citations' },
            { text: 'Stale Notes', link: '/review/stale-notes' },
          ]
        }
      ],
      '/revision/': [
        {
          text: 'Revision',
          items: [
            { text: 'Overview', link: '/revision/' },
            { text: 'Questions', link: '/revision/questions' },
            { text: 'Flashcards', link: '/revision/flashcards' },
            { text: 'Weak Areas', link: '/revision/weak-areas' },
            { text: 'By Topic', link: '/revision/by-topic' },
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
      ],
      '/graph/': [
        {
          text: 'Graph',
          items: [
            { text: 'Index', link: '/graph/' },
            { text: 'Viewer', link: '/graph/viewer' },
            { text: 'Resource relationships', link: '/graph/resource-relationships' },
          ]
        }
      ],
      '/chunks/': [
        {
          text: 'Chunks',
          items: [
            { text: 'Overview', link: '/chunks/' },
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
