export interface Span { at: number; frames: number }
export type EditEdge = 'move' | 'start' | 'end'

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value))
}

function closest(values: number[], target: number, fallback: number) {
  return values.reduce((best, value) => Math.abs(value-target)<Math.abs(best-target) ? value : best, fallback)
}

export function moveStart(target: number, span: Span, length: number, neighbors: Span[], markers: number[], tolerance: number) {
  const slots: [number,number][] = []
  let from = 0
  for (const following of [...neighbors,{at:length,frames:0}].sort((a,b)=>a.at-b.at)) {
    const last = following.at-span.frames
    if (last>=from) slots.push([from,last])
    from = Math.max(from,following.at+following.frames)
  }
  const legal = slots.map(([lo,hi])=>clamp(target,lo,hi))
  if (!legal.length) return span.at
  const bounded = closest(legal.slice(1),target,legal[0])
  if (!tolerance) return bounded
  const eligible = markers.flatMap(marker=>[marker,marker-span.frames]).filter(at=>
    Math.abs(target-at)<=tolerance && slots.some(([lo,hi])=>at>=lo && at<=hi))
  if (!eligible.length) return bounded
  return closest(eligible.slice(1),target,eligible[0])
}

export function trimBoundary(target: number, lo: number, hi: number, markers: number[], tolerance: number) {
  const bounded = clamp(target,lo,hi)
  if (!tolerance) return bounded
  const eligible = markers.filter(marker=>marker>=lo && marker<=hi && Math.abs(target-marker)<=tolerance)
  return eligible.length ? closest(eligible.slice(1),target,eligible[0]) : bounded
}
