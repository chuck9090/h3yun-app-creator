import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { HashRouter } from 'react-router-dom'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'

import '@xyflow/react/dist/style.css'
import '@uiw/react-md-editor/markdown-editor.css'
import 'react-quill/dist/quill.snow.css'
import './theme/tokens.css'
import './styles.css'

import App from './App'
import { ThemeProvider, useTheme } from './theme/ThemeContext'
import { buildAntdTheme } from './theme/antdTheme'

dayjs.locale('zh-cn')

/** 跟随当前主题的 AntD 配置容器。 */
function ThemedApp() {
  const { mode } = useTheme()
  return (
    <ConfigProvider locale={zhCN} theme={buildAntdTheme(mode)}>
      <AntApp>
        <HashRouter>
          <App />
        </HashRouter>
      </AntApp>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <ThemeProvider>
      <ThemedApp />
    </ThemeProvider>
  </React.StrictMode>,
)
