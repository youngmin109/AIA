import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// AIA 데스크톱 셸: 빌드 산출물이 PyInstaller의 --collect-all aia_web 이 이미
// 수집하는 src/aia_web/static/ 아래로 들어가야 패키징 플래그 변경 없이 exe에
// 포함된다. base를 /static/app/ 로 고정해 index.html이 어떤 라우트로
// 서빙되든(catch-all, /app 임시 경로 등) 자산 경로가 항상 올바르게 풀리게 한다.
export default defineConfig({
  plugins: [react()],
  base: '/static/app/',
  build: {
    outDir: '../src/aia_web/static/app',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
        ws: true,
      },
      '/static/fonts': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
      },
    },
  },
})
