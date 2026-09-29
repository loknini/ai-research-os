// Local type definitions for the Knowledge Hub.
// Extracted from the original monolithic index.tsx (inline state shapes at lines 46-64).

/** An Obsidian Vault connection registered with the backend. */
export interface ObsidianVault {
  id: number
  name: string
  path: string
  file_count: number
  last_sync_at: number | null
}

/** A file discovered inside an Obsidian Vault. */
export interface ObsidianFile {
  id: number
  path: string
  title: string
  tags: string[]
  modified_at: number
}

/** Full file payload returned when an Obsidian list item is opened. */
export interface ObsidianFileDetail extends ObsidianFile {
  content: string | null
  frontmatter: Record<string, unknown>
  links: Array<{ target: string; alias: string }>
}

/** One server-visible directory returned by the protected filesystem browser. */
export interface ServerDirectory {
  name: string
  path: string
  isVault: boolean
}

/** A single level of the backend machine's directory tree. */
export interface ServerDirectoryListing {
  success: boolean
  currentPath: string | null
  parentPath: string | null
  directories: ServerDirectory[]
}
