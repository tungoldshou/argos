# Argos 语音 + 图片输入

> 设计出处：[`docs/superpowers/specs/2026-06-13-voice-image-input-design.md`](superpowers/specs/2026-06-13-voice-image-input-design.md)
> 实现计划：[`plans/2026-06-13-multimodal-core-and-attachments.md`](superpowers/plans/2026-06-13-multimodal-core-and-attachments.md)、
> [`voice-input.md`](superpowers/plans/2026-06-13-voice-input.md)、[`image-input-ux.md`](superpowers/plans/2026-06-13-image-input-ux.md)

## 这是什么

让 Argos 接受**语音输入**与**图片输入**。诚实前提：旗舰形态是终端 TUI（Textual），
终端做不了 GUI 式的「按住说话 / 剪贴板直接贴图」，所以输入能力做成**与界面无关的共享内核**
（`argos/input/`），TUI 先用、桌面壳成熟后复用同一套。

管线产出两样东西：一段**文本**（语音转写并入 prompt，走老路）和一组**图片附件**
（走方案 C 的边车 `attachments` 字段，只在协议适配器一处物化成 wire 格式）。

## 现状速览（已落地 vs 待接线）

诚实是产品铁律——这张表区分「真能用」和「数据层就绪但 UX 未接」，不要把后者当前者：

| 能力 | 状态 | 说明 |
|---|---|---|
| **语音输入（空格录音）** | ✅ 已端到端接 | 输入框为空时按空格 → 录音 → 再按停止 → 转写 → 文本注入输入框（不自动提交）。`tui/widgets/prompt.py` + `tui/app.py._voice_toggle`。 |
| **多模态模型管线** | ✅ 已落地并测 | `loop.run(goal, attachments=[ImageAttachment,...])` 端到端可用：`tier.multimodal` 门禁 → 边车注入 → Anthropic/OpenAI 两套 wire 格式物化。单测覆盖。 |
| **STT provider 抽象** | ✅ 已落地 | 本地默认（faster-whisper，Apple Silicon 走 mlx），云端可选（OpenAI 兼容 `/audio/transcriptions`）。 |
| **图片输入 TUI 入口** | ⏳ 待接线 | 数据层（`ImageAttachment`、路径检测、校验、base64）与协议物化已就绪并测过，**但 TUI 提交流尚未产出 `ImageAttachment` 喂给 run**——`app.py` 当前调用 `loop.run()` 不传 `attachments`，也未 import `attachments` 模块。 |
| **剪贴板贴图 / 统一粘贴管线 / 粘贴 chip** | ⏳ 未实现 | spec §6.2 的 `Ctrl+V` 贴图、长文本占位 chip、`clipboard_image.py` 本期未落地（无该模块）。 |

**一句话**：语音真能用；图片的「数据 + 协议」地基铺好了，但 TUI 上还没有把图片送进一次运行的入口。

## `input/` 子包

`argos/input/` —— 高内聚、可独立测试、纯宿主进程（沙箱外）。

| 模块 | 公开 API | 职责 / 诚实边界 |
|---|---|---|
| `attachments.py` | `ImageAttachment`（frozen dataclass：`data`/`media_type`/`source_label`/`width`/`height`）；`sniff_media_type`、`validate_attachment`、`to_base64`、`extract_image_paths`、`load_from_path` | 纯逻辑、无网络 I/O。白名单 png/jpeg/webp/gif；单张 ≤5MB；未知格式/超限 → `ValueError`，绝不静默剥除或返回假 MIME。 |
| `recorder.py` | `Recorder`（`start()` / `stop() -> np.ndarray`）、`RecorderError` | sounddevice 开关式录音 → float32 16kHz 单声道。无后端 / 无麦克风 / 空录音 → `RecorderError`，不静默。Linux 缺 `libportaudio2` 给明确提示。 |
| `stt.py` | `Transcriber`（Protocol）、`LocalWhisper`、`CloudWhisper`、`make_transcriber`、`is_apple_silicon`、`SttError` | provider-agnostic。本地 `LocalWhisper`：Apple Silicon 试 `mlx-whisper`，失败回退 `faster-whisper`（仍本地），权重首次使用懒下载。云端 `CloudWhisper`：OpenAI 兼容，需 `cloud-stt` extra。失败一律 `SttError`，不伪造转写。 |
| `stt_config.py` | `SttConfig`（frozen：`provider`/`model`/`base_url`/`api_key`）、`load_stt_config` | 读 `~/.argos/config.json` 的 `stt` 块；无文件/无块 → 全默认（本地 `base`）。`provider="cloud"` 时从 `~/.argos/.env` 解析 `api_key_env` 指向的 key。 |

平台判定用显式 `platform.system()=='Darwin' and platform.machine()=='arm64'`，
**不靠 `ImportError`**——Linux 也有 mlx 轮子，靠 import 失败判定会静默跑错路径。

