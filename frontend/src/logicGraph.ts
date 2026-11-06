import type {
  Expression,
  LogicEditorState,
  LogicNode,
  LogicProgram,
  TemplateDocument,
  ValueType,
  VariableValue,
} from './editor'
import { randomUUID } from './uuid'
import { validVariableName } from './variableInputs'
export type SocketType = ValueType | 'null' | 'any'
export interface Operation {
  name: string
  minimum_arguments: number
  maximum_arguments: number
  signature: 'numeric' | 'comparison' | 'equality' | 'boolean' | 'conditional' | 'presence'
  description: string
}
export interface SourceDiagnostic {
  from: number
  to: number
  message: string
  severity: 'error'
  line: number
  column: number
}
export interface CompileResult {
  valid: boolean
  program?: LogicProgram
  formatted?: string
  catalog?: LogicCatalog
  diagnostics: SourceDiagnostic[]
}
export interface LogicCatalog {
  source: string
  operations: Operation[]
  targets: Record<
    string,
    {
      id: string
      properties: Record<string, ValueType>
      readable_properties?: Record<string, ValueType> | null
      disabled_properties?: Record<string, string>
    }
  >
  types: Record<string, SocketType>
  values: Record<string, VariableValue>
  property_values?: Record<string, Record<string, VariableValue>>
  sample_error: string | null
}
export const valueTypes: ValueType[] = ['text', 'number', 'boolean', 'image']
export const defaultValue = (type: SocketType): VariableValue =>
  type === 'text' ? '' : type === 'boolean' ? false : type === 'number' ? 0 : null
export const valueType = (value: VariableValue): SocketType =>
  value === null
    ? 'null'
    : typeof value === 'object'
      ? 'image'
      : typeof value === 'string'
        ? 'text'
        : typeof value === 'boolean'
          ? 'boolean'
          : 'number'
export const title = (name: string) =>
  name.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase())
