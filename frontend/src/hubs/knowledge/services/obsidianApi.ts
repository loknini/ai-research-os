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
// - `scanVault` / `addVault` return `null` when `response.ok` is false, so the
//   handler's existing `if (result?.success)` / `if (result)` flow reproduces the
//   original behavior (non-OK responses were silently ignored in the source).

import type { ObsidianVault, ObsidianFile } from '../types'

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
  const response = await fetch('/api/obsidian/vaults')
  if (response.ok) {
    const data = await response.json()
    if (data.success) return data.vaults as ObsidianVault[]
  }
  return []
}

/** Fetch the files belonging to a given vault. */
export async function fetchVaultFiles(vaultId: number): Promise<ObsidianFile[]> {
  const response = await fetch(`/api/obsidian/vaults/${vaultId}/files`)
  if (response.ok) {
    const data = await response.json()
    if (data.success) return data.files as ObsidianFile[]
  }
  return []
}

/** Trigger a scan of the given vault. Returns `null` when the response is not OK. */
export async function scanVault(vaultId: number): Promise<ScanResult | null> {
  const response = await fetch(`/api/obsidian/vaults/${vaultId}/scan`, {
    method: 'POST'
  })
  if (!response.ok) return null
  return (await response.json()) as ScanResult
}

/** Register a new vault. Returns `null` when the response is not OK. */
export async function addVault(name: string, path: string): Promise<AddVaultResult | null> {
  const response = await fetch('/api/obsidian/vaults', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, path })
  })
  if (!response.ok) return null
  return (await response.json()) as AddVaultResult
}
