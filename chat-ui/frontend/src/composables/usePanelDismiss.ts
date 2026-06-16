import { onMounted, onUnmounted } from 'vue'
import { useUIStore } from '@/stores/ui'

export function usePanelDismiss() {
  const ui = useUIStore()

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') ui.dismissPanels()
  }

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onUnmounted(() => window.removeEventListener('keydown', onKeydown))
}