export function automaticOutput(
  node: Pick<LogicNode, 'kind' | 'target' | 'property'>,
  doc: TemplateDocument,
): boolean {
  if (node.kind !== 'output') return false
  if (node.target === 'label') return node.property === 'length_mm' && !!doc.auto_length
  const element = doc.elements.find((element) => element.id === node.target)
  return !!(element?.kind === 'text' && element.auto_width && node.property === 'width')
}
export function makeNode(
  kind: LogicNode['kind'],
  state: LogicEditorState,
  extra: Partial<LogicNode> = {},
): LogicNode {
  return {
    id: randomUUID(),
    kind,
    x: 40 - state.x / state.zoom,
    y: 40 - state.y / state.zoom,
    type: 'number',
    inputs: [],
    defaults: [],
    ...extra,
  }
}
export function semanticProgram(program: LogicProgram | null | undefined): string {
  function clean(expression: Expression): unknown {
    if (expression.kind === 'literal') return ['literal', expression.value]
    if (expression.kind === 'reference') return ['reference', expression.name]
    if (expression.kind === 'property') return ['property', expression.target, expression.property]
    return [expression.operation, expression.arguments.map(clean)]
  }
  return JSON.stringify([
    Object.entries(program?.variables ?? {})
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, expression]) => [name, clean(expression)]),
    (program?.bindings ?? [])
      .map((binding) => [binding.target, binding.property, clean(binding.expression)])
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b))),
  ])
}
export function compileGraph(nodes: LogicNode[], doc: TemplateDocument): LogicProgram {
  if (nodes.length > 512) throw new Error('At most 512 nodes are supported.')
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const outputs = new Map(
    nodes
      .filter((node) => node.kind === 'output' && !automaticOutput(node, doc))
      .map((node) => [`${node.target}.${node.property}`, node]),
  )
  const variables = nodes.filter((node) => node.kind === 'variable')
  const names = new Set([
    ...doc.fields.map((field) => field.name),
    ...doc.elements.map((element) => element.logic_name),
    'label',
  ])
  for (const node of variables) {
    if (!node.name || !validVariableName(node.name) || names.has(node.name))
      throw new Error('Intermediate variables need unique, non-reserved names.')
    names.add(node.name)
  }
  // Check every wire, including detached draft nodes, before walking expression trees.
  const visiting = new Set<string>(),
    visited = new Set<string>()
  function check(node: LogicNode, depth = 0) {
    if (depth > 32 || visiting.has(node.id))
      throw new Error('Connections cannot form a cycle or exceed 32 levels.')
    if (visited.has(node.id)) return
    visiting.add(node.id)
    if (node.kind === 'property') {
      const binding = outputs.get(`${node.target}.${node.property}`)
      if (binding) check(binding, depth + 1)
    }
    for (const id of node.inputs)
      if (id) {
        const input = byId.get(id)
        if (!input || input.kind === 'output') throw new Error('A connection has no value source.')
        check(input, depth + 1)
      }
    visiting.delete(node.id)
    visited.add(node.id)
  }
  nodes.forEach((node) => check(node))
  let budget = 0
  function argument(node: LogicNode, index: number, depth: number): Expression {
    const id = node.inputs[index]
    return id
      ? expression(byId.get(id)!, depth + 1)
      : { kind: 'literal', value: node.defaults[index] ?? null }
  }
  function expression(node: LogicNode, depth = 0): Expression {
    if (++budget > 512 || depth > 32)
      throw new Error('This graph exceeds the expression size or depth limit.')
    if (node.kind === 'input' || node.kind === 'variable')
      return { kind: 'reference', name: node.name!, node_id: node.id }
    if (node.kind === 'literal')
      return { kind: 'literal', value: node.value ?? null, node_id: node.id }
    if (node.kind === 'property')
      return { kind: 'property', target: node.target!, property: node.property!, node_id: node.id }
    if (node.kind === 'call')
      return {
        kind: 'call',
        operation: node.operation!,
        arguments: node.inputs.map((_, index) => argument(node, index, depth)),
        node_id: node.id,
      }
    throw new Error('Output nodes cannot be used as inputs.')
  }
  return {
    version: 1,
    variables: Object.fromEntries(variables.map((node) => [node.name!, argument(node, 0, 0)])),
    bindings: nodes
      .filter((node) => node.kind === 'output' && !automaticOutput(node, doc))
      .map((node) => ({
        target: node.target!,
        property: node.property!,
        expression: argument(node, 0, 0),
      })),
  }
}
export function loadGraph(doc: TemplateDocument, restoreManualLength = true): LogicEditorState {
  const saved = doc.logic_editor
  if (saved) {
    try {
      const program = compileGraph(saved.nodes, doc)
      const current = {
        ...(doc.logic ?? { version: 1 as const, variables: {}, bindings: [] }),
        bindings: (doc.logic?.bindings ?? []).filter(
          (binding) => !automaticOutput({ ...binding, kind: 'output' }, doc),
        ),
      }
      const comparable = restoreManualLength
        ? {
            ...program,
            bindings: program.bindings.filter(
              (binding) =>
                current.bindings.some(
                  (item) => item.target === binding.target && item.property === binding.property,
                ) ||
                !(
                  binding.target === 'label' ||
                  (binding.property === 'width' &&
                    doc.elements.some(
                      (element) => element.id === binding.target && element.kind === 'text',
                    ))
                ),
            ),
          }
        : program
      if (
        semanticProgram(comparable) === semanticProgram(current) &&
        saved.nodes
          .filter((node) => node.kind === 'input')
          .every((node) =>
            doc.fields.some(
              (field) => field.name === node.name && (field.type ?? 'text') === node.type,
            ),
          )
      ) {
        const state: LogicEditorState = JSON.parse(JSON.stringify(saved))
        for (const field of doc.fields)
          if (!state.nodes.some((node) => node.kind === 'input' && node.name === field.name))
            state.nodes.push(
              makeNode('input', state, {
                name: field.name,
                type: field.type ?? 'text',
                x: 0,
                y: state.nodes.length * 110,
              }),
            )
        return state
      }
    } catch {
      /* Reconstruct when executable logic was edited outside this graph. */
    }
  }
  const state: LogicEditorState = { version: 1, nodes: [], x: 24, y: 24, zoom: 0.85 }
  const references = new Map<string, string>()
  const positions = new Map(saved?.nodes.map((node) => [node.id, node]))
  function insert(node: LogicNode) {
    const position = positions.get(node.id)
    if (position) {
      node.x = position.x
      node.y = position.y
    }
    state.nodes.push(node)
    return node.id
  }
  doc.fields.forEach((field, index) =>
    references.set(
      field.name,
      insert(
        makeNode('input', state, {
          id:
            saved?.nodes.find((node) => node.kind === 'input' && node.name === field.name)?.id ??
            `input:${field.name}`,
          name: field.name,
          type: field.type ?? 'text',
          x: 0,
          y: index * 130,
        }),
      ),
    ),
  )
  Object.keys(doc.logic?.variables ?? {}).forEach((name, index) =>
    references.set(
      name,
      insert(
        makeNode('variable', state, {
          id:
            saved?.nodes.find((node) => node.kind === 'variable' && node.name === name)?.id ??
            `variable:${name}`,
          name,
          inputs: [null],
          defaults: [0],
          x: 600,
          y: index * 150,
        }),
      ),
    ),
  )
  let row = 0
  function unpack(expression: Expression, path: string, depth = 0): string {
    if (expression.kind === 'reference' && references.has(expression.name))
      return references.get(expression.name)!
    const id = expression.node_id ?? `expression:${path}`
    if (state.nodes.some((node) => node.id === id)) return id
    const node = makeNode(
      expression.kind === 'literal'
        ? 'literal'
        : expression.kind === 'property'
          ? 'property'
          : 'call',
      state,
      {
        id,
        x: 300 + depth * 280,
        y: row++ * 150,
      },
    )
    if (expression.kind === 'literal') {
      node.value = expression.value
      node.type =
        valueType(expression.value) === 'null'
          ? 'image'
          : (valueType(expression.value) as ValueType)
    } else if (expression.kind === 'property') {
      node.target = expression.target
      node.property = expression.property
    } else if (expression.kind === 'call') {
      node.operation = expression.operation
      node.inputs = expression.arguments.map((argument, index) =>
        argument.kind === 'literal' &&
        !saved?.nodes.some((node) => node.kind === 'literal' && node.id === argument.node_id)
          ? null
          : unpack(argument, `${path}:${index}`, depth + 1),
      )
      node.defaults = expression.arguments.map((argument) =>
        argument.kind === 'literal' ? argument.value : null,
      )
    } else throw new Error(`Unknown variable: ${expression.name}`)
    return insert(node)
  }
  function setRoot(node: LogicNode, expression: Expression, path: string) {
    if (
      expression.kind === 'literal' &&
      !saved?.nodes.some(
        (candidate) => candidate.kind === 'literal' && candidate.id === expression.node_id,
      )
    ) {
      node.inputs = [null]
      node.defaults = [expression.value]
    } else node.inputs = [unpack(expression, path)]
  }
  Object.entries(doc.logic?.variables ?? {}).forEach(([name, expression], index) => {
    setRoot(
      state.nodes.find((node) => node.id === references.get(name))!,
      expression,
      `v${index}`,
    )
  })
  doc.logic?.bindings.forEach((binding, index) => {
    const previous = saved?.nodes.find(
      (node) =>
        node.kind === 'output' &&
        node.target === binding.target &&
        node.property === binding.property,
    )
    const node = makeNode('output', state, {
      id: previous?.id ?? (saved ? randomUUID() : `output:${index}`),
      target: binding.target,
      property: binding.property,
      inputs: [null],
      defaults: [null],
      x: 900,
      y: index * 150,
    })
    setRoot(node, binding.expression, `b${index}`)
    insert(node)
  })
  if (saved) {
    state.x = saved.x
    state.y = saved.y
    state.zoom = saved.zoom
    const used = new Set<string>()
    function visit(id: string) {
      if (used.has(id)) return
      used.add(id)
      saved!.nodes
        .find((node) => node.id === id)
        ?.inputs.forEach((input) => {
          if (input) visit(input)
        })
    }
    saved.nodes
      .filter((node) => node.kind === 'variable' || node.kind === 'output')
      .forEach((node) => visit(node.id))
    const retained = saved.nodes.filter((node) => !used.has(node.id) && node.kind !== 'input')
    // Automatic dimensions retain their inactive manual drafts.
    {
      const inactive = new Set<string>()
      function keep(id: string) {
        if (inactive.has(id)) return
        inactive.add(id)
        const node = saved!.nodes.find((node) => node.id === id)
        if (!node || node.kind === 'variable') return
        retained.push(node)
        node.inputs.forEach((input) => {
          if (input) keep(input)
        })
      }
      saved.nodes.filter((node) => automaticOutput(node, doc)).forEach((node) => keep(node.id))
    }
    for (const node of retained)
      if (!state.nodes.some((candidate) => candidate.id === node.id))
        state.nodes.push(JSON.parse(JSON.stringify(node)))
    for (const node of state.nodes)
      node.inputs = node.inputs.map((id) =>
        state.nodes.some((candidate) => candidate.id === id) ? id : null,
      )
  }
  return state
}
export function nodeType(
  node: LogicNode,
  nodes: LogicNode[],
  catalog: LogicCatalog,
  depth = 0,
): SocketType {
  if (depth > 32) return 'any'
  const input = (index: number): SocketType => {
    const source = nodes.find((candidate) => candidate.id === node.inputs[index])
    return source
      ? nodeType(source, nodes, catalog, depth + 1)
      : valueType(node.defaults[index] ?? null)
  }
  if (node.kind === 'input') return node.type
  if (node.kind === 'property') {
    const target = Object.values(catalog.targets).find((target) => target.id === node.target)
    return (target?.readable_properties ?? target?.properties)?.[node.property!] ?? 'any'
  }
  if (node.kind === 'literal') return valueType(node.value ?? null)
  if (node.kind === 'variable') return input(0)
  if (node.kind === 'output')
    return (
      Object.values(catalog.targets).find((target) => target.id === node.target)?.properties[
        node.property!
      ] ?? 'any'
    )
  const signature = catalog.operations.find(
    (operation) => operation.name === node.operation,
  )?.signature
  if (signature === 'numeric') return 'number'
  if (signature === 'conditional') return input(1) === 'null' ? input(2) : input(1)
  return 'boolean'
}
// If branches and equality operands have one shared value type.
export function pairedInputs(node: LogicNode): number[] {
  if (node.kind !== 'call') return []
  if (node.operation === 'if') return [1, 2]
  return node.operation === 'equal' || node.operation === 'not_equal' ? [0, 1] : []
}
export function pairedType(node: LogicNode, nodes: LogicNode[], catalog: LogicCatalog): ValueType {
  for (const index of pairedInputs(node)) {
    const source = nodes.find((candidate) => candidate.id === node.inputs[index])
    const type = source ? nodeType(source, nodes, catalog) : valueType(node.defaults[index] ?? null)
    if (type !== 'null' && type !== 'any') return type
  }
  return node.type
}

