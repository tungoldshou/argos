import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// dev 下浏览器直连 MiniMax 会被 CORS 拦。用 dev proxy 把同源 /minimax/* 转发到
// MiniMax 的 Anthropic 兼容端,浏览器侧请求同源即绕过 CORS。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_MINIMAX_URL || 'https://api.minimaxi.com/anthropic'
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/minimax': {
          target,
          changeOrigin: true,
          rewrite: (p: string) => p.replace(/^\/minimax/, ''),
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              proxyReq.removeHeader('cookie');
              proxyReq.removeHeader('origin');
              proxyReq.removeHeader('referer');
            });
          },
        },
      },
    },
  }
})
