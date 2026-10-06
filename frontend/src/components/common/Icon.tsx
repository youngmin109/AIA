const PATHS = {
  dashboard: 'M4 4h7v7H4V4zm9 0h7v4h-7V4zm0 6h7v10h-7V10zM4 13h7v7H4v-7z',
  settings:
    'M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zm8.94 3.5a7.4 7.4 0 0 0-.15-1.5l2.02-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.38.96a7.5 7.5 0 0 0-1.3-.75l-.36-2.53a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.53c-.47.19-.9.44-1.3.75l-2.38-.96a.5.5 0 0 0-.6.22L2.07 8.28a.5.5 0 0 0 .12.64l2.02 1.58a7.4 7.4 0 0 0 0 3l-2.02 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.22.4.31.6.22l2.38-.96c.4.31.83.56 1.3.75l.36 2.53c.05.24.26.42.5.42h3.84c.24 0 .45-.18.5-.42l.36-2.53c.47-.19.9-.44 1.3-.75l2.38.96c.2.09.47 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.02-1.58c.1-.49.15-.99.15-1.5z',
  history: 'M12 3a9 9 0 1 0 9 9h-2a7 7 0 1 1-2.05-4.95L14 10h7V3l-2.6 2.6A8.98 8.98 0 0 0 12 3zm-1 4v6l5 3-.9 1.5L10 15V7h1z',
  results: 'M9 3l1.5 3.5L14 8l-3.5 1.5L9 13l-1.5-3.5L4 8l3.5-1.5L9 3zm9 6l1 2.3 2.3 1-2.3 1-1 2.3-1-2.3-2.3-1 2.3-1L18 9zM14 16l.7 1.6 1.6.7-1.6.7-.7 1.6-.7-1.6-1.6-.7 1.6-.7.7-1.6z',
  close: 'M6 6l12 12M18 6L6 18',
  plus: 'M12 5v14M5 12h14',
  brand: 'M12 2 3 7v10l9 5 9-5V7l-9-5z',
  terminal: 'M5 6l5 6-5 6M12 18h7',
  agents: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm13 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zm-3-10 2 2 4-5',
  shieldPlain: 'M12 3 4.5 6v5.5c0 4.6 3.2 8 7.5 9.5 4.3-1.5 7.5-4.9 7.5-9.5V6L12 3Z',
  report: 'M4 20V10m6 10V4m6 16v-7m5 7H2',
  search: 'M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm6-2 4 4',
  home: 'M3 11.5 12 4l9 7.5M5.5 10v9.5h13V10',
  chat: 'M4 5h16v11H9l-5 4z',
  records: 'M7 4h10l3 3v13H7zM10 11h7M10 15h7M4 8v12h3',
  pulse: 'M3 12h4l2-5 4 10 2-5h6',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5',
  restore: 'M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4',
  clock: 'M12 7v5l3 2M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z',
  check: 'M5 12.5 10 17l9-10',
  alert: 'M12 8v5M12 16.5v.5M10.3 4.2 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0z',
  folder: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  block: 'M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18zM5.7 5.7l12.6 12.6',
  arrowRight: 'M5 12h14M13 6l6 6-6 6',
  refresh: 'M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5',
  info: 'M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18zM12 11v5M12 8v.5',
  stop: 'M7 7h10v10H7z',
  tree: 'M6 4v6M6 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM6 14v6M8 12h6M14 12v4h6M14 12V8h6',
  lock: 'M7 11V8a5 5 0 0 1 10 0v3M5 11h14v10H5z',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
