# Argos 语音 + 图片输入

## 这是什么

让 Argos 接受**语音输入**与**图片输入**。诚实前提：旗舰形态是终端 TUI（Textual），
终端做不了 GUI 式的「按住说话 / 剪贴板直接贴图」，所以输入能力做成**与界面无关的共享内核**
（`argos/input/`），TUI 先用、桌面壳成熟后复用同一套。

管线产出两样东西：一段**文本**（语音转写并入 prompt，走老路）和一组**图片附件**
（走方案 C 的边车 `attachments` 字段，只在协议适配器一处物化成 wire 格式）。

## 现状速览（已落地）

诚实是产品铁律——这张表逐条标注「真能用」的能力：

| 能力 | 状态 | 说明 |
|---|---|---|
| **语音输入（空格录音）** | ◐ 未启用 | 当前构建没有 recorder/STT 实现；空输入框按空格或运行 `/voice` 只给诚实提示，不静默假装可用。 |
| **多模态模型管线** | ✅ 已落地并测 | `loop.run(goal, attachments=[ImageAttachment,...])` 端到端可用：`tier.multimodal` 门禁 → 边车注入 → Anthropic/OpenAI 两套 wire 格式物化。单测覆盖。 |
| **STT provider 抽象** | ✖ 未落地 | 后续接 `sounddevice` + 本地/云端 whisper 时再补。 |
| **图片输入 TUI 入口** | ✅ 已接线 | 数据层（`ImageAttachment`、路径检测、校验、base64）与协议物化就绪并测过；TUI 提交流汇总 `(goal_text, attachments)` 后喂给 run——`app.py` import `attachments` / `clipboard_image`，`handle_input` 带 `attachments` 一路传到 `start_run` → inline / daemon 两路 `loop.run(..., attachments=...)`。 |
| **剪贴板贴图 / 统一粘贴管线 / 粘贴 chip** | ✅ 已实现 | spec §6.2 的 `Ctrl+V` 贴图（`clipboard_image.py` → `action_paste_image`）、`[图片 #N]` 占位 chip（`prompt.register_image`）已落地。 |

**一句话**：图片真能用；语音当前只做诚实不可用提示，避免文档先行造成假功能。

## `input/` 子包

`argos/input/` —— 高内聚、可独立测试、纯宿主进程（沙箱外）。

| 模块 | 公开 API | 职责 / 诚实边界 |
|---|---|---|
| `attachments.py` | `ImageAttachment`（frozen dataclass：`data`/`media_type`/`source_label`/`width`/`height`）；`sniff_media_type`、`validate_attachment`、`to_base64`、`extract_image_paths`、`load_from_path` | 纯逻辑、无网络 I/O。白名单 png/jpeg/webp/gif；单张 ≤5MB；未知格式/超限 → `ValueError`，绝不静默剥除或返回假 MIME。 |
| `recorder.py`（计划） | `Recorder`（`start()` / `stop() -> np.ndarray`）、`RecorderError` | sounddevice 开关式录音 → float32 16kHz 单声道。无后端 / 无麦克风 / 空录音 → `RecorderError`，不静默。Linux 缺 `libportaudio2` 给明确提示。 |
| `stt.py`（计划） | `Transcriber`（Protocol）、`LocalWhisper`、`CloudWhisper`、`make_transcriber`、`is_apple_silicon`、`SttError` | provider-agnostic。本地 `LocalWhisper`：Apple Silicon 试 `mlx-whisper`，失败回退 `faster-whisper`（仍本地），权重首次使用懒下载。云端 `CloudWhisper`：OpenAI 兼容，需 `cloud-stt` extra。失败一律 `SttError`，不伪造转写。 |
| `stt_config.py`（计划） | `SttConfig`（frozen：`provider`/`model`/`base_url`/`api_key`）、`load_stt_config` | 读 Argos config directory 下 `config.json` 的 `stt` 块；无文件/无块 → 全默认（本地 `base`）。`provider="cloud"` 时从同一 config directory 下的 `.env` 解析 `api_key_env` 指向的 key。 |

平台判定用显式 `platform.system()=='Darwin' and platform.machine()=='arm64'`，
**不靠 `ImportError`**——Linux 也有 mlx 轮子，靠 import 失败判定会静默跑错路径。

## 多模态模型路径（方案 C：边车 attachments）

零回归是硬约束：无附件的消息行为与改动前**逐字节一致**（`content` 仍是裸字符串）。

- **能力位**：`ModelTier.multimodal: bool | None`（[`core/models.py`](../argos/core/models.py)），`None`=首次发图时自动探测，`true`/`false`=config/setup 显式 override。
- **门禁**（[`core/loop.py`](../argos/core/loop.py) `run()`）：存在附件且视觉能力解析为 false →
  抛诚实错误「当前模型不支持图像输入」，顶层兜底转 `Error` 事件——**绝不静默剥图、绝不假装看到**。
