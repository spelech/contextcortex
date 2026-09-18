import DefaultTheme from 'vitepress/theme'
import { onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vitepress'
import './custom.css'
import { setupMermaidObserver, initMermaidPanZoom } from './mermaid-panzoom'

export default {
  extends: DefaultTheme,
  setup() {
    const route = useRoute()

    onMounted(() => {
      setupMermaidObserver()
    })

    watch(
      () => route.path,
      () => {
        nextTick(() => {
          setTimeout(initMermaidPanZoom, 200)
        })
      }
    )
  }
}
