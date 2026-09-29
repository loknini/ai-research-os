import { apiRequest } from '@/services/api'
// Obsidian Vault / file API service for the Knowledge Hub.
// Extracted from the original monolithic index.tsx (fetch calls inside
// loadObsidianVaults / loadObsidianFiles / handleScanVault / handleAddVault at
// lines 108, 128, 146, 205).
//
// Behavior contract: each function owns exactly one fetch request (URL, options and
// JSON parsing). Toasts and state mutations stay in the container handlers.
//
// - `fetchVaults` / `fetchVaultFiles` return an empty array on failure (matching the
//   container's initial `[]` state, so a failed load is a no-op on mount).
// - Mutating and filesystem-browsing calls surface non-OK responses so the UI can
//   explain missing remote administrator authorization instead of failing silently.

import type {
  ObsidianVault,
  ObsidianFile,
  ObsidianFileDetail,
  ServerDirectoryListing,
} from '../types'

/** Result shape of a vault scan, as returned by the backend. */
export interface ScanResult {
  success: boolean
  added: number
  updated: number
}

/** Result shape of adding a vault, as returned by the backend. */
export interface AddVaultResult {
  success: boolean
  message?: string
}

/** Fetch all registered Obsidian Vaults. */
export async function fetchVaults(): Promise<ObsidianVault[]> {
  const response = await apiRequest('/api/obsidian/vaults')
  if (response.ok) {
    const data = await response.json()
    if (data.success) return data.vaults as ObsidianVault[]
  }
  return []
}

/** Fetch the files belonging to a given vault. */
export async function fetchVaultFiles(vaultId: number): Promise<ObsidianFile[]> {
  const response = await apiRequest(`/api/obsidian/vaults/${vaultId}/files`)
  if (response.ok) {
    const data = await response.json()
    if (data.success) return data.files as ObsidianFile[]
  }
  return []
}

/** Fetch the complete Markdown and metadata for one indexed Obsidian file. */
export async function fetchObsidianFile(fileId: number): Promise<ObsidianFileDetail | null> {
  const response = await apiRequest(`/api/obsidian/files/${fileId}`)
  if (!response.ok) return null
  const data = await response.json()
  return data.success && data.file ? data.file as ObsidianFileDetail : null
}

/** Browse one level of the backend machine's directory tree. */
export async function browseServerDirectories(path?: string): Promise<ServerDirectoryListing> {
  const query = path ? `?${new URLSearchParams({ path }).toString()}` : ''
  const response = await apiRequest(`/api/obsidian/directories${query}`)
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail || `无法浏览服务器目录（HTTP ${response.status}）`)
  }
  return (await response.json()) as ServerDirectoryListing
}

/** Trigger a scan of the given vault and surface server-side errors to the UI. */
export async function scanVault(vaultId: number): Promise<ScanResult | null> {
  const response = await apiRequest(`/api/obsidian/vaults/${vaultId}/scan`, {
    method: 'POST'
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail || `无法扫描 Vault（HTTP ${response.status}）`)
  }
  return (await response.json()) as ScanResult
}

/** Register a new vault. Returns `null` when the response is not OK. */
export async function addVault(name: string, path: string): Promise<AddVaultResult | null> {
  const response = await apiRequest('/api/obsidian/vaults', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, path })
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail || `无法添加 Vault（HTTP ${response.status}）`)
  }
  return (await response.json()) as AddVaultResult
}
