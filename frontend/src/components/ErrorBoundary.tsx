import { Component, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
  fallbackTitle?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="glass-card p-6 flex flex-col items-center justify-center gap-3 text-center"
        >
          <AlertTriangle className="w-8 h-8 text-amber-400" />
          <p className="text-sm text-slate-300">
            {this.props.fallbackTitle ?? 'Bir hata oluştu'}
          </p>
          {import.meta.env.DEV && this.state.error?.message && (
            <p className="text-xs text-slate-500 max-w-xs">
              {this.state.error.message}
            </p>
          )}
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="mt-2 flex items-center gap-2 px-4 py-2 rounded-lg bg-iuGold/10 text-iuGold text-xs hover:bg-iuGold/20 transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
            Tekrar Dene
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
