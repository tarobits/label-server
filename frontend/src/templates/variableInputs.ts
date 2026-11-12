import { t } from '../shared/i18n'
import type {
  Expression,
  TemplateDocument,
  TemplateField,
  VariableValue,
  ValueType,
} from './editor'
import { randomUUID } from '../shared/uuid'

import { validVariableName } from './variableNames'
export { validVariableName } from './variableNames'
export function initialValue(field: TemplateField): VariableValue {
  return (
    field.default ??
    (field.type === 'boolean' && field.required
      ? false
      : field.type && field.type !== 'text'
        ? null
        : '')
  )
}
export function missingValue(value: VariableValue | undefined) {
  return value == null || (typeof value === 'string' && !value.trim())
}
export function displayValue(value: VariableValue) {
  return value === null ? '' : typeof value === 'object' ? 'Uploaded image' : String(value)
}
export function nextElementName(doc: TemplateDocument, kind: string) {
  const names = new Set([
    ...doc.fields.map((f) => f.name),
    ...doc.elements.map((e) => e.logic_name),
    ...Object.keys(doc.logic?.variables ?? {}),
  ])
  let index = 1
  while (names.has(`${kind}${index}`)) index++
  return `${kind}${index}`
}
export function setFieldType(doc: TemplateDocument, field: TemplateField, type: ValueType) {
  if ((field.type ?? 'text') === type) return
  upgradeDocument(doc)
  field.type = type
  field.default = type === 'text' ? '' : null
  field.sample =
    type === 'text'
      ? t('templatePreviewInputs.example')
      : type === 'number'
        ? 0
        : type === 'boolean'
          ? false
          : null
  delete field.minimum
  delete field.maximum
  delete field.min_length
  delete field.max_length
  for (const example of doc.preview_examples ?? []) example.data[field.name] = field.sample
}
export function upgradeDocument(doc: TemplateDocument) {
  const invalid = doc.fields.find((f) => !validVariableName(f.name))
  if (invalid)
    throw new Error(
      `Rename variable “${invalid.name}” before using typed variables. Use up to 40 letters, numbers or underscores, starting with a letter, and avoid reserved names.`,
    )
  doc.version = 2
  for (const element of doc.elements) element.logic_name ||= nextElementName(doc, element.kind)
  for (const input of doc.fields) input.type ??= 'text'
}
export function visitReferences(
  doc: TemplateDocument,
  visit: (reference: Extract<Expression, { kind: 'reference' }>) => void,
) {
  function walk(expression: Expression) {
    if (expression.kind === 'reference') visit(expression)
    else if (expression.kind === 'call') expression.arguments.forEach(walk)
  }
  Object.values(doc.logic?.variables ?? {}).forEach(walk)
  doc.logic?.bindings.forEach((binding) => walk(binding.expression))
}
export function copyExpression(expression: Expression): Expression {
  const copy = { ...expression, node_id: randomUUID(), span: null }
  if (copy.kind === 'call') copy.arguments = copy.arguments.map(copyExpression)
  return copy
}
export function renameField(doc: TemplateDocument, field: TemplateField, name: string) {
  if (name === field.name) return
  if (
    (doc.version === 2 ? !validVariableName(name) : !/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) ||
    doc.fields.some((f) => f !== field && f.name === name) ||
    Object.hasOwn(doc.logic?.variables ?? {}, name) ||
    (doc.version === 2 && doc.elements.some((element) => element.logic_name === name))
  )
    throw new Error(
      'Choose a unique variable name starting with a letter. Reserved names cannot be used in logic.',
    )
  const previous = field.name
  for (const example of doc.preview_examples ?? []) {
    if (Object.hasOwn(example.data, previous)) {
      example.data[name] = example.data[previous]!
      delete example.data[previous]
    }
  }
  visitReferences(doc, (reference) => {
    if (reference.name === previous) reference.name = name
  })
  for (const element of doc.elements) {
    if (!element.literal_content)
      element.content = element.content.replace(
        /\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}/g,
        (token, symbol) => (symbol === previous ? `{{${name}}}` : token),
      )
  }
  field.name = name
}