// Validate the affected consumers too: changing an intermediate can otherwise
// invalidate a distant wire even when its immediate destination accepts any type.
export function validateGraphTypes(nodes: LogicNode[], catalog: LogicCatalog, changed?: string[]) {
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const types = new Map<string, SocketType>(),
    visiting = new Set<string>()
  function infer(node: LogicNode, depth = 0): SocketType {
    if (depth > 32 || visiting.has(node.id))
      throw new Error('Connections cannot form a cycle or exceed 32 levels.')
    const cached = types.get(node.id)
    if (cached) return cached
    visiting.add(node.id)
    const args = node.inputs.map((id, index) => {
      if (!id) return valueType(node.defaults[index] ?? null)
      const source = byId.get(id)
      if (!source || source.kind === 'output') throw new Error('A connection has no value source.')
      return infer(source, depth + 1)
    })
    const require = (
      actual: SocketType | undefined,
      expected: SocketType,
      label: string,
      nullable = false,
    ) => {
      if (actual !== expected && !(nullable && actual === 'null'))
        throw new Error(`${label} needs ${expected}; the value is ${actual ?? 'missing'}.`)
    }
    let result: SocketType
    if (node.kind === 'input') result = node.type
    else if (node.kind === 'property') {
      result = nodeType(node, nodes, catalog)
      if (result === 'any') throw new Error('This property cannot be read during logic.')
    } else if (node.kind === 'literal') result = valueType(node.value ?? null)
    else if (node.kind === 'variable') result = args[0] ?? 'null'
    else if (node.kind === 'output') {
      result = nodeType(node, nodes, catalog)
      require(args[0], result, node.property ?? 'Output', result === 'image')
    } else {
      const operation = catalog.operations.find((operation) => operation.name === node.operation)
      if (!operation) throw new Error(`Unknown operation: ${node.operation}`)
      if (args.length < operation.minimum_arguments || args.length > operation.maximum_arguments)
        throw new Error(`${title(operation.name)} has an invalid number of inputs.`)
      if (operation.signature === 'conditional' || operation.signature === 'equality') {
        const [a, b] = operation.signature === 'conditional' ? [1, 2] : [0, 1]
        if (operation.signature === 'conditional') require(args[0], 'boolean', 'If Condition')
        if (args[a!] !== args[b!] && args[a!] !== 'null' && args[b!] !== 'null')
          throw new Error(
            `${title(operation.name)} ${socketLabel(node, a!)} and ${socketLabel(node, b!)} must have the same type; received ${args[a!]} and ${args[b!]}.`,
          )
        result =
          operation.signature === 'equality'
            ? 'boolean'
            : args[a!] === 'null'
              ? args[b!]!
              : args[a!]!
      } else if (operation.signature === 'presence') result = 'boolean'
      else {
        const expected = operation.signature === 'boolean' ? 'boolean' : 'number'
        args.forEach((actual, index) =>
          require(actual, expected, `${title(operation.name)} ${socketLabel(node, index)}`),
        )
        result = operation.signature === 'numeric' ? 'number' : 'boolean'
      }
    }
    visiting.delete(node.id)
    types.set(node.id, result)
    return result
  }
  const affected = changed ? new Set(changed) : new Set(nodes.map((node) => node.id))
  if (changed) {
    const pending = [...changed]
    while (pending.length) {
      const id = pending.pop()!
      for (const node of nodes)
        if (!affected.has(node.id) && node.inputs.includes(id)) {
          affected.add(node.id)
          pending.push(node.id)
        }
    }
  }
  for (const id of affected) {
    const node = byId.get(id)
    if (node) infer(node)
  }
}
export function inputType(
  node: LogicNode,
  index: number,
  nodes: LogicNode[],
  catalog: LogicCatalog,
): SocketType {
  if (node.kind === 'output') return nodeType(node, nodes, catalog)
  if (node.kind === 'variable') return 'any'
  if (pairedInputs(node).includes(index)) return pairedType(node, nodes, catalog)
  const signature = catalog.operations.find(
    (operation) => operation.name === node.operation,
  )?.signature
  if (signature === 'numeric' || signature === 'comparison') return 'number'
  if (signature === 'boolean' || (signature === 'conditional' && index === 0)) return 'boolean'
  return 'any'
}
export function socketLabel(node: LogicNode, index: number) {
  if (node.kind === 'output' || node.kind === 'variable') return 'Value'
  if (node.operation === 'if') return ['Condition', 'Then', 'Else'][index]!
  if (node.inputs.length === 1) return 'Value'
  return ['A', 'B'][index]!
}
export function canConnect(
  source: LogicNode,
  destination: LogicNode,
  index: number,
  nodes: LogicNode[],
  catalog: LogicCatalog,
  doc: TemplateDocument,
) {
  if (source.kind === 'output' || source.id === destination.id)
    throw new Error('Choose a value output and a different node’s input.')
  if (destination.kind === 'output') {
    const reason = Object.values(catalog.targets).find((target) => target.id === destination.target)
      ?.disabled_properties?.[destination.property!]
    if (reason) throw new Error(reason)
  }
  const expected = inputType(destination, index, nodes, catalog),
    actual = nodeType(source, nodes, catalog)
  const nullable = expected === 'image' || pairedInputs(destination).includes(index)
  if (expected !== 'any' && actual !== expected && !(nullable && actual === 'null'))
    throw new Error(`This input needs ${expected}; the output is ${actual}.`)
  const candidate = nodes.map((node) =>
    node.id === destination.id
      ? { ...node, inputs: node.inputs.map((id, slot) => (slot === index ? source.id : id)) }
      : node,
  )
  compileGraph(candidate, doc)
  validateGraphTypes(candidate, catalog, [destination.id])
}
