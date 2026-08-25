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
