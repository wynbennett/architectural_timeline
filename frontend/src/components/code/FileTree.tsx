import { useEffect, useMemo, useRef, useState } from 'react'
import { Tree, type NodeApi, type NodeRendererProps } from 'react-arborist'

export interface TreeItem { id: string; name: string; children?: TreeItem[] }

export function buildTree(paths: string[]): TreeItem[] {
  const root: TreeItem[] = []
  const index = new Map<string, TreeItem>()
  for (const p of [...paths].sort()) {
    const parts = p.split('/')
    let level = root
    let acc = ''
    parts.forEach((part, i) => {
      acc = acc ? `${acc}/${part}` : part
      let node = index.get(acc)
      if (!node) {
        node = i === parts.length - 1 ? { id: acc, name: part } : { id: acc, name: part, children: [] }
        index.set(acc, node)
        level.push(node)
      }
      level = node.children ?? level
    })
  }
  const sortRec = (items: TreeItem[]) => {
    items.sort((a, b) => (a.children ? 0 : 1) - (b.children ? 0 : 1) || a.name.localeCompare(b.name))
    items.forEach((i) => i.children && sortRec(i.children))
  }
  sortRec(root)
  return root
}

function Row({ node, style }: NodeRendererProps<TreeItem>) {
  const isDir = node.isInternal
  return (
    <div
      style={style}
      className={`tree-row${node.isSelected ? ' is-selected' : ''}${isDir ? ' is-dir' : ''}`}
      onClick={() => (isDir ? node.toggle() : node.select())}
    >
      <span className="tree-caret">{isDir ? (node.isOpen ? '▾' : '▸') : ''}</span>
      <span className="tree-name">{node.data.name}</span>
    </div>
  )
}

export function FileTree({ paths, selected, onOpen }: { paths: string[]; selected: string | null; onOpen: (path: string) => void }) {
  const data = useMemo(() => buildTree(paths), [paths])
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 240, height: 300 })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="file-tree" ref={ref}>
      <Tree<TreeItem>
        data={data}
        width={size.width}
        height={size.height}
        rowHeight={22}
        indent={12}
        openByDefault={paths.length < 60}
        selection={selected ?? undefined}
        disableDrag
        disableDrop
        disableEdit
        onSelect={(nodes: NodeApi<TreeItem>[]) => { const n = nodes[0]; if (n && n.isLeaf) onOpen(n.id) }}
      >
        {Row}
      </Tree>
    </div>
  )
}
