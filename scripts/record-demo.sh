#!/usr/bin/env bash
# record-demo.sh — 全自动录制 Argos / Context Lens 出圈 demo。
#
# 与旧版(模拟 Recordly 快捷键)不同:这版用 ffmpeg 直接抓屏,脚本完全
# 控制起停;用 cliclick 在大脑画布上做平滑拖拽轨迹,展示力导向物理。
# 你只需保证 Argos 窗口在 LIVE 状态、位置不动,然后跑这个脚本。
#
# 依赖(本机已装):ffmpeg(brew)、cliclick(brew)。
# 权限:终端需要「屏幕录制」+「辅助功能」两个权限
#   系统设置 → 隐私与安全性 → 屏幕录制 / 辅助功能 → 勾选你的终端 app。
set -euo pipefail

# ── 配置 ────────────────────────────────────────────────────────────
AVF_SCREEN_INDEX="1"        # ffmpeg avfoundation 屏幕设备号(本机:1 = Capture screen 0)
OUT="${1:-/tmp/argos-demo-$(date +%H%M%S).mp4}"

# 几何:逻辑坐标(AppleScript/cliclick 用)+ 物理坐标(ffmpeg 抓帧用)。
SCALE=2                              # Retina 缩放(物理/逻辑)
# Argos 窗口被铺满后实测落在 (0,39),内容区 1800×1071(标题栏含在内)。
WIN_X=0 ; WIN_Y=39 ; WIN_W=1800 ; WIN_H=1071
# 大脑中心(逻辑坐标,cliclick 用):窗口中点略偏上,避开底部指令栏。
CX=$(( WIN_X + WIN_W/2 ))            # 900
CY=$(( WIN_Y + WIN_H/2 - 70 ))      # 偏上,落在大脑簇

# ffmpeg 物理裁切:只录 Argos 窗口内容区,桌面/Dock/菜单栏都不入镜。
CROP_PW=$(( WIN_W * SCALE ))         # 3600
CROP_PH=$(( WIN_H * SCALE ))         # 2142
CROP_PX=$(( WIN_X * SCALE ))         # 0
CROP_PY=$(( WIN_Y * SCALE ))         # 78

FPS=30
COUNTDOWN=3
# ────────────────────────────────────────────────────────────────────

need() { command -v "$1" >/dev/null 2>&1 || { echo "✗ 缺少 $1"; exit 1; }; }
need ffmpeg ; need cliclick ; need osascript

focus_argos() {
  /usr/bin/osascript <<'OSA' >/dev/null 2>&1 || true
tell application "System Events"
  set procName to ""
  if exists (process "argos") then set procName to "argos"
  if exists (process "Argos") then set procName to "Argos"
  if procName is not "" then
    tell process procName
      set frontmost to true
      try
        set position of first window to {0, 37}
        set size of first window to {1800, 1132}
      end try
    end tell
  end if
end tell
OSA
}

# 平滑拖拽:从 (x1,y1) 到 (x2,y2)。
# 关键:整条拖拽在「单个 cliclick 进程」里完成(dd + 多个 dm + du 串联),
# 并用 -e <easing> 让 cliclick 自己在每段间做缓动插值 —— 系统级平滑移动,
# 不再是 shell 循环里 fork+sleep 的离散跳跃(那才是一卡一顿的根因)。
# steps 只决定我们喂几个路标,真正的丝滑由 -e 的插值产生。
EASING=320        # 越高越慢越顺(cliclick 缓动因子)
drag() {
  local x1=$1 y1=$2 x2=$3 y2=$4 steps=${5:-6}
  local cmds=("dd:${x1},${y1}")
  local i x y
  for ((i=1;i<=steps;i++)); do
    x=$(( x1 + (x2-x1)*i/steps ))
    y=$(( y1 + (y2-y1)*i/steps ))
    cmds+=("dm:${x},${y}")
  done
  cmds+=("du:${x2},${y2}")
  cliclick -e "$EASING" "${cmds[@]}"
}

echo "▸ Context Lens 全自动 demo 录制"
echo "  输出: $OUT"
echo "  确认 Argos 窗口在 ($WIN_X,$WIN_Y) ${WIN_W}x${WIN_H},LIVE 状态。"
echo

focus_argos
sleep 0.6

echo -n "▸ 倒数:"
for i in $(seq "$COUNTDOWN" -1 1); do echo -n " $i"; sleep 1; done; echo

# ── 开录:ffmpeg 后台,记下 PID ──────────────────────────────────────
echo "▸ 开始录制…"
ffmpeg -y -loglevel error \
  -f avfoundation -capture_cursor 1 -framerate "$FPS" -i "$AVF_SCREEN_INDEX" \
  -vf "crop=${CROP_PW}:${CROP_PH}:${CROP_PX}:${CROP_PY}" \
  -pix_fmt yuv420p -c:v libx264 -preset veryfast -crf 20 \
  "$OUT" >/tmp/argos-ffmpeg.log 2>&1 &
FF_PID=$!
sleep 1.5   # 让 ffmpeg 进入稳定抓帧

stop_rec() {
  echo "▸ 停止录制…"
  # ffmpeg 收到 q 优雅收尾(写完 moov atom)。发 q 到它的 stdin 不可行(后台),
  # 改用 SIGINT,ffmpeg 会 flush 并正常关闭文件。
  kill -INT "$FF_PID" 2>/dev/null || true
  wait "$FF_PID" 2>/dev/null || true
}
trap stop_rec EXIT

# ── 分镜(总长约 22s)───────────────────────────────────────────────
# 原则:小幅、来回对称、每次拖完回到原点附近放手,让图谱始终留在中心。
# self 节点(图谱重心)就在 (CX,CY) 附近;抓它轻拽再松手,看整体弹性回弹。

# 1) 静置 2.5s:观众先看到「活着的大脑」自然漂浮、念头流光。
sleep 2.5

# 2) 抓 self 往右轻拽,稍停,再回到原点附近松手 → 弹性回弹,图不偏离中心。
#    steps 少(6),靠 cliclick -e 缓动插值出连续滑动(像人手)。
echo "  · 拖拽展示物理(对称小幅)"
drag "$CX" "$CY" $(( CX+170 )) $(( CY+90 )) 6
sleep 0.5                                                            # 人手会在终点稍顿
drag $(( CX+170 )) $(( CY+90 )) $(( CX+20 )) $(( CY+10 )) 6          # 拽回原点附近再松手
sleep 1.8

# 3) 反向对称再来一次(左上),同样拽回原点松手。
drag "$CX" "$CY" $(( CX-180 )) $(( CY-70 )) 6
sleep 0.5
drag $(( CX-180 )) $(( CY-70 )) "$CX" "$CY" 6
sleep 1.8

# 4) 单击中心 self,展示「这是你 agent 的记忆中枢」(不拖,只点亮+可能弹卡)。
cliclick "c:${CX},${CY}"
sleep 1.6

# 5) 双击空白处 → fit() 复位,图谱平滑飞回完美居中(干净收尾)。
echo "  · 双击复位"
cliclick "dc:$(( CX+380 )),$(( CY-220 ))"
sleep 3.2   # 看 flyTo 动画归位 + 留干净的最后一帧

stop_rec
trap - EXIT

echo "✓ 完成: $OUT"
ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1 "$OUT" 2>/dev/null || true
echo "▸ 按 docs/context-lens-demo-script.md 的分镜剪,或直接转 gif 发帖。"
