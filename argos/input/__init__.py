"""argos/input — 语音/图片输入内核(spec §4)。

与界面无关的共享输入基础设施(TUI 等任意客户端复用)。
子模块：
  attachments  — ImageAttachment dataclass、路径检测、校验、base64
  recorder     — 麦克风采集(sounddevice)
  stt          — provider-agnostic Transcriber 接口
  clipboard_image — 剪贴板图片读取
"""
