import { defineConfig } from 'vitepress'
import { withSidebar } from 'vitepress-sidebar'
import { withMermaid } from 'vitepress-plugin-mermaid'

const baseConfig = {
  title: '.NET Full-Stack Mastery',
  description: 'Senior .NET interview prep guide — 11 chapters, 131 topics',
  base: '/master-guide/',
  srcDir: '.',
  cleanUrls: true,
  ignoreDeadLinks: true,
  lastUpdated: true,

  // Each folder's README.md acts as the folder's index page
  rewrites: {
    'README.md': 'index.md',
    ':a/README.md': ':a/index.md',
    ':a/:b/README.md': ':a/:b/index.md',
    ':a/:b/:c/README.md': ':a/:b/:c/index.md',
    ':a/:b/:c/:d/README.md': ':a/:b/:c/:d/index.md'
  },

  themeConfig: {
    search: { provider: 'local' },
    outline: { level: [2, 4] },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/ahmed-developer7/master-guide' }
    ],
    editLink: {
      pattern: 'https://github.com/ahmed-developer7/master-guide/edit/main/:path',
      text: 'Edit this page on GitHub'
    },
    footer: {
      message: 'Built with VitePress',
      copyright: 'Ahmed Liaqat'
    }
  },

  markdown: {
    lineNumbers: true
  }
}

const sidebarOptions = {
  documentRootPath: '.',
  collapsed: true,
  capitalizeFirst: true,
  useTitleFromFileHeading: true,
  useTitleFromFrontmatter: true,
  useFolderTitleFromIndexFile: true,
  sortMenusByName: true,
  excludePattern: [
    '_templates/**',
    '_reports/**',
    'scripts/**',
    'STUDY-PLAN.md',
    'PUBLISH-PLAN.md',
    'package.json',
    'mkdocs.yml',
    'requirements.txt'
  ]
}

export default withMermaid(defineConfig(withSidebar(baseConfig, sidebarOptions)))
