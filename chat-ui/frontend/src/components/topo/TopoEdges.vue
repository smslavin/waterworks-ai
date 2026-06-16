<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useTopologyStore } from '@/stores/topology'
import { useUIStore } from '@/stores/ui'

const topo = useTopologyStore()
const ui   = useUIStore()
const svgEl = ref<SVGSVGElement | null>(null)

function drawEdges() {
  const svg    = svgEl.value
  const canvas = document.getElementById('topo-canvas')
  if (!svg || !canvas) return

  const cr = canvas.getBoundingClientRect()
  svg.innerHTML = ''

  function centerOf(id: string) {
    const el = document.querySelector<HTMLElement>(`[data-id="${id}"] .topo-node-circle`)
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { x: r.left - cr.left + r.width / 2, y: r.top - cr.top + r.height / 2 }
  }

  for (const edge of topo.edges) {
    const pa = centerOf(edge.from)
    const pb = centerOf(edge.to)
    if (!pa || !pb) continue

    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line')
    line.setAttribute('x1', String(pa.x))
    line.setAttribute('y1', String(pa.y))
    line.setAttribute('x2', String(pb.x))
    line.setAttribute('y2', String(pb.y))
    line.setAttribute('stroke', '#3f3f46')
    line.setAttribute('stroke-width', '1.5')
    line.setAttribute('stroke-dasharray', '4 5')
    svg.appendChild(line)
  }
}

let ro: ResizeObserver | null = null

onMounted(() => {
  nextTick(drawEdges)
  const canvas = document.getElementById('topo-canvas')
  if (canvas) {
    ro = new ResizeObserver(drawEdges)
    ro.observe(canvas)
  }
})

onUnmounted(() => ro?.disconnect())

watch(() => ui.activeNodeId, () => nextTick(drawEdges))
watch(() => topo.nodes, () => nextTick(drawEdges), { deep: true })
</script>

<template>
  <svg ref="svgEl" class="topo-edges" aria-hidden="true" />
</template>

<style scoped>
.topo-edges {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 1;
}
</style>
