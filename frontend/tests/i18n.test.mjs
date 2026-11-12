import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { test } from 'node:test'
import { baseCompile } from '@intlify/message-compiler'
import { createI18n } from 'vue-i18n'

const root = fileURLToPath(new URL('../../', import.meta.url))
const messages = Object.fromEntries(
  ['en', 'de'].map((locale) => [
    locale,
    JSON.parse(readFileSync(join(root, 'lang', `${locale}.json`), 'utf8')),
  ]),
)
function flatten(value, prefix = '', result = {}) {
  for (const [key, child] of Object.entries(value)) {
    assert.match(key, /^[A-Za-z0-9]+$/, `Use nested objects instead of dotted keys: ${key}`)
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof child === 'object' && child !== null) flatten(child, path, result)
    else {
      assert.equal(typeof child, 'string', path)
      assert.ok(child.length, path)
      result[path] = child
    }
  }
  return result
}
const flat = Object.fromEntries(
  Object.entries(messages).map(([locale, data]) => [locale, flatten(data)]),
)

test('catalogs have matching nested keys and valid Vue I18n messages', () => {
  assert.deepEqual(Object.keys(flat.en).sort(), Object.keys(flat.de).sort())
  for (const [locale, catalog] of Object.entries(flat)) {
    for (const [key, text] of Object.entries(catalog)) {
      const errors = []
      baseCompile(text, { onError: (error) => errors.push(error.message) })
      assert.deepEqual(errors, [], `${locale}:${key}`)
    }
  }
  const parameters = (text) =>
    [...text.matchAll(/\{([A-Za-z_][A-Za-z_0-9]*)\}/g)].map((m) => m[1]).sort()
  for (const key of Object.keys(flat.en)) {
    assert.deepEqual(parameters(flat.en[key]), parameters(flat.de[key]), key)
  }
})

test('literal translation references resolve in both languages', () => {
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) visit(path)
      else if (/\.(vue|ts)$/.test(entry.name)) {
        const source = readFileSync(path, 'utf8')
        for (const match of source.matchAll(/(?:\$t|\bt)\(\s*['"]([A-Za-z0-9_.]+)['"]/g)) {
          assert.ok(match[1] in flat.en, `${path}: ${match[1]}`)
        }
      }
    }
  }
  visit(join(root, 'frontend/src'))
})

test('Vue I18n resolves nested keys and switches locale', () => {
  const { global } = createI18n({ legacy: false, locale: 'en', fallbackLocale: 'en', messages })
  assert.equal(global.t('account.language'), 'Language')
  global.locale.value = 'de'
  assert.equal(global.t('account.language'), 'Sprache')
  assert.equal(global.t('app.copyCount', { count: 1 }), '1 Kopie')
  assert.equal(global.t('app.copyCount', { count: 2 }), '2 Kopien')
  assert.equal(
    global.t('app.printersConnected', { connected: 1, total: 3 }),
    '1 von 3 Druckern verbunden',
  )
  for (const key of Object.keys(flat.de)) {
    assert.notEqual(global.t(key), key, `Unresolved German message: ${key}`)
  }
})
