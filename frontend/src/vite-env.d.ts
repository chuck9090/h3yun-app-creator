/// <reference types="vite/client" />

declare module 'react-quill' {
  import * as React from 'react'

  export interface ReactQuillProps {
    value?: string
    defaultValue?: string
    onChange?: (value: string, delta?: unknown, source?: unknown, editor?: unknown) => void
    readOnly?: boolean
    placeholder?: string
    theme?: string
    modules?: unknown
    formats?: unknown
    bounds?: string | HTMLElement
    style?: React.CSSProperties
    className?: string
  }

  export default class ReactQuill extends React.Component<ReactQuillProps> {}
}
