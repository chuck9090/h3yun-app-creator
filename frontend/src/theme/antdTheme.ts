import { theme as antdAlgorithm } from 'antd'
import type { ThemeConfig } from 'antd'
import type { ThemeMode } from './ThemeContext'

/** 界面无衬线栈:优先系统字体,兼顾中文渲染。 */
export const FONT_SANS =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans SC', 'Helvetica Neue', Arial, sans-serif"

/** 等宽栈:用于编码、字段 key、源码等"工程感"文本。 */
export const FONT_MONO =
  "'JetBrains Mono', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Courier New', monospace"

/** 由当前模式生成 AntD 主题:覆盖为低饱和、低对比的柔和配色。 */
export function buildAntdTheme(mode: ThemeMode): ThemeConfig {
  const dark = mode === 'dark'

  return {
    algorithm: dark ? antdAlgorithm.darkAlgorithm : antdAlgorithm.defaultAlgorithm,
    token: {
      colorPrimary: dark ? '#7d8cff' : '#5b6ff0',
      colorInfo: dark ? '#7d8cff' : '#5b6ff0',
      colorSuccess: dark ? '#4bbf82' : '#3aa76d',
      colorWarning: dark ? '#e0aa4a' : '#d99a2b',
      colorError: dark ? '#ec6b6b' : '#e05a5a',
      colorLink: dark ? '#8f9cff' : '#4c5fe0',

      colorBgBase: dark ? '#1b1f29' : '#ffffff',
      colorBgLayout: dark ? '#14171e' : '#f4f6fb',
      colorTextBase: dark ? '#d6dae4' : '#2a3040',

      colorBorder: dark ? '#2c3241' : '#e5e8f1',
      colorBorderSecondary: dark ? '#262c38' : '#eef1f7',

      borderRadius: 8,
      borderRadiusLG: 12,
      borderRadiusSM: 6,
      controlHeight: 32,
      fontFamily: FONT_SANS,
      fontSize: 13,
      wireframe: false,

      boxShadow: '0 8px 24px rgba(24, 32, 64, 0.08)',
      boxShadowSecondary: '0 10px 28px rgba(24, 32, 64, 0.1)',
    },
    components: {
      Layout: {
        headerBg: 'transparent',
        bodyBg: 'transparent',
        siderBg: 'transparent',
        headerHeight: 52,
        headerPadding: '0 16px',
      },
      Menu: {
        itemBorderRadius: 8,
        itemHeight: 38,
        itemMarginInline: 8,
        itemMarginBlock: 2,
        itemSelectedBg: dark ? 'rgba(125, 140, 255, 0.16)' : 'rgba(91, 111, 240, 0.1)',
        itemSelectedColor: dark ? '#a8b2ff' : '#4152d2',
        itemHoverBg: dark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(42, 48, 64, 0.04)',
        itemColor: dark ? '#99a1b3' : '#5e6678',
        activeBarWidth: 0,
        activeBarBorderWidth: 0,
      },
      Card: {
        borderRadiusLG: 12,
        paddingLG: 16,
        headerHeight: 42,
        headerHeightSM: 34,
      },
      Button: {
        primaryShadow: 'none',
        defaultShadow: 'none',
        fontWeight: 500,
        paddingInline: 12,
      },
      Table: {
        headerBg: dark ? '#222733' : '#f5f7fb',
        headerColor: dark ? '#b9c0cf' : '#4a5163',
        headerSplitColor: 'transparent',
        rowHoverBg: dark ? 'rgba(125, 140, 255, 0.06)' : 'rgba(91, 111, 240, 0.045)',
        borderColor: dark ? '#262c38' : '#eef1f7',
        cellPaddingBlock: 7,
        cellPaddingInline: 10,
        cellPaddingBlockSM: 4,
        cellPaddingInlineSM: 8,
      },
      Tabs: {
        horizontalItemGutter: 18,
        horizontalItemPadding: '8px 0',
        titleFontSize: 13,
        horizontalMargin: '0 0 12px 0',
      },
      Segmented: {
        itemSelectedBg: dark ? 'rgba(125, 140, 255, 0.18)' : '#ffffff',
      },
      Modal: {
        borderRadiusLG: 12,
        titleFontSize: 15,
      },
      Drawer: {
        paddingLG: 16,
      },
      Descriptions: {
        itemPaddingBottom: 8,
      },
      Form: {
        itemMarginBottom: 16,
        verticalLabelPadding: '0 0 4px',
      },
      Tooltip: {
        borderRadius: 6,
      },
      List: {
        itemPadding: '8px 0',
      },
    },
  }
}
