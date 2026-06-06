// contracts.test.ts — 锁住 domainOf 的领域识别行为。
// 核心命题:模板是护城河,但选错模板=白搭。所以领域识别必须可靠,
// 尤其要覆盖「正则字面词识别不了、但语义明确」的目标。
import { describe, it, expect, vi } from 'vitest';
import { domainOf } from './contracts';
import type { ChatFn } from '../lib/llm';

describe('domainOf — 正则兜底(无 chat,向后兼容/离线)', () => {
  it('字面命中关键词时直接归类', async () => {
    expect(await domainOf('设计一个 REST API')).toBe('rest-api');
    expect(await domainOf('数据库 schema 设计')).toBe('db-schema');
    expect(await domainOf('订单状态机流转')).toBe('state-machine');
    expect(await domainOf('写一份 config 配置文件')).toBe('config');
  });

  it('无任何关键词时落 generic', async () => {
    expect(await domainOf('帮我把这个流程拆开')).toBe('generic');
  });
});

describe('domainOf — LLM 语义分类(有 chat)', () => {
  it('把语义明确但无字面词的目标交给 LLM,并采纳其结果', async () => {
    // 「用户登录流程」没有 state/状态机 字面词,正则会落 generic,
    // 但语义上是状态机。LLM 应能识别。
    const chat: ChatFn = vi.fn(async () => 'state-machine');
    expect(await domainOf('把用户登录流程拆成可复用的服务', chat)).toBe('state-machine');
    expect(chat).toHaveBeenCalledTimes(1);
  });

  it('容忍 LLM 输出里的杂音(空格/引号/解释)', async () => {
    const chat: ChatFn = vi.fn(async () => '  领域: "rest-api" \n(因为是接口对接)');
    expect(await domainOf('做一个支付回调对接', chat)).toBe('rest-api');
  });

  it('LLM 返回非法领域时安全降级到 generic', async () => {
    const chat: ChatFn = vi.fn(async () => 'banana');
    expect(await domainOf('随便什么目标', chat)).toBe('generic');
  });

  it('LLM 抛错时降级到正则兜底,不让整个 run 崩', async () => {
    const chat: ChatFn = vi.fn(async () => {
      throw new Error('model down');
    });
    // 目标含 "api" 字面词 → 兜底正则仍能命中 rest-api
    expect(await domainOf('设计订单 api', chat)).toBe('rest-api');
  });
});
