import RagSettingsManager from '../RagSettingsManager'
import type { SettingsController } from '../hooks/useSettingsController'

interface PanelProps { settings: SettingsController }

export function RagSettingsPanel({ settings }: PanelProps) {
  const { activeTab } = settings
  return (
    <>
          {/* ============ RAG 文档检索 ============ */}
          {activeTab === 'rag' && <RagSettingsManager />}
    </>
  )
}
