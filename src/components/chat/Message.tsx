// Message.tsx — 渲染一轮对话:用户气泡 + agent 的 blocks。
// 连续的 activity blocks 在这里折叠成一个 ActivityTrail;text→Markdown;honesty→HonestyCard。
import type { Turn, Block } from '../../lib/chatReducer';
import { Markdown } from './Markdown';
import { ActivityTrail, type Activity } from './ActivityTrail';
import { HonestyCard } from './HonestyCard';

// 把 blocks 切成渲染段:连续 activity 合并为一组。
type Segment =
  | { kind: 'activities'; items: Activity[] }
  | { kind: 'text'; text: string; streaming: boolean }
  | { kind: 'honesty'; type: 'verify_failed' | 'escalation' | 'tampering'; detail: string }
  | { kind: 'error'; text: string };

// LLM 有时会把工具的 5xx 错误"抄"进文本流(不是走 error 事件);
// 这里把明显是 MiniMax/Anthropic 风格 API 错误的文本段重路由到 error 渲染,
// 否则它会以 Markdown 形式当正文出现,看起来像乱码。
export function looksLikeApiErrorText(s: string): boolean {
  return /^Error code:\s*\d{3}\b/.test(s) && /api_error/.test(s);
}

function segment(blocks: Block[]): Segment[] {
  const segs: Segment[] = [];
  for (const b of blocks) {
    if (b.kind === 'activity') {
      const last = segs[segs.length - 1];
      if (last && last.kind === 'activities') last.items.push({ call: b.call, result: b.result });
      else segs.push({ kind: 'activities', items: [{ call: b.call, result: b.result }] });
    } else if (b.kind === 'text') {
      if (looksLikeApiErrorText(b.text)) {
        segs.push({ kind: 'error', text: b.text });
      } else {
        segs.push({ kind: 'text', text: b.text, streaming: b.streaming });
      }
    } else if (b.kind === 'honesty') {
      segs.push({ kind: 'honesty', type: b.type, detail: b.detail });
    } else {
      segs.push({ kind: 'error', text: b.text });
    }
  }
  return segs;
}

export function Message({ turn }: { turn: Turn }) {
  const segs = segment(turn.blocks);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* 用户气泡(右对齐) */}
      <div style={{ alignSelf: 'flex-end', maxWidth: '85%', padding: '9px 13px', borderRadius: 14, background: 'color-mix(in oklab,var(--accent),transparent 86%)', color: 'var(--text-1)', fontSize: 13.5, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        {turn.user}
      </div>
      {/* agent blocks(左对齐) */}
      {segs.map((s, i) => {
        if (s.kind === 'activities') return <ActivityTrail key={i} activities={s.items} />;
        if (s.kind === 'honesty') return <HonestyCard key={i} type={s.type} detail={s.detail} />;
        if (s.kind === 'error')
          return (
            <div key={i} style={{ fontSize: 12.5, color: 'var(--danger)', padding: '8px 11px', borderRadius: 9, border: '1px solid color-mix(in oklab, var(--danger), transparent 70%)' }}>
              {s.text}
            </div>
          );
        // text
        return (
          <div key={i}>
            <Markdown text={s.text} />
            {s.streaming && <span style={{ animation: 'blink-caret 1s step-end infinite', color: 'var(--accent)' }}>▋</span>}
          </div>
        );
      })}
    </div>
  );
}
