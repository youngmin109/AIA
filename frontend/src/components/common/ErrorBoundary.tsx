import { Button } from './Button'
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { errorReportTemplate } from '../../api/errorReport'

interface State { error: Error | null; copied: boolean | null }

/**
 * Keeps a render error from blanking the whole window. Protected runs live in
 * the local server, so redrawing the console does not affect them.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, copied: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error, copied: null }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('AIA console render error', error, info.componentStack)
  }

  private copyReport = () => {
    const detail = this.state.error ? `${this.state.error.name}: ${this.state.error.message}` : undefined
    const text = errorReportTemplate(detail)
    if (!navigator.clipboard) { this.setState({ copied: false }); return }
    navigator.clipboard.writeText(text).then(() => this.setState({ copied: true }), () => this.setState({ copied: false }))
  }

  render() {
    const { error, copied } = this.state
    if (!error) return this.props.children
    return (
      <div className="error-boundary" role="alert">
        <div className="error-boundary-card">
          <h1>화면을 그리는 중 문제가 생겼습니다</h1>
          <p>실행 중인 보호 세션은 로컬 서버에서 계속 유지됩니다. 화면만 다시 그리면 이어서 사용할 수 있습니다.</p>
          <code className="mono">{error.name}: {error.message}</code>
          <div className="error-boundary-actions">
            <Button variant="cta" onClick={() => this.setState({ error: null, copied: null })}>다시 시도</Button>
            <Button variant="secondary" onClick={() => window.location.reload()}>새로 고침</Button>
            <Button variant="text" onClick={this.copyReport}>진단 정보 복사</Button>
          </div>
          {copied !== null && <p role="status">{copied ? '오류 신고 양식을 복사했습니다. 민감한 정보는 지운 뒤 공유하세요.' : '클립보드를 쓸 수 없습니다. 화면의 오류 내용을 직접 적어 주세요.'}</p>}
        </div>
      </div>
    )
  }
}
