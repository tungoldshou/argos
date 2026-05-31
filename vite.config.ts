import { defineConfig, loadEnv, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';

// dev 下浏览器直连 8642 会被 CORS 拦(Hermes 不发 Access-Control-Allow-Origin)。
// 用 dev proxy 把同源 /hermes/* 转发到本地 Hermes,浏览器侧请求同源即绕过 CORS。
export default defineConfig(({ mode }: { mode: string }) => {
  const env = loadEnv(mode, '.', '');
  const target = env.VITE_HERMES_URL || 'http://127.0.0.1:8642';
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/hermes': {
          target,
          changeOrigin: true,
          rewrite: (p: string) => p.replace(/^\/hermes/, ''),
          // 浏览器会把 localhost 域下无关站点的 cookie 一起带上,Hermes(aiohttp)对带 cookie
          // 的请求返回 403。转发前剥掉 cookie/origin/referer,只留 Authorization。
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              proxyReq.removeHeader('cookie');
              proxyReq.removeHeader('origin');
              proxyReq.removeHeader('referer');
            });
          },
        } satisfies ProxyOptions,
      },
    },
  };
});
