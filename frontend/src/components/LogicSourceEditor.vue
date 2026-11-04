<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Compartment, EditorState, Transaction } from '@codemirror/state'
import {
  EditorView,
  keymap,
  lineNumbers,
  highlightActiveLine,
  highlightActiveLineGutter,
  drawSelection,
  hoverTooltip,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import {
  StreamLanguage,
  HighlightStyle,
  syntaxHighlighting,
  bracketMatching,
  syntaxTree,
} from '@codemirror/language'
import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  snippetCompletion,
  type CompletionContext,
  type Completion,
} from '@codemirror/autocomplete'
import { lintGutter, setDiagnostics, lintKeymap } from '@codemirror/lint'
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search'
import { tags } from '@lezer/highlight'
import type { TemplateDocument } from '../editor'
import type { LogicCatalog, SourceDiagnostic } from '../logicGraph'
import { referenceEntries } from '../logicReference'

const props = defineProps<{
  source: string
  catalog: LogicCatalog
  document: TemplateDocument
  diagnostics: SourceDiagnostic[]
  disabled?: boolean
  active: boolean
}>()
const emit = defineEmits<{ change: [source: string]; help: [id: string] }>()
const host = ref<HTMLElement | null>(null),
  status = ref('Ln 1, Col 1'),
  limit = ref('')
