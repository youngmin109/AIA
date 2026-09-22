const PATHS = {
  dashboard: 'M4 4h7v7H4V4zm9 0h7v4h-7V4zm0 6h7v10h-7V10zM4 13h7v7H4v-7z',
  settings:
    'M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zm8.94 3.5a7.4 7.4 0 0 0-.15-1.5l2.02-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.38.96a7.5 7.5 0 0 0-1.3-.75l-.36-2.53a.5.5 0 0 0-.5-.42h-3.84a.5.5 0 0 0-.5.42l-.36 2.53c-.47.19-.9.44-1.3.75l-2.38-.96a.5.5 0 0 0-.6.22L2.07 8.28a.5.5 0 0 0 .12.64l2.02 1.58a7.4 7.4 0 0 0 0 3l-2.02 1.58a.5.5 0 0 0-.12.64l1.92 3.32c.13.22.4.31.6.22l2.38-.96c.4.31.83.56 1.3.75l.36 2.53c.05.24.26.42.5.42h3.84c.24 0 .45-.18.5-.42l.36-2.53c.47-.19.9-.44 1.3-.75l2.38.96c.2.09.47 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.02-1.58c.1-.49.15-.99.15-1.5z',
  history: 'M12 3a9 9 0 1 0 9 9h-2a7 7 0 1 1-2.05-4.95L14 10h7V3l-2.6 2.6A8.98 8.98 0 0 0 12 3zm-1 4v6l5 3-.9 1.5L10 15V7h1z',
  results: 'M9 3l1.5 3.5L14 8l-3.5 1.5L9 13l-1.5-3.5L4 8l3.5-1.5L9 3zm9 6l1 2.3 2.3 1-2.3 1-1 2.3-1-2.3-2.3-1 2.3-1L18 9zM14 16l.7 1.6 1.6.7-1.6.7-.7 1.6-.7-1.6-1.6-.7 1.6-.7.7-1.6z',
  collapseLeft: 'M19 5H5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1zM10 5v14M7.5 9.5 5.5 12l2 2.5',
  collapseRight: 'M19 5H5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1zM14 5v14m2.5-9.5L18.5 12l-2 2.5',
  close: 'M6 6l12 12M18 6L6 18',
  sun: 'M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4 4.2 19.8M19.8 4.2l-1.4 1.4M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z',
  plus: 'M12 5v14M5 12h14',
  brand: 'M12 2 3 7v10l9 5 9-5V7l-9-5z',
  terminal: 'M5 6l5 6-5 6M12 18h7',
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
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