- **注入**：通过门禁后，附件挂在首条 user 消息的 `attachments` 边车字段（`content` 保持字符串）。
- **物化**（[`core/protocols.py`](../argos/core/protocols.py) `payload()` 一处）：
  - Anthropic：`content` → `[{"type":"text",...}, {"type":"image","source":{"type":"base64",...}}]`
  - OpenAI：`content` → `[{"type":"text",...}, {"type":"image_url","image_url":{"url":"data:<mime>;base64,..."}}]`
  - `_coalesce_consecutive_roles` 合并同 role 时 `attachments` 列表一并 concat，不触发崩溃。

## TUI 接线（[`tui/app.py`](../argos/tui/app.py) + [`tui/widgets/prompt.py`](../argos/tui/widgets/prompt.py)）

**语音（未启用）**：当前没有 `recorder.py` / `stt.py` / `VoiceToggle` 链路。
空输入框按空格会走同一个 `/voice` 入口，只显示当前构建未启用语音。

**图片（已接）**：spec §6.2–6.3 的 `Ctrl+V` 贴图（`clipboard_image.read_clipboard_image` →
`action_paste_image`）、`[图片 #N]` 占位 chip（`prompt.register_image`）已落地。提交时
`handle_input(text, attachments)` 汇总 `(goal_text, attachments)`，经 `start_run` 一路传给
inline / daemon 两路的 `loop.run(..., attachments=...)`——仅在真有附件时传 `attachments` kwarg，
无附件路径调用签名与改造前逐字一致。数据层钩子是 `attachments.extract_image_paths` / `load_from_path`。

## 配置

Argos config directory 默认是 `~/.argos`,可用 `ARGOS_CONFIG_DIR` 改到别处。
配置写在该目录下的 `config.json`：

```jsonc
{
  "stt": {
    "provider": "local",        // "local"（默认）| "cloud"
    "model": "base",            // local: whisper 尺寸 tiny/base/small/…；cloud: 云模型 id
    "base_url": null,           // cloud: OpenAI 兼容端点
    "api_key_env": "OPENAI_API_KEY"   // cloud: 指向同一 config directory 下 .env 里的 key 名
  }
  // 模型 tier 另带 multimodal 位，控制是否允许图像输入
}
```

云端 STT 的 host 由 `CapabilityRegistry`（`capability/`）注册进 egress allowlist，
broker 运行时据此识别网络动作并过审批闸。

## 沙箱 / 宿主边界

录音、本地 STT（以及未来的剪贴板读取）在**宿主进程**运行——与 LSP / hooks / MCP 同侧、沙箱外。
Seatbelt 子进程无网络、文件笼死，本就采不了音、读不了剪贴板。
**只有云端 STT 的网络出口走 broker egress 策略**。

## 诚实与失败模式

每条失败路径显式诚实，绝不伪绿：无麦克风、音频后端缺失、STT 失败/超时、图过大/格式不支持、
模型非多模态——全部在活动区给明确原因；转写结果不自动提交，由用户确认。
首次权重懒下载（base ~145MB / large-v3 ~3GB）给真实进度，不伪装成「思考中」。

## 依赖与打包

- **语音依赖未声明**：`pyproject.toml` 当前没有 `sounddevice` / `faster-whisper` / `mlx-whisper`。
- **后续接入时**：再决定本地 whisper 是否进基础依赖，云端 STT 是否做 extra。
- **禁 GPL/AGPL 运行依赖**：底层积木全 MIT/Apache（见 spec §4.1）；GPL 工具仅作只读设计参考，绝不拷码。

## 测试

- `tests/input/`：图片附件路径检测 / 校验 / 媒体类型嗅探。
- `tests/input/test_model_tier_multimodal`、`test_protocols_multimodal`、`test_loop_multimodal`（能力位、image block 形状、门禁阻断不发请求、零回归）
- `tests/test_tui_commands.py`：`/voice` 命令给诚实未启用提示。

## 范围与分期（YAGNI）

- **本期（TUI）**：多模态模型内核端到端就绪；图片输入 TUI 入口（路径附加 → `Ctrl+V` 剪贴板贴图 → `[图片 #N]` 占位 chip）已接通；语音只提示未启用。
- **下一期**：补 `recorder.py` / `stt.py` 后再接空格录音；桌面壳复用同一 `input/` 内核，加「按住空格说话」+ 拖拽上传。
- **明确不做**：实时流式 STT；视频/音频附件喂模型；TUI 内联显示图片缩略（终端图形协议碎，留给桌面期，本期只显示 chip）。
