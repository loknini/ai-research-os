import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { applyTheme, useThemeStore } from './stores/themeStore'
import './index.css'

// 首屏渲染前应用已持久化的主题，避免暗色/浅色首屏闪烁
applyTheme(useThemeStore.getState().mode)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
