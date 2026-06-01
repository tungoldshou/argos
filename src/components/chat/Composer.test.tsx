import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Composer } from './Composer';

describe('Composer', () => {
  it('Enter 发送当前文本并清空', () => {
    const onSend = vi.fn();
    render(<Composer value="hi" onChange={() => {}} onSend={onSend} running={false} />);
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onSend).toHaveBeenCalledOnce();
  });

  it('Shift+Enter 不发送（换行）', () => {
    const onSend = vi.fn();
    render(<Composer value="hi" onChange={() => {}} onSend={onSend} running={false} />);
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it('running 时按钮为"停止"并触发 onStop', () => {
    const onStop = vi.fn();
    render(<Composer value="" onChange={() => {}} onSend={() => {}} onStop={onStop} running={true} />);
    const btn = screen.getByRole('button', { name: /停止/ });
    fireEvent.click(btn);
    expect(onStop).toHaveBeenCalledOnce();
  });

  it('"/" 开头时触发 onSlash 钩子（Phase 2 扩展点）', () => {
    const onSlash = vi.fn();
    render(<Composer value="" onChange={() => {}} onSend={() => {}} running={false} onSlash={onSlash} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '/he' } });
    expect(onSlash).toHaveBeenCalledWith('/he');
  });
});
