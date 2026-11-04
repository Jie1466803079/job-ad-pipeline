import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` serves the page on port 5173 and passes API calls to intake-api on
// 127.0.0.1:8000, so the browser sees one origin and the session cookie works.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
    },
  },
})
