# Context Lens — 30-60 秒出圈 Demo 脚本

> 目标:让一个被 "agent 到底在想什么" 折磨过的开发者,在 10 秒内 "卧槽" + 想转发。
> 原则:**只演真做得到的**(回放 / 图谱 / 实时点亮),不演做不到的(编辑窗口)。
> 一镜到底感,配字幕,无人声也行(适合 X / 即刻静音自动播放)。

---

## 版本 A（英文,主投 X / HN / Reddit）— 约 35 秒

| 秒 | 画面 | 字幕(叠在画面上) |
|---|---|---|
| 0-3 | 黑屏,中心一个琥珀色光点缓缓呼吸 | `Your AI agent is a black box.` |
| 3-6 | 光点炸开成一张发光的图谱(Argos 大脑),节点缓缓漂浮 | `Until now.` |
| 6-12 | 左下角一个小终端窗口:`claude` 在跑一个真实任务（"refactor auth"）。同时大脑里的节点**逐个点亮**、连线流光 | `This is Claude Code — thinking.` `Every file it reads. Every memory it recalls. Live.` |
| 12-18 | 镜头推进大脑,一簇节点高亮(auth.ts, middleware.ts, session.ts…),旁边浮出 "read · 0.4s" | `Watch its attention move.` |
| 18-24 | 切换:顶部出现三个小标签 `Claude Code / Codex / Hermes`,大脑瞬间长出更多节点(跨工具合并) | `Not one agent. All of them. One mind.` |
| 24-30 | 鼠标点一个节点,详情侧栏滑出("learned this week · ……",连接列表) | `Click any thought. See where it came from.` |
| 30-35 | 拉回全景,大脑安静呼吸,底部出现产品名 + 一行 | `Context Lens` `See what your agent is thinking. (local · open source)` |

**首帧封面(thumbnail)**:大脑全亮 + 大字 `I gave Claude Code eyes 👁`

---

## 版本 B（中文,主投 即刻 / V2EX / B站 / 小红书）— 约 40 秒

| 秒 | 画面 | 字幕 |
|---|---|---|
| 0-3 | 呼吸的光点 | `你的 AI agent 在想什么?` |
| 3-6 | 炸开成发光大脑 | `第一次,看得见。` |
| 6-14 | 终端里 `claude` 跑真实任务,大脑节点跟着点亮、流光 | `这是 Claude Code 正在思考——` `它读的每个文件、回忆的每条记忆,实时点亮。` |
| 14-20 | 推进,一簇文件节点高亮 | `看着它的注意力在移动。` |
| 20-27 | 顶部 `Claude Code / Codex / Hermes` 三标签,大脑合并长大 | `不是一个 agent,是你所有的 agent——一个大脑。` |
| 27-34 | 点节点,侧栏滑出来龙去脉 | `点开任意一个念头,看它从哪来。` |
| 34-40 | 全景 + 产品名 | `Context Lens` `看见你的 agent 在想什么。本地运行 · 开源` |

**首帧封面**:大脑全亮 + 大字 `我给 Claude Code 装了一双眼睛 👁`

---

## 配套发布文案（帖子正文,≤ 必要长度）

**英文(X 帖)**:
> Every AI coding agent is a black box. It reads 40 files, forgets the first,
> and you have no idea what's in its head.
>
> So I built Context Lens — a living map of what your agent reads, recalls,
> and uses. Across Claude Code, Codex & Hermes. Local. Open source.
>
> [video]
>
> 👁 watch it think → [link]

**中文(即刻 / V2EX)**:
> 用 Claude Code 最难受的一点:它是个黑盒。读了 40 个文件,读到后面忘了前面,
> 你根本不知道它脑子里此刻装着啥。
>
> 于是我做了个东西:把 agent 读过、记过、用过的东西,画成一张**活的、会发光的图谱**——
> 它在想什么,实时点亮。还能跨 Claude Code / Codex / Hermes 合并成一个大脑。
> **纯本地 · 开源**,不上传任何东西。
>
> 演示 👇

---

## 拍摄注意(诚实红线)

1. **真终端、真任务、真点亮** —— 别用假动画冒充。哪怕只点亮"读过的文件"也要是真 hook 抓的。
2. **不要出现"一键清理上下文""控制注意力"** —— 那是做不到的,演了就是骗,会被技术圈当场拆。
3. **强调 local / open source** —— 这是和 mem0/Supermemory(云)的差异,也是信任来源。
4. **跨工具那一刀(18-24s)是核心差异点** —— 即使 v1 只真接通了 Claude Code + Hermes,Codex 也至少要有真日志接入再演;不能凑数。
5. **首帧 + 前 3 秒决定生死** —— "装眼睛 👁" 这种具象钩子比 "可视化上下文" 这种抽象词强 10 倍。

---

## 这条视频要测什么

- **不是**"产品好不好" —— 是 **"这个钩子能不能让人停下来 + 转发"**。
- 达标线(发出后 2-4 周任一):视频 ≥ 1 万播放 / GitHub ≥ 500 star / 进 HN 首页。
- 达标 → 进 C(把采集器做成真原型,扩 Codex,放出可装的版本)。
- 不达标 → 钩子不够强,坦然收手,Argos 转作品集。
