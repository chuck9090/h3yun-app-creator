import { useEffect, useState } from 'react'
import { Tooltip } from 'antd'
import { VerticalAlignTopOutlined } from '@ant-design/icons'

/**
 * 回到顶部按钮:页面滚动超过一定距离后出现在右下角。
 * 位置比「生成进度」悬浮图标更高(job-fab 在 bottom:30),避免两者重叠。
 */
export default function BackToTop({ threshold = 320 }: { threshold?: number }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    let raf = 0
    const onScroll = () => {
      if (raf) return
      raf = window.requestAnimationFrame(() => {
        raf = 0
        setVisible(window.scrollY > threshold)
      })
    }
    onScroll() // 初次(含刷新后已在下方的情况)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      if (raf) window.cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
    }
  }, [threshold])

  const toTop = () => {
    try {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch {
      window.scrollTo(0, 0)
    }
  }

  if (!visible) return null

  return (
    <Tooltip title="回到顶部" placement="left">
      <button type="button" className="back-to-top" onClick={toTop} aria-label="回到顶部">
        <VerticalAlignTopOutlined />
      </button>
    </Tooltip>
  )
}
