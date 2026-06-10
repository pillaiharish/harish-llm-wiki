import DefaultTheme from 'vitepress/theme'
import GraphExplorer from './components/GraphExplorer.vue'
import GraphifyExplorer from './components/GraphifyExplorer.vue'
import IngestCommandBuilder from './components/IngestCommandBuilder.vue'
import SearchExplorer from './components/SearchExplorer.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }: { app: any }) {
    app.component('GraphExplorer', GraphExplorer)
    app.component('GraphifyExplorer', GraphifyExplorer)
    app.component('IngestCommandBuilder', IngestCommandBuilder)
    app.component('SearchExplorer', SearchExplorer)
  },
}
