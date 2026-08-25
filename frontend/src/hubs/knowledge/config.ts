// Constants for the Knowledge Hub.
// Extracted from the original monolithic index.tsx (NOTE_TYPE_CONFIG at lines 29-34).

import { BookOpen, Lightbulb, FileText, Code } from 'lucide-react'

/** Metadata for each supported note type: display label, icon and badge color. */
export const NOTE_TYPE_CONFIG: Record<string, { label: string; icon: typeof BookOpen; color: string }> = {
  note: { label: '笔记', icon: BookOpen, color: 'bg-blue-500' },
  idea: { label: '想法', icon: Lightbulb, color: 'bg-yellow-500' },
  summary: { label: '总结', icon: FileText, color: 'bg-green-500' },
  code_snippet: { label: '代码', icon: Code, color: 'bg-purple-500' }
}
