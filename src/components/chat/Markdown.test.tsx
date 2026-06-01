import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Markdown } from './Markdown';

describe('Markdown', () => {
  it('渲染标题与段落', () => {
    render(<Markdown text={'# 标题\n\n正文'} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('标题');
    expect(screen.getByText('正文')).toBeInTheDocument();
  });

  it('渲染无序列表', () => {
    render(<Markdown text={'- a\n- b'} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('渲染代码块并带语言标签', () => {
    const { container } = render(<Markdown text={'```python\nprint(1)\n```'} />);
    expect(screen.getByText('python')).toBeInTheDocument();
    // rehype-highlight 会把 `print`/`1` 拆进 hljs-* span,跨多节点;走 textContent 比对更稳。
    expect(container.textContent).toMatch(/print\(1\)/);
  });

  it('不渲染裸 HTML（XSS 防护：script 不进 DOM）', () => {
    const { container } = render(<Markdown text={'<script>alert(1)</script>正常'} />);
    expect(container.querySelector('script')).toBeNull();
  });
});
