import { useTheme } from '../theme/ThemeContext'

/** 矢量太阳图标(浅色态)。 */
function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="4.2" fill="currentColor" />
      <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
        <path d="M12 2.6v2.4M12 19v2.4M2.6 12h2.4M19 12h2.4" />
        <path d="M5.1 5.1l1.7 1.7M17.2 17.2l1.7 1.7M18.9 5.1l-1.7 1.7M6.8 17.2l-1.7 1.7" />
      </g>
    </svg>
  )
}

/** 矢量月亮图标(深色态)。 */
function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" aria-hidden="true">
      <path
        d="M20.4 14.2A8.6 8.6 0 1 1 9.8 3.6a6.9 6.9 0 0 0 10.6 10.6Z"
        fill="currentColor"
      />
    </svg>
  )
}

/**
 * 深/浅色主题切换器:带滑块的胶囊按钮。
 * 纯矢量图标,不依赖字体或 emoji;提供无障碍标签与状态。
 */
export default function ThemeToggle() {
  const { dark, toggle } = useTheme()
  const label = dark ? '切换到浅色主题' : '切换到深色主题'

  return (
    <button
      type="button"
      className={`theme-toggle${dark ? ' is-dark' : ''}`}
      onClick={toggle}
      title={label}
      aria-label={label}
      aria-pressed={dark}
    >
      <span className="theme-toggle-thumb" aria-hidden="true" />
      <span className={`theme-toggle-opt${dark ? '' : ' is-active'}`} aria-hidden="true">
        <SunIcon />
      </span>
      <span className={`theme-toggle-opt${dark ? ' is-active' : ''}`} aria-hidden="true">
        <MoonIcon />
      </span>
    </button>
  )
}