let view: EditorView | undefined
const readOnly = new Compartment()
const language = StreamLanguage.define({
  token(stream) {
    if (stream.eatSpace()) return null
    if (stream.match('//')) {
      stream.skipToEnd()
      return 'comment'
    }
    if (stream.match(/"(?:[^"\\]|\\.)*"/)) return 'string'
    if (stream.match(/(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?/)) return 'number'
    if (stream.match(/\b(?:true|false|null)\b/)) return 'atom'
    if (stream.match(/\b(?:let|and|or|not)\b/)) return 'keyword'
    if (stream.match(/[A-Za-z][A-Za-z0-9_]*/))
      return stream.match(/^\s*\(/, false) ? 'function' : 'variableName'
    if (stream.match(/[+*/<>=!\-]+/)) return 'operator'
    stream.next()
    return null
  },
  tokenTable: { function: tags.function(tags.variableName), atom: tags.bool },
  languageData: { commentTokens: { line: '//' }, closeBrackets: { brackets: ['(', '"'] } },
})
const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: 'var(--accent-hover)' },
  { tag: tags.number, color: 'var(--link-hover)' },
  { tag: tags.bool, color: 'var(--link-hover)' },
  { tag: tags.string, color: 'var(--success-text)' },
  { tag: tags.function(tags.variableName), color: 'var(--accent-hover)' },
  { tag: tags.variableName, color: 'var(--ink)' },
  { tag: tags.operator, color: 'var(--text-secondary)' },
  { tag: tags.comment, color: 'var(--muted)', fontStyle: 'italic' },
])
function helpFor(symbol: string) {
  const entries = referenceEntries(props.catalog, props.document)
  const property = symbol.split('.')[1]
  return (
    entries.find((entry) => entry.id === (property ? `property:${property}` : `input:${symbol}`)) ??
    entries.find((entry) => entry.id === `operation:${symbol}`) ??
    entries.find(
      (entry) =>
        entry.id ===
        (symbol === 'let' || Object.hasOwn(props.catalog.types, symbol)
          ? 'variables'
          : symbol === 'image'
            ? 'type:image'
            : 'source'),
    )!
  )
}
function complete(context: CompletionContext) {
  if (/comment|string/i.test(syntaxTree(context.state).resolveInner(context.pos, -1).name))
    return null
  const word = context.matchBefore(/[A-Za-z][A-Za-z0-9_.]*/)
  if (!word && !context.explicit) return null
  const fragment = word?.text ?? '',
    split = fragment.indexOf('.')
  let options: Completion[]
  if (split >= 0) {
    const alias = fragment.slice(0, split)
    options = Object.entries(props.catalog.targets[alias]?.properties ?? {}).map(
      ([label, type]) => ({
        label,
        type: 'property',
        detail: type,
        info: helpFor(`${alias}.${label}`).summary,
      }),
    )
    return { from: (word?.from ?? context.pos) + split + 1, options, validFor: /^[A-Za-z0-9_]*$/ }
  }
  const inputs = props.document.fields.map((field) => ({
    label: field.name,
    type: 'variable',
    detail: field.type ?? 'text',
    info: field.label,
  }))
  const declared = [
    ...context.state.doc.toString().matchAll(/\blet\s+([A-Za-z][A-Za-z0-9_]*)\s*=/g),
  ].map((match) => match[1]!)
  options = [
    ...inputs,
    ...[...new Set(declared)]
      .filter((name) => !inputs.some((input) => input.label === name))
      .map((label) => ({
        label,
        type: 'variable',
        detail: props.catalog.types[label] ?? 'intermediate',
      })),
    ...Object.keys(props.catalog.targets).map((label) => ({
      label,
      type: 'class',
      detail: 'output target',
    })),
    ...props.catalog.operations.map((operation) =>
      snippetCompletion(
        `${operation.name}(${Array.from({ length: operation.minimum_arguments }, (_, index) => '${' + (index + 1) + ':' + (operation.signature === 'boolean' || (operation.name === 'if' && index === 0) ? 'false' : '0') + '}').join(', ')})`,
        {
          label: operation.name,
          type: 'function',
          detail: `${operation.minimum_arguments} argument${operation.minimum_arguments === 1 ? '' : 's'}`,
          info: operation.description,
        },
      ),
    ),
    ...['true', 'false', 'null', 'and', 'or', 'not'].map((label) => ({ label, type: 'keyword' })),
    snippetCompletion('let ${1:name} = ${2:0};', {
      label: 'let',
      type: 'keyword',
      info: 'Declare a named intermediate value.',
    }),
    snippetCompletion('image("${1:asset-id}")', {
      label: 'image',
      type: 'function',
      info: 'An uploaded image asset reference.',
    }),
  ]
  return { from: word?.from ?? context.pos, options, validFor: /^[A-Za-z0-9_]*$/ }
}
const theme = EditorView.theme(
  {
    '&': { backgroundColor: 'var(--surface-deepest)', color: 'var(--ink)', fontSize: '14px' },
    '&.cm-focused': { outline: '2px solid var(--accent-hover)', outlineOffset: '-2px' },
    '.cm-content': {
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      padding: '12px 0',
      caretColor: 'var(--ink)',
    },
    '.cm-scroller': { overflow: 'auto', minHeight: '360px', maxHeight: '65vh', lineHeight: '1.6' },
    '.cm-gutters': {
      backgroundColor: 'var(--surface)',
      color: 'var(--muted)',
      borderRight: '1px solid var(--line)',
    },
    '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--overlay)' },
    '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': {
      backgroundColor: 'var(--surface-secondary)',
    },
    '.cm-cursor': { borderLeftColor: 'var(--ink)' },
    '.cm-tooltip': {
      border: '1px solid var(--border-strong)',
      backgroundColor: 'var(--surface)',
      color: 'var(--ink)',
      maxWidth: 'min(360px, 85vw)',
    },
    '.cm-tooltip-autocomplete > ul > li[aria-selected]': {
      backgroundColor: 'var(--accent)',
      color: 'var(--ink)',
    },
    '.cm-panels': { backgroundColor: 'var(--surface)', color: 'var(--ink)' },
    '.cm-searchMatch': {
      backgroundColor: 'var(--accent-fill)',
      outline: '1px solid var(--accent-hover)',
    },
    '.cm-diagnostic-error': { borderLeftColor: 'var(--danger-text)' },
    '.cm-lintRange-error': {
      textDecoration: 'underline wavy var(--danger-text)',
      backgroundImage: 'none',
    },
  },
  { dark: true },
)
function updateDiagnostics() {
  if (!view) return
  const length = view.state.doc.length
  view.dispatch(
    setDiagnostics(
      view.state,
      props.diagnostics.map((issue) => ({
        ...issue,
        from: Math.min(issue.from, length),
        to: Math.min(Math.max(issue.from, issue.to), length),
      })),
    ),
  )
}
onMounted(() => {
  view = new EditorView({
    parent: host.value!,
    doc: props.source,
    extensions: [
      lineNumbers(),
      lintGutter(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      drawSelection(),
      EditorView.lineWrapping,
      history(),
      bracketMatching(),
      closeBrackets(),
      highlightSelectionMatches(),
      language,
      syntaxHighlighting(highlight),
      theme,
      readOnly.of([
        EditorState.readOnly.of(!!props.disabled),
        EditorView.editable.of(!props.disabled),
      ]),
      EditorView.contentAttributes.of({
        'aria-label': 'Logic source',
        'aria-multiline': 'true',
        spellcheck: 'false',
      }),
      keymap.of([
        ...closeBracketsKeymap,
        ...defaultKeymap,
        ...historyKeymap,
        ...searchKeymap,
        ...lintKeymap,
        { key: 'Mod-]', run: indentWithTab.run },
      ]),
      autocompletion({ override: [complete] }),
      hoverTooltip((editor, position) => {
        if (/comment|string/i.test(syntaxTree(editor.state).resolveInner(position, -1).name))
          return null
        const line = editor.state.doc.lineAt(position)
        let from = position,
          to = position
        while (from > line.from && /[\w.]/.test(editor.state.sliceDoc(from - 1, from))) from--
        while (to < line.to && /[\w.]/.test(editor.state.sliceDoc(to, to + 1))) to++
        if (from === to) return null
        const entry = helpFor(editor.state.sliceDoc(from, to))
        return {
          pos: from,
          end: to,
          above: true,
          create() {
            const dom = document.createElement('div')
            dom.className = 'logic-code-hover'
            const text = document.createElement('p')
            text.textContent = entry.summary
            dom.append(text)
            const button = document.createElement('button')
            button.type = 'button'
            button.textContent = 'Open reference'
            button.onclick = () => emit('help', entry.id)
            dom.append(button)
            return { dom }
          },
        }
      }),
      EditorState.changeFilter.of((transaction) => {
        if ([...transaction.newDoc.toString()].length <= 16384) return true
        limit.value = 'Logic source is limited to 16,384 characters.'
        return false
      }),
      EditorView.updateListener.of((update) => {
        const line = update.state.doc.lineAt(update.state.selection.main.head)
        status.value = `Ln ${line.number}, Col ${update.state.selection.main.head - line.from + 1}`
        if (
          update.docChanged &&
          !update.transactions.some(
            (transaction) => transaction.annotation(Transaction.addToHistory) === false,
          )
        ) {
          limit.value = ''
          emit('change', update.state.doc.toString())
        }
      }),
    ],
  })
  updateDiagnostics()
})
watch(
  () => props.source,
  (source) => {
    if (!view || view.state.doc.toString() === source) return
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: source },
      annotations: Transaction.addToHistory.of(false),
    })
  },
)
watch(
  () => props.disabled,
  (disabled) =>
    view?.dispatch({
      effects: readOnly.reconfigure([
        EditorState.readOnly.of(!!disabled),
        EditorView.editable.of(!disabled),
      ]),
    }),
)
watch(() => props.diagnostics, updateDiagnostics, { deep: true })
watch(
  () => props.active,
  (active) => {
    if (active) view?.requestMeasure()
  },
)
onBeforeUnmount(() => view?.destroy())
function focusIssue(issue: SourceDiagnostic) {
  view?.dispatch({
    selection: { anchor: Math.min(issue.from, view.state.doc.length) },
    scrollIntoView: true,
  })
  view?.focus()
}
</script>
<template>
  <div class="source-editor">
    <div ref="host" class="code-host" />
    <div class="source-status">
      <span>{{ status }}</span
      ><span v-if="disabled">Read-only</span>
    </div>
    <p v-if="limit" class="alert warning" role="status">{{ limit }}</p>
    <div v-if="diagnostics.length" class="source-diagnostics" role="alert">
      <button
        v-for="(issue, index) in diagnostics"
        :key="index"
        class="text-button"
        @click="focusIssue(issue)"
      >
        Line {{ issue.line }}, column {{ issue.column }}: {{ issue.message }}
      </button>
    </div>
  </div>
</template>
<style scoped>
.code-host {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
.source-status {
  display: flex;
  justify-content: space-between;
  color: var(--muted);
  margin-top: 8px;
  font-variant-numeric: tabular-nums;
}
.source-diagnostics {
  display: grid;
  gap: 8px;
  padding-block: 12px;
}
.source-diagnostics button {
  justify-content: start;
  text-align: left;
  color: var(--danger-text);
  overflow-wrap: anywhere;
}
:deep(.logic-code-hover) {
  padding: 12px;
}
:deep(.logic-code-hover p) {
  margin: 0 0 12px;
}
</style>
