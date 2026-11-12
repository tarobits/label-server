// Native dialogs can carry :focus-visible through programmatic focus changes.
// Preserve that focus for assistive technology, while tracking how the user is
// interacting so dialog headings and their openers do not gain pointer rings.
function setMethod(method: 'pointer' | 'keyboard') {
  document.documentElement.dataset.inputMethod = method
}

setMethod('pointer')
document.addEventListener('pointerdown', () => setMethod('pointer'), true)
document.addEventListener(
  'keydown',
  (event) => {
    if (!['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(event.key)) setMethod('keyboard')
  },
  true,
)
// Keyboard and assistive-technology activation can dispatch clicks without a
// preceding key event. Pointer clicks have a positive detail count.
document.addEventListener(
  'click',
  (event) => {
    if (event.detail === 0) setMethod('keyboard')
  },
  true,
)
