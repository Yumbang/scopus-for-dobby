export type Paper = {
  eid: string
  title: string
  /** Up to three surnames, then "et al." */
  authors: string
  year: string
  journal: string
  cited: number
}

/** scope is "all", "project:<name>" or "collection:<name>". */
export type View = {
  scope: string
  query: string
  /** Index of the first paper the list shows; the list scrolls by moving it. */
  top: number
  total: number
  papers: Paper[]
  isLoading: boolean
  error: string | null
}

export type Catalog = {
  projects: { name: string; count: number }[]
  collections: { name: string; count: number; project: string | null }[]
}

/** What the pane shows under an unfolded paper; loaded when it is first unfolded. */
export type Detail = { abstract: string; keywords: string[] }

/** Which papers are unfolded, and which of those show their whole abstract. */
export type Open = { expanded: string[]; full: string[] }

/** Which projects are unfolded in the scope tree, and whether the tree is showing. */
export type Tree = { isOpen: boolean; expanded: string[]; top: number }

declare module 'claude-code' {
  interface PluginState {
    'scopus-papers': { view: View; picked: Paper[]; catalog: Catalog; tree: Tree; open: Open; details: Record<string, Detail> }
  }
}
