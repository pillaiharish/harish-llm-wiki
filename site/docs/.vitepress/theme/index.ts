import DefaultTheme from 'vitepress/theme'
import { h } from 'vue'
import ControlPlaneStatus from './components/ControlPlaneStatus.vue'
import GraphExplorer from './components/GraphExplorer.vue'
import GraphifyExplorer from './components/GraphifyExplorer.vue'
import IngestCommandBuilder from './components/IngestCommandBuilder.vue'
import RuntimeIdentityProvider from './components/RuntimeIdentityProvider.vue'
import RuntimeIdentitySettings from './components/RuntimeIdentitySettings.vue'
import SearchExplorer from './components/SearchExplorer.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  Layout() {
    return h(DefaultTheme.Layout, null, {
      'layout-top': () => h(RuntimeIdentityProvider),
    })
  },
  enhanceApp({ app }: { app: any }) {
    app.component('ControlPlaneStatus', ControlPlaneStatus)
    app.component('GraphExplorer', GraphExplorer)
    app.component('GraphifyExplorer', GraphifyExplorer)
    app.component('IngestCommandBuilder', IngestCommandBuilder)
    app.component('RuntimeIdentitySettings', RuntimeIdentitySettings)
    app.component('SearchExplorer', SearchExplorer)
  },
}
