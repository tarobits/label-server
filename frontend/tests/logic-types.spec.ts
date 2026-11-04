import { test, expect } from '@playwright/test'
import { canConnect, inputType, validateGraphTypes, type LogicCatalog } from '../src/logicGraph'
import type { LogicNode, TemplateDocument, VariableValue } from '../src/editor'

const catalog: LogicCatalog = {
  source: '',
  values: {},
  types: {},
  sample_error: null,
  targets: { label: { id: 'label', properties: { length_mm: 'number' } } },
  operations: [
    {
      name: 'if',
      minimum_arguments: 3,
      maximum_arguments: 3,
      signature: 'conditional',
      description: '',
    },
    ...['equal', 'not_equal'].map((name) => ({
      name,
      minimum_arguments: 2,
      maximum_arguments: 2,
      signature: 'equality' as const,
      description: '',
    })),
    ...['add', 'subtract', 'multiply', 'divide', 'min', 'max'].map((name) => ({
      name,
      minimum_arguments: 2,
      maximum_arguments: 2,
      signature: 'numeric' as const,
      description: '',
    })),
    ...['less', 'less_equal', 'greater', 'greater_equal'].map((name) => ({
      name,
      minimum_arguments: 2,
      maximum_arguments: 2,
      signature: 'comparison' as const,
      description: '',
    })),
    ...['and', 'or'].map((name) => ({
      name,
      minimum_arguments: 2,
      maximum_arguments: 2,
      signature: 'boolean' as const,
      description: '',
    })),
  ],
}
const doc: TemplateDocument = { version: 2, width_mm: 24, length_mm: 60, fields: [], elements: [] }
const values: VariableValue[] = ['text', 12, true, { image_asset: 'a'.repeat(64) }]
function node(id: string, extra: Partial<LogicNode>): LogicNode {
  return { id, kind: 'literal', type: 'number', x: 0, y: 0, inputs: [], defaults: [], ...extra }
}
for (const operation of ['if', 'equal', 'not_equal']) {
  test(`${operation} rejects every mismatched concrete type in either input order`, () => {
    for (const first of values)
      for (const second of values) {
        const source = node('source', { value: second })
        const defaults = operation === 'if' ? [false, first, first] : [first, first]
        const destination = node('destination', {
          kind: 'call',
          operation,
          defaults,
          inputs: defaults.map(() => null),
        })
        const nodes = [source, destination]
        const before = JSON.stringify(nodes)
        for (const slot of operation === 'if' ? [1, 2] : [0, 1]) {
          const connect = () => canConnect(source, destination, slot, nodes, catalog, doc)
          if (typeof first === typeof second) expect(connect).not.toThrow()
          else expect(connect).toThrow(/needs/)
        }
        expect(JSON.stringify(nodes)).toBe(before)
      }
  })
}

test('numeric, comparison, boolean, and condition sockets reject incompatible values', () => {
  for (const operation of catalog.operations.filter((item) =>
    ['numeric', 'comparison', 'boolean'].includes(item.signature),
  )) {
    const boolean = operation.signature === 'boolean'
    const destination = node('destination', {
      kind: 'call',
      operation: operation.name,
      inputs: [null, null],
      defaults: boolean ? [false, false] : [1, 1],
    })
    for (const value of [...values, null]) {
      const source = node('source', { value })
      for (const index of [0, 1]) {
        const connect = () =>
          canConnect(source, destination, index, [source, destination], catalog, doc)
        if (typeof value === (boolean ? 'boolean' : 'number')) expect(connect).not.toThrow()
        else expect(connect).toThrow(/needs/)
      }
    }
  }
  const conditional = node('conditional', {
    kind: 'call',
    operation: 'if',
    inputs: [null, null, null],
    defaults: [false, 1, 2],
  })
  for (const value of [...values, null]) {
    const source = node('source', { value })
    const connect = () => canConnect(source, conditional, 0, [source, conditional], catalog, doc)
    if (typeof value === 'boolean') expect(connect).not.toThrow()
    else expect(connect).toThrow(/needs boolean/)
  }
})

test('null remains an absence test and a compatible optional branch', () => {
  for (const operation of ['if', 'equal', 'not_equal']) {
    const source = node('source', { value: null })
    const destination = node('destination', {
      kind: 'call',
      operation,
      inputs: operation === 'if' ? [null, null, null] : [null, null],
      defaults: operation === 'if' ? [false, 'text', 'text'] : ['text', 'text'],
    })
    expect(() =>
      canConnect(source, destination, 1, [source, destination], catalog, doc),
    ).not.toThrow()
    destination.inputs[1] = source.id
    expect(() => validateGraphTypes([source, destination], catalog)).not.toThrow()
    expect(inputType(destination, 1, [source, destination], catalog)).toBe('text')
  }
})

test('reconnecting an intermediate cannot invalidate downstream branches or outputs', () => {
  for (const operation of ['if', 'equal', 'not_equal', 'add']) {
    const source = node('source', { value: 'text' })
    const relay = node('relay', { kind: 'variable', name: 'amount', inputs: [null], defaults: [1] })
    const consumer = node('consumer', {
      kind: 'call',
      operation,
      inputs: operation === 'if' ? [null, relay.id, null] : [relay.id, null],
      defaults: operation === 'if' ? [false, 1, 2] : [1, 2],
    })
    expect(() => canConnect(source, relay, 0, [source, relay, consumer], catalog, doc)).toThrow(
      /same type|needs number/,
    )
    expect(relay.inputs).toEqual([null])
  }
  const source = node('source', { value: false })
  const relay = node('relay', { kind: 'variable', name: 'amount', inputs: [null], defaults: [1] })
  const output = node('output', {
    kind: 'output',
    target: 'label',
    property: 'length_mm',
    inputs: [relay.id],
    defaults: [30],
  })
  expect(() => canConnect(source, relay, 0, [source, relay, output], catalog, doc)).toThrow(
    /length_mm needs number/,
  )
})

test('detached mismatches are invalid but unrelated invalid drafts do not prevent repairs', () => {
  const broken = node('broken', {
    kind: 'call',
    operation: 'equal',
    inputs: [null, null],
    defaults: ['text', false],
  })
  expect(() => validateGraphTypes([broken], catalog)).toThrow(/same type/)
  const source = node('source', { value: true })
  const destination = node('destination', {
    kind: 'call',
    operation: 'and',
    inputs: [null, null],
    defaults: [false, false],
  })
  expect(() =>
    canConnect(source, destination, 0, [broken, source, destination], catalog, doc),
  ).not.toThrow()
})
