import { useSearchParams } from 'react-router-dom'
import { Header } from '@/components/layout/header'
import { cn } from '@/utils'
import SoftwareHub from '@/hubs/software'
import ExperimentHub from '@/hubs/experiment'

/**
 * 研发实验 Hub：软件开发 + 实验管理 合并为一个业务域容器。
 * 通过 ?tab=experiment 直达实验子页；/software、/experiment 旧路由保留（重定向至此）。
 */
export default function LabHub() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab: 'software' | 'experiment' =
    searchParams.get('tab') === 'experiment' ? 'experiment' : 'software'

  const setTab = (tab: 'software' | 'experiment') => {
    if (tab === 'experiment') setSearchParams({ tab: 'experiment' })
    else setSearchParams({})
  }

  return (
    <div className="flex flex-col h-screen">
      <Header title="研发实验" />

      <div className="px-6 pt-3 flex items-center gap-1 border-b border-border/60">
        <button
          className={cn(
            'px-4 py-2 text-sm font-medium transition-colors',
            activeTab === 'software'
              ? 'text-primary border-b-2 border-primary'
              : 'text-muted-foreground hover:text-foreground'
          )}
          onClick={() => setTab('software')}
        >
          软件开发
        </button>
        <button
          className={cn(
            'px-4 py-2 text-sm font-medium transition-colors',
            activeTab === 'experiment'
              ? 'text-primary border-b-2 border-primary'
              : 'text-muted-foreground hover:text-foreground'
          )}
          onClick={() => setTab('experiment')}
        >
          实验管理
        </button>
      </div>

      <div className="flex-1 overflow-hidden">
        {activeTab === 'software' ? <SoftwareHub embedded /> : <ExperimentHub embedded />}
      </div>
    </div>
  )
}