## 多模态模型路径（方案 C：边车 attachments）

零回归是硬约束：无附件的消息行为与改动前**逐字节一致**（`content` 仍是裸字符串）。

- **能力位**：`ModelTier.multimodal: bool`（[`core/models.py`](../argos/core/models.py)），来自 config / setup 探针，默认 `False`。
- **门禁**（[`core/loop.py`](../argos/core/loop.py) `run()`）：存在附件但 `tier.multimodal=False` →
  抛诚实错误「当前模型不支持图像输入」，顶层兜底转 `Error` 事件——**绝不静默剥图、绝不假装看到**。
- **注入**：通过门禁后，附件挂在首条 user 消息的 `attachments` 边车字段（`content` 保持字符串）。
- **物化**（[`core/protocols.py`](../argos/core/protocols.py) `payload()` 一处）：
  - Anthropic：`content` → `[{"type":"text",...}, {"type":"image","source":{"type":"base64",...}}]`
  - OpenAI：`content` → `[{"type":"text",...}, {"type":"image_url","image_url":{"url":"data:<mime>;base64,..."}}]`
  - `_coalesce_consecutive_roles` 合并同 role 时 `attachments` 列表一并 concat，不触发崩溃。

## TUI 接线（[`tui/app.py`](../argos/tui/app.py) + [`tui/widgets/prompt.py`](../argos/tui/widgets/prompt.py)）

**语音（已接）**：`PromptArea` 在输入框为空时拦截空格，发 `VoiceToggle` 消息；
`app.on_prompt_area_voice_toggle → _voice_toggle` 开/停录音，转写在 `asyncio.to_thread` 上跑，
转写文本经 `load_text`/普通插入注入（**不模拟粘贴**，避开无标记注入卡死），**不自动提交**
——用户瞄一眼再回车，防听岔伪装成功。录音/转写/失败都在活动区给明确状态。
`/voice` 斜杠命令为可发现兜底入口。

**图片（待接）**：spec §6.2–6.3 的 `Ctrl+V` 贴图、路径提交时自动附加、`[图片 #N]`/`[粘贴文本 #N]`
占位 chip、统一括号粘贴管线本期未接。要接的话，钩子是 `attachments.extract_image_paths` /
`load_from_path`（数据层已就绪），在 `on_prompt_area_submitted` 汇总 `(goal_text, attachments)`
后传给 `loop.run(..., attachments=...)`。

## 配置

`~/.argos/config.json`：

```jsonc
{
  "stt": {
    "provider": "local",        // "local"（默认）| "cloud"
    "model": "base",            // local: whisper 尺寸 tiny/base/small/…；cloud: 云模型 id
    "base_url": null,           // cloud: OpenAI 兼容端点
    "api_key_env": "OPENAI_API_KEY"   // cloud: 指向 ~/.argos/.env 里的 key 名
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

- **语音默认开**：`sounddevice` + `faster-whisper` 进**基础依赖**（随 `uv sync` 装），模型权重不进包、首次录音懒下载。
- **Apple Silicon 加速**：`mlx-whisper` 作条件依赖（`sys_platform=='darwin' and platform_machine=='arm64'`）。
- **云端 STT 可选**：`pyproject.toml` 的 `cloud-stt = ["openai>=1.0.0"]` extra——`uv sync --extra cloud-stt` 开启。
- **禁 GPL/AGPL 运行依赖**：底层积木全 MIT/Apache（见 spec §4.1）；GPL 工具仅作只读设计参考，绝不拷码。

## 测试

- `tests/input/`：`test_attachments`、`test_recorder`、`test_stt`、`test_stt_config`（单元：路径检测/校验/媒体类型嗅探、fake `Transcriber`、mock 后端 + 诚实错误路径）
- `tests/input/test_model_tier_multimodal`、`test_protocols_multimodal`、`test_loop_multimodal`（能力位、image block 形状、门禁阻断不发请求、零回归）
- `tests/tui/test_voice.py`：空格触发 `VoiceToggle`、非空空格正常输入、录音→转写→注入循环
- `tests/test_capability_stt_egress.py`：云端 STT host 进 egress allowlist
- `tests/test_pyproject_voice_deps.py`：语音依赖声明

## 范围与分期（YAGNI）

- **本期（TUI）**：语音 = 空格（空框）触发（默认开）；多模态模型内核（方案 C）端到端就绪。
- **下一期**：图片输入 TUI 入口（路径自动附加 → `Ctrl+V` 剪贴板贴图 → 统一粘贴管线 + 占位 chip）；桌面壳复用同一 `input/` 内核，加「按住空格说话」+ 拖拽上传。
- **明确不做**：实时流式 STT；视频/音频附件喂模型；TUI 内联显示图片缩略（终端图形协议碎，留给桌面期，本期只显示 chip）。
