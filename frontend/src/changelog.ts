import source from '../../CHANGELOG.md?raw'

type Block = { kind: 'heading' | 'paragraph'; text: string } | { kind: 'list'; items: string[] }
export type ReleaseNotes = { version: string; date: string | undefined; blocks: Block[] }

function versionParts(version: string) {
  const match =
    /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$/.exec(
      version,
    )
  if (!match) return undefined
  const prerelease = match[4]?.split('.') ?? []
  if (prerelease.some((part) => /^0\d+$/.test(part))) return undefined
  return { core: match.slice(1, 4).map(Number), prerelease }
}
function compare(
  a: NonNullable<ReturnType<typeof versionParts>>,
  b: NonNullable<ReturnType<typeof versionParts>>,
) {
  for (let i = 0; i < 3; i++) if (a.core[i] !== b.core[i]) return a.core[i]! - b.core[i]!
  if (!a.prerelease.length || !b.prerelease.length)
    return Number(!a.prerelease.length) - Number(!b.prerelease.length)
  for (let i = 0; i < Math.max(a.prerelease.length, b.prerelease.length); i++) {
    const left = a.prerelease[i],
      right = b.prerelease[i]
    if (left === right) continue
    if (left === undefined) return -1
    if (right === undefined) return 1
    const leftNumeric = /^\d+$/.test(left),
      rightNumeric = /^\d+$/.test(right)
    if (leftNumeric && rightNumeric) return BigInt(left) < BigInt(right) ? -1 : 1
    if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1
    return left < right ? -1 : 1
  }
  return 0
}

// CHANGELOG.md uses Keep a Changelog headings, paragraphs and wrapped bullet
// lists. Render these as text nodes, never as HTML supplied by release notes.
export function parseChangelog(markdown: string): ReleaseNotes[] {
  const releases: ReleaseNotes[] = []
  let release: ReleaseNotes | undefined
  let paragraph = ''
  const flush = () => {
    if (paragraph && release) release.blocks.push({ kind: 'paragraph', text: paragraph })
    paragraph = ''
  }
  for (const line of markdown.split(/\r?\n/)) {
    const heading = /^## \[([^\]]+)\](?: - (\d{4}-\d{2}-\d{2}))?\s*$/.exec(line)
    if (heading) {
      flush()
      release = versionParts(heading[1]!)
        ? { version: heading[1]!.replace(/^v/, ''), date: heading[2], blocks: [] }
        : undefined
      if (release) releases.push(release)
      continue
    }
    if (!release || /^\[[^\]]+\]:\s/.test(line)) continue
    const category = /^### (.+)$/.exec(line)
    if (category) {
      flush()
      release.blocks.push({ kind: 'heading', text: category[1]! })
    } else if (/^- /.test(line)) {
      flush()
      let list = release.blocks.at(-1)
      if (list?.kind !== 'list') {
        list = { kind: 'list', items: [] }
        release.blocks.push(list)
      }
      list.items.push(line.slice(2).trim())
    } else if (!line.trim()) {
      flush()
    } else if (/^\s+/.test(line) && release.blocks.at(-1)?.kind === 'list' && !paragraph) {
      const list = release.blocks.at(-1) as Extract<Block, { kind: 'list' }>
      list.items[list.items.length - 1] += ` ${line.trim()}`
    } else {
      paragraph += `${paragraph ? ' ' : ''}${line.trim()}`
    }
  }
  flush()
  return releases.sort((a, b) => compare(versionParts(b.version)!, versionParts(a.version)!))
}

export function releaseHistory(current: string): ReleaseNotes[] {
  const installed = versionParts(current)
  if (!installed) return []
  return parseChangelog(source).filter((release) => {
    const version = versionParts(release.version)!
    return compare(version, installed) <= 0
  })
}

export function unseenReleases(previous: string | null, current: string): ReleaseNotes[] {
  const before = previous && versionParts(previous)
  if (!before) return []
  return releaseHistory(current).filter(
    (release) => compare(versionParts(release.version)!, before) > 0,
  )
}
