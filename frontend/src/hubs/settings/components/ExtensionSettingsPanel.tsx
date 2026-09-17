import SkillManager from '../SkillManager'
import MemoryManager from '../MemoryManager'
import type { SettingsController } from '../hooks/useSettingsController'

interface PanelProps { settings: SettingsController }

export function ExtensionSettingsPanel({ settings }: PanelProps) {
  const { activeTab } = settings
  return (
    <>
          {/* ============ 扩展能力 ============ */}
          {activeTab === 'extensions' && (<>
          {/* 技能管理 */}
          <SkillManager />

          {/* 长期记忆 */}
          <MemoryManager />

          </>)}
    </>
  )
}
