import DefaultTheme from 'vitepress/theme'
import GraphExplorer from './components/GraphExplorer.vue'
import SearchExplorer from './components/SearchExplorer.vue'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }: { app: any }) {
    app.component('GraphExplorer', GraphExplorer)
    app.component('SearchExplorer', SearchExplorer)
  },
}
