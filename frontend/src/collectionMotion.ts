// Keep a departing card in its visible grid cell while siblings move around it.
export function freezeLeavingItem(element: Element) {
  const item = element as HTMLElement
  const parent = item.parentElement
  if (!parent) return
  const bounds = item.getBoundingClientRect()
  const frame = parent.getBoundingClientRect()
  Object.assign(item.style, {
    left: `${bounds.left - frame.left + parent.scrollLeft - parent.clientLeft}px`,
    top: `${bounds.top - frame.top + parent.scrollTop - parent.clientTop}px`,
    width: `${bounds.width}px`,
    height: `${bounds.height}px`,
  })
  item.inert = true
}
