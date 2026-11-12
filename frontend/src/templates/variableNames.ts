// Logic identifiers are language-independent and usable outside the browser.
const reserved = new Set([
  'let',
  'true',
  'false',
  'null',
  'and',
  'or',
  'not',
  'if',
  'image',
  'filled',
  'min',
  'max',
  'abs',
  'round',
  'label',
])

export function validVariableName(name: string) {
  return /^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(name) && !reserved.has(name)
}
