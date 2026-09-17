import { Header } from '@/components/layout/header'
import { cn } from '@/utils'
import AdminAccessCard from './AdminAccessCard'
import { GeneralSettingsPanel } from './components/GeneralSettingsPanel'
import { IntegrationSettingsPanel } from './components/IntegrationSettingsPanel'
import { ExtensionSettingsPanel } from './components/ExtensionSettingsPanel'
import { RagSettingsPanel } from './components/RagSettingsPanel'
import { useSettingsController } from './hooks/useSettingsController'

export default function SettingsHub() {
  const settings = useSettingsController()
  const { activeTab, changeTab, SETTINGS_TABS, reloadProtectedSettings } = settings

  return (
    <div className="flex flex-col h-screen">
      <Header title="设置" />
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-6 pt-4 border-b border-border/50 shrink-0">
          <div className="max-w-4xl mx-auto flex flex-wrap gap-1">
            {SETTINGS_TABS.map((tab) => {
              const Icon = tab.icon
              const active = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => changeTab(tab.id)}
                  className={cn(
                    'flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium transition-colors',
                    active
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                </button>
              )
            })}
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          <div className="max-w-4xl mx-auto space-y-6">
            <AdminAccessCard onVerified={reloadProtectedSettings} />
            <GeneralSettingsPanel settings={settings} />
            <IntegrationSettingsPanel settings={settings} />
            <ExtensionSettingsPanel settings={settings} />
            <RagSettingsPanel settings={settings} />
          </div>
        </div>
      </div>
    </div>
  )
}
