# Argos 桌面壳打包文档

## 构建产物

```
desktop/shell/src-tauri/target/release/bundle/macos/Argos.app   ← .app bundle
desktop/shell/src-tauri/target/release/bundle/dmg/Argos_0.1.0_aarch64.dmg
```

## 构建方法

```bash
# 在仓库根目录运行
bash packaging/build_desktop.sh

# debug 构建(更快,不启用 LTO/strip)
bash packaging/build_desktop.sh --debug
```

### 前提依赖

| 依赖 | 说明 |
|------|------|
| Node.js + npm | `npm ci` 安装 @tauri-apps/cli |
| Rust toolchain | `cargo build`; aarch64-apple-darwin target |
| macOS 13.0+ | Tauri 2 最低系统版本 |

`build_desktop.sh` 依次执行:
1. `npm ci` — 安装 Node 依赖
2. `npx tsc` — 编译 TypeScript 前端
3. `npx tauri build` — Rust release 编译 + .app + .dmg bundle

## 签名状态

**当前: ad-hoc 签名,未公证。**

Tauri 默认以 `codesign -s -`(ad-hoc)签名产物。ad-hoc 签名:
- 可在本机直接运行(无 Gatekeeper 阻止)
- **无法**通过 Gatekeeper 分发给其他用户
- `codesign -dv` 输出 `Signature=adhoc`

### 正式分发所需步骤

1. Apple Developer ID 证书(Apple Developer Program,年费 99 USD)
2. 在 `tauri.conf.json` 的 `bundle.macOS` 节添加:
   ```json
   "signingIdentity": "Developer ID Application: <名字> (<TeamID>)"
   ```
3. 启用 Hardened Runtime:
   ```json
   "hardenedRuntime": true,
   "entitlements": "entitlements.plist"
   ```
4. 公证:
   ```bash
   xcrun notarytool submit Argos_0.1.0_aarch64.dmg \
       --apple-id <appleId> --team-id <teamId> \
       --password <app-specific-password> --wait
   xcrun stapler staple Argos.app
   ```

## Bundle 配置

- **Bundle ID**: `app.argos.shell`
- **版本**: `0.1.0`
- **最低系统版本**: macOS 13.0 (Ventura)
- **类别**: `public.app-category.productivity`
- **图标**: `desktop/shell/src-tauri/icons/` (由 `npx tauri icon` 从 `argos-icon-src.png` 生成)

## 已知限制

1. **Python 内核未捆绑**: `.app` 内不含 Argos Python daemon (argosd)。
   壳启动后需要 argosd 已在运行并监听 Unix socket。
   捆绑方案见 `docs/argos-v6-design.md`(p6-desktop-notes sidecar 方案)。

2. **屏幕授权**: ad-hoc 签名无系统识别的开发者身份,屏幕录制等隐私权限
   可能需要用户手动在系统设置中授权。

3. **Gatekeeper 拦截**: 其他用户运行未公证产物时会被 Gatekeeper 拦截,
   需要在"系统设置 > 隐私与安全性"手动允许,或通过 `xattr -cr Argos.app` 清除隔离位。

## 版本同步纪律

版本号单源: **`packaging/VERSION`**

每次发版(`/ship`)时同步更新三处:
```
packaging/VERSION
desktop/shell/src-tauri/tauri.conf.json  (.version)
desktop/shell/package.json               (.version)
```

不要手动改三处——用 `/ship` 脚本统一操作。
