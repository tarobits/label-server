import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { test } from 'node:test'
import { baseCompile } from '@intlify/message-compiler'
import { createI18n } from 'vue-i18n'
import ts from 'typescript'
import vm from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import { computed, ref } from 'vue'

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

test('editor help and permission labels switch language without changing permission IDs', () => {
  const { global } = createI18n({ legacy: false, locale: 'en', messages })
  function load(relative) {
    const exports = {}
    const code = ts.transpileModule(readFileSync(join(root, relative), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS },
    }).outputText
    vm.runInNewContext(code, { exports, require: () => ({ t: global.t }) })
    return exports
  }
  const { editorHelp } = load('frontend/src/templates/editorHelp.ts')
  const permissions = load('frontend/src/printing/printerPermissions.ts')
  const ids = permissions.printerPermissionOptions.map((option) => option.id)
  const english = editorHelp.autoLength.text
  global.locale.value = 'de'
  assert.match(editorHelp.autoLength.text, /Bandverbrauch/)
  assert.equal(permissions.printerPermissionLabel('printer.view'), 'Drucker anzeigen')
  assert.deepEqual(
    permissions.printerPermissionOptions.map((option) => option.id),
    ids,
  )
  assert.equal(permissions.printerPermissionLabel('unknown.permission'), 'unknown.permission')
  assert.ok(
    !permissions.permissionOptions(true).some((option) => option.id === 'printer.emergency_stop'),
  )
  global.locale.value = 'en'
  assert.equal(editorHelp.autoLength.text, english)
  assert.equal(permissions.printerPermissionLabel('printer.view'), 'View printer')
})

test('upload retries remain functional when the language changes after a failed upload', async () => {
  const { global } = createI18n({ legacy: false, locale: 'en', messages })
  const file = join(root, 'frontend/src/components/AssetUpload.vue')
  const { descriptor } = parse(readFileSync(file, 'utf8'))
  const script = compileScript(descriptor, { id: 'test-upload' }).content
  const code = ts.transpileModule(script, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText
  class ApiError extends Error {}
  let calls = 0
  const { default: component } = (() => {
    const exports = {}
    vm.runInNewContext(code, {
      exports,
      URLSearchParams,
      require: (name) => {
        if (name === 'vue')
          return { computed, ref, defineComponent: (value) => value, onUnmounted: () => {} }
        if (name.endsWith('/i18n')) return { t: global.t }
        if (name.endsWith('/api'))
          return {
            ApiError,
            errorMessage: (error) => error.message,
            api: async () => {
              if (++calls === 1) throw new ApiError('temporary failure')
            },
          }
        if (name.endsWith('/auth'))
          return {
            useAuthStore: () => ({ user: { id: 'owner', is_admin: true }, can: () => true }),
          }
        if (name.endsWith('/workspace'))
          return { useWorkspaceStore: () => ({ refresh: async () => {} }) }
        return {}
      },
    })
    return exports
  })()
  const state = component.setup({ kind: 'images' }, { expose: () => {} })
  const fileValue = { name: 'My image {name}.png', size: 123 }
  state.choose({ target: { files: [fileValue] } })
  await state.upload()
  assert.equal(state.files.value[0].state, 'Failed')
  assert.equal(state.uploading.value, false)
  global.locale.value = 'de'
  await state.upload()
  assert.equal(state.files.value[0].state, 'Uploaded')
  assert.equal(state.remaining.value.length, 0)
  assert.equal(state.files.value[0].file.name, fileValue.name)
  await state.upload()
  assert.equal(calls, 2, 'completed uploads must not be sent again')
})

test('catalogs have matching nested keys and valid Vue I18n messages', () => {
  // JSON.parse silently discards duplicate keys, hiding otherwise valid translations.
  for (const locale of ['en', 'de']) {
    const source = ts.parseJsonText(
      `${locale}.json`,
      readFileSync(join(root, 'lang', `${locale}.json`), 'utf8'),
    )
    function visit(node) {
      if (ts.isObjectLiteralExpression(node)) {
        const names = node.properties.map((property) => property.name?.getText(source))
        assert.equal(new Set(names).size, names.length, `${locale}: duplicate catalog key`)
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
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

function untranslatedErrorLiterals(source) {
  const file = ts.createSourceFile('source.ts', source, ts.ScriptTarget.Latest, true)
  const found = []
  function visit(node) {
    if (
      (ts.isStringLiteral(node) ||
        ts.isNoSubstitutionTemplateLiteral(node) ||
        ts.isTemplateHead(node) ||
        ts.isTemplateTail(node)) &&
      /[A-Za-z]{2,}[ ,;:!?]+[A-Za-z]{2,}/.test(node.text)
    )
      found.push(node.text)
    ts.forEachChild(node, visit)
  }
  visit(file)
  return found
}

test('shared request and outage messages cannot bypass the catalogs', () => {
  // These modules have no user content or prose protocol constants to exempt.
  for (const file of ['api.ts', 'serverConnection.ts']) {
    assert.deepEqual(
      untranslatedErrorLiterals(readFileSync(join(root, 'frontend/src/shared', file), 'utf8')),
      [],
      file,
    )
  }
  assert.equal(untranslatedErrorLiterals("throw new Error('Please try again')").length, 1)
  assert.equal(
    untranslatedErrorLiterals('return `Request failed (${status}). Try again.`').length,
    2,
  )
  assert.deepEqual(
    untranslatedErrorLiterals("return t('errors.connection') // English comment"),
    [],
  )
})

test('real request helper localizes failures, preserves detail and allows later requests', async () => {
  const { global } = createI18n({ legacy: false, locale: 'de', fallbackLocale: 'en', messages })
  let response = new Response('{}', { status: 403 })
  const requests = []
  const exports = {}
  const source = readFileSync(join(root, 'frontend/src/shared/api.ts'), 'utf8')
  vm.runInNewContext(
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText,
    {
      exports,
      Error,
      Blob,
      AbortSignal,
      fetch: async (_url, options) => {
        requests.push(options)
        return response
      },
      require: (name) => {
        if (name === './i18n')
          return {
            t: global.t,
            locale: global.locale,
            browserLanguage: { value: 'de' },
          }
        if (name === './serverConnection')
          return {
            checkServer: async () => true,
            serverUnavailable: { value: false },
          }
        throw new Error(`Unexpected import: ${name}`)
      },
    },
  )
  await assert.rejects(exports.api('/test'), {
    message: 'Du hast keine Berechtigung für diese Aktion.',
  })
  assert.equal(requests[0].headers['Accept-Language'], 'de')
  global.locale.value = 'en'
  response = new Response('{}', { status: 403 })
  await assert.rejects(exports.api('/test'), {
    message: 'You do not have permission to perform this action.',
  })
  response = new Response(JSON.stringify({ detail: 'User content {name} <script>' }), {
    status: 400,
  })
  await assert.rejects(exports.api('/test'), { message: 'User content {name} <script>' })
  response = new Response('{"ok":true}')
  assert.equal((await exports.api('/test')).ok, true)
  assert.equal(requests.length, 4) // Mutations/errors must not acquire automatic retries.
})
