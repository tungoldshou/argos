// platforms.ts — platform hue metadata + oklch color helper.
import type { PlatformKind } from '../data/types';

export const PLATFORM_META: Record<string, { label: string; hue: number }> = {
  telegram: { label: 'Telegram', hue: 220 },
  discord: { label: 'Discord', hue: 265 },
  slack: { label: 'Slack', hue: 320 },
  whatsapp: { label: 'WhatsApp', hue: 150 },
  signal: { label: 'Signal', hue: 235 },
  email: { label: 'Email', hue: 30 },
  cli: { label: 'CLI', hue: 80 },
  matrix: { label: 'Matrix', hue: 175 },
  teams: { label: 'Teams', hue: 270 },
  sms: { label: 'SMS', hue: 130 },
  feishu: { label: 'Feishu', hue: 200 },
  dingtalk: { label: 'DingTalk', hue: 230 },
  wecom: { label: 'WeCom', hue: 145 },
  gchat: { label: 'Google Chat', hue: 145 },
  homeassistant: { label: 'Home Assistant', hue: 210 },
};

export function pColor(kind: PlatformKind | string, l = 0.7, c = 0.11): string {
  const m = PLATFORM_META[kind] ?? { hue: 70 };
  return `oklch(${l} ${c} ${m.hue})`;
}
