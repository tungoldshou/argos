import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Message } from './Message';
import type { Turn } from '../../lib/chatReducer';

describe('Message', () => {
  it('渲染用户输入与 markdown 文本', () => {
    const turn: Turn = { id: 't1', user: '你好', blocks: [{ kind: 'text', text: '世界', streaming: false }] };
    render(<Message turn={turn} />);
    expect(screen.getByText('你好')).toBeInTheDocument();
    expect(screen.getByText('世界')).toBeInTheDocument();
  });

  it('连续的 activity 块折叠成一个 ActivityTrail', () => {
    const turn: Turn = {
      id: 't1',
      user: 'q',
      blocks: [
        { kind: 'activity', call: 'a()', result: undefined },
        { kind: 'activity', call: 'b()', result: 'ok' },
      ],
    };
    render(<Message turn={turn} />);
    // 默认收起，标题应为"用了 2 个工具"
    expect(screen.getByText(/用了 2 个工具/)).toBeInTheDocument();
  });

  it('honesty block 渲染为 HonestyCard', () => {
    const turn: Turn = {
      id: 't1',
      user: 'q',
      blocks: [{ kind: 'honesty', type: 'verify_failed', detail: '没过' }],
    };
    render(<Message turn={turn} />);
    expect(screen.getByText(/拦下了一次假完成/)).toBeInTheDocument();
    expect(screen.getByText('没过')).toBeInTheDocument();
  });

  it('streaming 文本块后接 ▋ 光标', () => {
    const turn: Turn = { id: 't1', user: 'q', blocks: [{ kind: 'text', text: '正在打', streaming: true }] };
    const { container } = render(<Message turn={turn} />);
    expect(container.textContent).toContain('正在打');
    // caret 是 <span>▋</span>，查 caret 字符
    expect(screen.getByText('▋')).toBeInTheDocument();
  });
});
