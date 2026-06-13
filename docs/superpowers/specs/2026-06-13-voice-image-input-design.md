# Argos 语音 + 图片输入 — 设计

- 日期：2026-06-13
- 状态：设计已定稿，待实现
- 关联：`core/loop.py`、`core/models.py`、`core/protocols.py`、`tui/app.py`、`web.py`(provider 抽象样板)、`capability/`、`sandbox/broker.py`

## 1. 背景与目标

用户希望 Argos 支持**语音输入**与**图片/截图输入**，与市面产品基建保持一致。

诚实前提：Argos 旗舰形态是**终端 TUI(Textual)**，终端无法做 GUI 式的"按住说话 / 剪贴板直接粘图"。因此本设计把输入能力做成**与界面无关的共享内核**，TUI 先用、Tauri 桌面壳成熟后复用同一套；终端限制(无 key-hold、无内联图)在 TUI 期用等价交互替代，桌面期再补齐完整 GUI 体验。

## 2. 决策摘要(已锁定)

1. **形态**：共享输入内核放进 `argos/`，TUI 先接，桌面壳后接。
2. **STT 默认开**：语音随基础安装即用，不是可选 extra。默认本地引擎用**跨平台 `faster-whisper`**(各平台有 wheel)，**模型权重首次录音懒下载**(装机不胖)；Apple Silicon 自动走 `mlx-whisper` 加速路径；云端 provider 可选——首选 `openai`(Apache-2.0，多数用户已有 key)、次选 `deepgram-sdk`(MIT，流式强)，Groq(whisper)亦可；**MiniMax ASR 无第一方 Python SDK，从默认列表拿掉，仅当用户已配 MiniMax key 时作机会性 bonus**。provider-agnostic 单接口，镜像 `web.py` 的双后端模式；云端走 broker egress 白名单 + 审批闸。GitHub 调研结论：**无单一整包方案**覆盖整条 TUI 链路；底层积木全 MIT/Apache 可直接装，aider `/voice`(Apache-2.0)的录音循环作**参考重写**(不拷贝)，**按键录音 + provider 路由两层自己写**(Textual 生态无先例)。
3. **图片输入**：剪贴板读取(macOS `pngpaste`/AppKit，Linux `xclip`/`xsel`)+ prompt 内图片路径检测/拖拽，**两者都做**。键位用 **`Ctrl+V`**(贴合 Claude Code 肌肉记忆)。
4. **多模态降级**：路由模型纯文本时**诚实阻断 + 提示配置多模态模型**，绝不静默剥图、绝不假装看到。
5. **集成方案 C**：图片走边车 `attachments` 字段，`content` 保持字符串，只在协议适配器 `payload()` 一处物化成 wire 格式。
6. **录音键**：输入框为空时**空格**开始/停止录音；有字则空格恢复普通输入；`/voice` 斜杠命令始终作兜底。转写文本经 `load_text` 普通插入注入输入框，**不模拟粘贴**(避开 Claude Code issue #13183 的无标记注入卡死)。
7. **统一粘贴管线**(对齐 Claude Code)：拦截括号粘贴(bracketed paste, `ESC[200~…201~`)→ 分流：剪贴板图 → `[图片 #N]` chip(进 attachments)；超长文本(>10000 字符)→ `[粘贴文本 #N +X 行]` chip(进文本侧缓冲)；否则原样内联。**提交时展开**占位符回全文/附件，chip 本身不发模型。

## 3. 架构总览

```
用户动作  ──►  argos/input/  ──►  (goal_text, [ImageAttachment])  ──►  AgentLoop
  │                  │
  ├ 空格(空框)录音      ├ recorder.py → stt.py(Transcriber) → 转写文本(并入 goal_text)
  ├ Ctrl+V 粘贴         ├ paste 分流(TUI 侧)：图 → attachments；超长文本 → 文本侧缓冲
  └ 路径检测/拖拽        └ clipboard_image.py / path → attachments.py(ImageAttachment)
```

管线产出**一段文本**(语音转写 + 提交时展开的粘贴文本，并入 prompt 文本，走老路)与**一组图片附件**(走新边车字段)。

## 4. `input/` 子包模块

新增 `argos/input/`，高内聚、可独立测试：

| 模块 | 职责 | 依赖 / 诚实边界 |
|---|---|---|
| `recorder.py` | 麦克风采集 → WAV 缓冲(`sounddevice`，wheel 自带 PortAudio) | 基础依赖。无麦克风 / 无音频后端 → 诚实报错，不静默 |
| `stt.py` | provider-agnostic `Transcriber` 接口：`LocalWhisper` 默认(跨平台 `faster-whisper`，Apple Silicon 自动 `mlx-whisper` 加速；权重首次使用懒下载)+ `CloudWhisper`(`openai` 首选 / `deepgram-sdk` 次选 / Groq；MiniMax 仅机会性)可选 | 本地无 egress；云端后端走 broker egress + 审批闸 |
| `clipboard_image.py` | 读系统剪贴板图片(macOS `pngpaste`/AppKit；Linux `xclip`/`xsel`) | 不支持的平台 / 剪贴板无图 → 诚实报错 |
| `attachments.py` | `ImageAttachment` dataclass(`data: bytes`、`media_type`、`source_label`、`width`、`height`)；prompt 内图片路径检测；格式(png/jpeg/webp/gif)与尺寸 + 体积上限(单张 ≤5MB，对齐 Claude Code)校验；base64 编码助手 | 纯逻辑、无网络 I/O，易测 |

**依赖默认随基础安装**(语音默认开)：`sounddevice` + `faster-whisper` 进基础依赖；模型权重不进安装包，**首次录音懒下载**。`mlx-whisper` 作为 Apple Silicon 加速、按平台条件可选。云端 STT provider 的 SDK / key 才是真正可选项。

### 4.1 复用结论(GitHub 调研，9 候选已对抗式核验)

无单一整包方案覆盖「按键录音 → 转写 → 注入 Textual」全链路。底层积木全可拿来用，链路顶层自建：

| 用途 | 库 | license | 结论 |
|---|---|---|---|
| 采集 | `sounddevice` | MIT | 拿来用(mac/win 自带 PortAudio；Linux 需 `libportaudio2`) |
| 本地默认 STT | `faster-whisper` | MIT | 拿来用(无 FFmpeg 依赖，权重懒下载) |
| 快速预设 | `distil-large-v3`(经 faster-whisper) | MIT | 拿来用(零新依赖) |
| Apple 加速 | `mlx-whisper` | MIT | 拿来用(API 与 faster-whisper 同形) |
| 云端首选 | `openai` SDK | Apache-2.0 | 拿来用 |
| 云端次选 | `deepgram-sdk` | MIT | 部分(独立付费 key) |
| 录音循环 | aider `/voice` | Apache-2.0 | **参考重写**(~60-70 行，不拷贝) |
| 按键 toggle + provider 路由 | — | — | **自己写**(无先例；`pynput` 在 TUI 内不可用) |

只作参考、不作运行依赖(license 或诚实问题)：`RealtimeSTT`(无麦克风时无限重试，违反诚实门)、`SpeechRecognition`(轮子捆 GPL-2 FLAC 二进制)、`whisper_streaming`(作者已宣布弃用)、`pywhispercpp`(Linux v1.5.0 链接回归、无 Intel Mac 轮子)。GPL/AGPL 工具(`nerd-dictation`、`whisper-writer`、Open Interpreter)只读设计、绝不拷码。

## 5. 模型层改动(方案 C：边车 attachments)

- `ModelTier`(`models.py:23`)增能力位 `multimodal: bool`，来自 config / setup 探针。
- 用户消息形如 `{"role":"user","content":"<文本>","attachments":[ImageAttachment,...]}`。`content` 仍是字符串 → **store、压缩、诚实检查、`_coalesce_consecutive_roles`(`protocols.py:10`)全部不动**。
- `_coalesce_consecutive_roles` 合并连续同 role 时，文本照旧并接；`attachments` 列表一并 concat(不会触发字符串格式化 list 的崩溃)。
- 图片**只在协议适配器 `payload()` 一处**物化：
  - `AnthropicProtocol.payload`(`protocols.py:48`)：`content` → `[{"type":"text",...}, {"type":"image","source":{"type":"base64","media_type":...,"data":...}}]`。
  - `OpenAIProtocol.payload`(`protocols.py:119`)：`content` → `[{"type":"text",...}, {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]`。
  - **无附件的消息行为与现状逐字节一致**(`content` 仍是裸字符串)，零回归。
- **诚实门禁**：发请求前若存在附件但 `tier.multimodal` 为假 → 抛诚实错误"当前模型 X 不支持图像输入，请在 setup 配置一个多模态模型"，不静默剥图。

## 6. TUI 接线(`tui/app.py` + `tui/widgets/prompt.py`)

### 6.1 语音(空格触发)

输入框为空时 `PromptArea._on_key` 拦截空格 → 开始录音(右栏活动区 `🎙 录音中…`)→ 再按空格停止 → `转写中…` → 转写文本经 **`load_text` 普通插入**注入 PromptArea，**不自动提交**(用户瞄一眼再回车，防听岔伪装成功)。底部提示 `空格 语音`。输入框非空时空格恢复普通输入。`/voice` 斜杠命令为可发现入口。注入走 `load_text` 而非模拟粘贴，避开 issue #13183 的无标记注入卡死。

### 6.2 统一粘贴管线(`PromptArea` 拦 `events.Paste`)

现状：`PromptArea` 是 `soft_wrap=True` 的 `TextArea`，粘贴多行**原样塞入**(`prompt.py` 注释"直接粘贴多行文本:原样进入")。改为拦截 Textual 的 `events.Paste`(括号粘贴；与本项目禁用的 Kitty 键盘协议互不影响),按内容分流：

| 粘贴内容 | 处理 | 占位 chip |
|---|---|---|
| 剪贴板含图片(`Ctrl+V`) | 转 `ImageAttachment` 存附件侧缓冲 | `[图片 #N]` |
| 文本 > 10000 字符 | 全文存**文本侧缓冲**(`{token: full_text}`)，输入框只插占位符 | `[粘贴文本 #N +X 行]` |
| 其余文本 | 原样内联(行为不变) | — |

- 阈值 10000 字符,对齐 Claude Code；侧缓冲键 `#N` 在一个 run/会话内自增。
- chip 是只读 token,不可内联编辑(与 Claude Code 一致);删除 = 清空重来。
- 终端拖文件粘成路径 → 提交时由 `attachments.py` 路径检测转附件(见 6.3)。

### 6.3 提交流(展开)

`on_prompt_area_submitted`(`app.py:448`)提交时：
1. 把输入文本里的 `[粘贴文本 #N]` 占位符**展开回侧缓冲全文**;
2. 检测残留的图片**文件路径**转 `ImageAttachment`;
3. 汇总 `(goal_text, attachments)` → 传 loop;loop 构造首条 user 消息(`loop.py:1060`)时挂上 `attachments` 边车字段。占位 chip 本身**不进** `goal_text`、不发模型。

## 7. 配置 / setup / 能力注册

- `~/.argos/config.json`：模型 tier 增 `multimodal` 位；新增 `stt` 块(`provider`、本地模型名 / 云端 host + key 引用)。
- `setup` 向导：可选多模态探针；STT provider 选择 + 本地模型下载提示 / 云端连测。
- `CapabilityRegistry`(`capability/`)：注册云端 STT host 进 egress allowlist，broker 运行时据此识别网络动作。

## 8. 沙箱 / 宿主边界

录音、剪贴板读取、本地 STT 在**宿主进程**运行(与 LSP / hooks / MCP 同侧、沙箱外)——Seatbelt 子进程无网络、文件笼死，本就采不了音、读不了剪贴板。云端 STT 的网络出口由 broker egress 策略管。

## 9. 诚实与失败模式(产品铁律)

每条失败路径显式诚实，绝不伪绿：无麦克风、音频后端缺失、STT 失败 / 超时、剪贴板无图、剪贴板读取在当前平台不支持、图过大 / 格式不支持、模型非多模态——全部在活动区给明确原因；转写结果不自动提交，由用户确认。三条调研核验出的诚实点：(a) 首次权重懒下载(base ~145MB / large-v3 ~3GB)给**真实下载进度**，不伪装成"思考中"；(b) Linux 缺 `libportaudio2` 系统包 → 诚实暴露安装提示；(c) `mlx-whisper` 平台判定用显式 `platform.system()=='Darwin' and platform.processor()=='arm'`，**不靠 `ImportError`**(Linux 有 mlx 轮子会静默跑 CPU)。

## 10. 测试策略(TDD，80% 覆盖门)

- **单元**：`attachments` 路径检测 / 校验 / 媒体类型嗅探；`stt` 用 fake `Transcriber`；`recorder` / `clipboard_image` mock 后端 + 诚实错误路径；协议 image block 形状(Anthropic vs OpenAI)断言；coalesce 带附件不受影响；多模态门禁(纯文本 tier + 附件 → 诚实阻断、不发请求)。
- **`@pytest.mark.slow`**：真麦克风 / 真 whisper(CI 无麦克风 → 跳过并诚实标注 unverifiable)。

## 11. 范围与分期(YAGNI)

- **本期(TUI)**：第 4–10 节全部；语音 = 空格(空框)触发(默认开)，图片 = `Ctrl+V` 剪贴板 + 路径，统一粘贴管线 + 长文本占位 chip。
- **下一期(桌面壳)**：复用同一 `input/` 内核，加"按住空格说话" + 剪贴板直接粘 + 拖拽上传。
- **明确不做**：实时流式 STT(边说边出字)；视频 / 音频附件喂模型；TUI 内联**显示**图片缩略(终端图形协议碎，留给桌面期；本期只显示 chip)；粘贴占位符的内联编辑(与 Claude Code 一致,不做)。

## 12. 触及文件清单

- 新增：`argos/input/{__init__,recorder,stt,clipboard_image,attachments}.py`
- 改：`argos/core/models.py`(`ModelTier.multimodal`)、`argos/core/protocols.py`(两个 `payload()` + `_coalesce_consecutive_roles` 处理 attachments)、`argos/core/loop.py`(首条 user 消息挂 attachments + 多模态门禁)、`argos/tui/widgets/prompt.py`(空格录音拦截 + `events.Paste` 分流 + 占位 chip + 侧缓冲)、`argos/tui/app.py`(`Ctrl+V` / chip 渲染 / 提交展开流)、setup 向导、`capability/` 注册
- 配置：`~/.argos/config.json` schema(`stt` 块 + tier `multimodal`)
- 打包：`pyproject.toml` **基础依赖**增 `sounddevice` + `faster-whisper`(语音默认开)；`mlx-whisper` 作 Apple Silicon 条件依赖(`sys_platform=='darwin' and platform_machine=='arm64'`)；`openai` / `deepgram-sdk` 作可选 extra。**Python 版本**：在 3.12 验证(faster-whisper 在 3.13 有 PyAV 冲突 issue #1231，3.12 不受影响)，必要时为依赖加约束。**禁止 GPL/AGPL 运行依赖**(nerd-dictation/whisper-writer GPL-3、SpeechRecognition 捆 GPL-2 FLAC、pynput LGPL、Open Interpreter AGPL — 仅只读设计)。
- 测试：镜像上述模块的 `tests/`

## 13. 验收标准

1. 输入框空时按空格 → 录音 → 再按 → 转写文本进输入框；非空时空格正常输入。
2. `Ctrl+V` 剪贴板含图 → `[图片 #N]` chip → 提交后图片以正确 wire 格式到达模型(Anthropic / OpenAI 各验)。
3. 粘贴 >10000 字符文本 → `[粘贴文本 #N +X 行]` chip(不塞满输入框)→ 提交时展开回全文发模型；占位符本身不发。
4. prompt 里写图片路径 → 提交时自动附上。
5. 纯文本模型 + 附件 → 诚实阻断、不发请求、活动区给原因。
6. 无麦克风 / 不支持的平台 / 剪贴板无图 → 各自诚实报错，不崩、不伪绿。
7. 无附件的请求 payload 与现状逐字节一致(零回归)；普通短文本粘贴行为不变。
8. 语音默认随基础安装可用(无需额外 extra)；首次录音触发权重懒下载有明确进度/提示。
9. `uv run pytest` 全绿，覆盖 ≥ 80%。
