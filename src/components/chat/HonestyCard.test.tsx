import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { HonestyCard } from './HonestyCard';

describe('HonestyCard', () => {
  it('verify_failed 显示"拦下了一次假完成"标题与 detail', () => {
    render(<HonestyCard type="verify_failed" detail="测试没过" />);
    expect(screen.getByText(/拦下了一次假完成/)).toBeInTheDocument();
    expect(screen.getByText('测试没过')).toBeInTheDocument();
  });

  it('escalation 显示"诚实求助"标题', () => {
    render(<HonestyCard type="escalation" detail="卡住了" />);
    expect(screen.getByText(/诚实求助/)).toBeInTheDocument();
  });

  it('tampering 显示"改动了被保护的测试文件"标题与文件', () => {
    render(<HonestyCard type="tampering" detail="a_test.py、b_test.py" />);
    expect(screen.getByText(/被保护的测试文件/)).toBeInTheDocument();
    expect(screen.getByText(/a_test.py/)).toBeInTheDocument();
  });
});
