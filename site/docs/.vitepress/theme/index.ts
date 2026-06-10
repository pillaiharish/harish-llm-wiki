import DefaultTheme from 'vitepress/theme'
import GraphExplorer from './components/GraphExplorer.vue'
import GraphifyExplorer from './components/GraphifyExplorer.vue'
import SearchExplorer from './components/SearchExplorer.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }: { app: any }) {
    app.component('GraphExplorer', GraphExplorer)
    app.component('GraphifyExplorer', GraphifyExplorer)
    app.component('SearchExplorer', SearchExplorer)
  },
}
