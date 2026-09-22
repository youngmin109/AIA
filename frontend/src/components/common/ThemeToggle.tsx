import { Icon } from './Icon'
import { useTheme } from '../../hooks/useTheme'

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()

  return (
    <button
      type="button"
      className="theme-toggle-btn"
      title={theme === 'dark' ? '라이트 테마로 전환' : '다크 테마로 전환'}
      aria-label="테마 전환"
      onClick={toggleTheme}
    >
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
    </button>
  )
}
