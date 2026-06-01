// Composer.tsx — 多行 auto-grow 输入框。Enter 发送 / Shift+Enter 换行 / 运行中变停止。
// 预留扩展点(后续 phase):onSlash(斜杠命令)、leftSlot(附件)、rightSlot(麦克风)。
import { useRef, useEffect, type ReactNode } from 'react';

interface ComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  running: boolean;
  onStop?: () => void;
  placeholder?: string;
  onSlash?: (text: string) => void; // value 以 '/' 开头时回调(Phase 2)
  leftSlot?: ReactNode;             // 附件按钮位(Phase 6)
  rightSlot?: ReactNode;            // 麦克风按钮位(Phase 5)
}

export function Composer({ value, onChange, onSend, running, onStop, placeholder, onSlash, leftSlot, rightSlot }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // auto-grow:内容变化时按 scrollHeight 调高(上限 168px ≈ 8 行 @ fontSize 13 / line-height 1.5)。
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 168) + 'px';
  }, [value]);

  const change = (v: string) => {
    onChange(v);
    if (v.startsWith('/')) onSlash?.(v);
  };

  const keyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!running && value.trim()) onSend();
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
      {leftSlot}
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => change(e.target.value)}
        onKeyDown={keyDown}
        placeholder={placeholder ?? '给 Argos 一个目标…'}
        rows={1}
        disabled={running}
        style={{ flex: 1, resize: 'none', minHeight: 38, maxHeight: 168, padding: '9px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--surface-2, rgba(255,255,255,.03))', color: 'var(--text-1)', fontSize: 13, lineHeight: 1.5, fontFamily: 'inherit', outline: 'none' }}
      />
      {rightSlot}
      <button
        onClick={running ? () => onStop?.() : onSend}
        disabled={!running && !value.trim()}
        style={{ height: 38, padding: '0 16px', borderRadius: 10, border: 'none', background: running ? '#ff7a4d' : 'var(--accent)', color: '#1a1205', fontWeight: 700, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0 }}
      >
        {running ? '停止' : '发送'}
      </button>
    </div>
  );
}
