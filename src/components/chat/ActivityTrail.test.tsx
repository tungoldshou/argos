import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ActivityTrail } from './ActivityTrail';

const acts = [
  { call: 'web_search({"q":"x"})', result: '命中 3 条' },
  { call: 'web_extract({"url":"y"})', result: undefined },
];

describe('ActivityTrail', () => {
  it('默认收起，显示"用了 N 个工具"摘要', () => {
    render(<ActivityTrail activities={acts} />);
    expect(screen.getByText(/用了 2 个工具/)).toBeInTheDocument();
    // 收起态不展示具体调用文本
    expect(screen.queryByText(/web_search/)).toBeNull();
  });

  it('点击展开后显示每个调用与结果', () => {
    render(<ActivityTrail activities={acts} />);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByText(/web_search/)).toBeInTheDocument();
    expect(screen.getByText(/命中 3 条/)).toBeInTheDocument();
  });
});
