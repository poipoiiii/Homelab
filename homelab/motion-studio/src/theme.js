// 主题、画布尺寸与确定性随机：渲染层和排版层共用，不依赖任何 canvas 实现。
export const W = 1920;
export const H = 1080;

export const TRANSITIONS = ['wipe', 'slide', 'blinds', 'zoom', 'flash', 'split', 'cut'];

export const THEMES = {
  ink: {
    id: 'ink',
    name: '墨',
    desc: '深墨底 + 米白字 + 朱红印章，适合台账/纪录片',
    dark: true,
    bg1: '#0a0c0b',
    bg2: '#161b17',
    ink: '#f4eedd',
    soft: '#cec6b1',
    muted: '#8b8574',
    line: 'rgba(244,238,221,0.14)',
    lineSoft: 'rgba(244,238,221,0.07)',
    accent: '#d94a30',
    accent2: '#d8b25a',
    glow: 'rgba(217,74,48,0.20)',
    glow2: 'rgba(216,178,90,0.12)',
    grain: 0.06,
    vignette: 0.55,
  },
  paper: {
    id: 'paper',
    name: '纸',
    desc: '米纸底 + 墨黑字 + 朱红批注，适合榜单/说明书',
    dark: false,
    bg1: '#f1e8d5',
    bg2: '#e2d6bd',
    ink: '#17160f',
    soft: '#3b372b',
    muted: '#6d6653',
    line: 'rgba(23,22,15,0.18)',
    lineSoft: 'rgba(23,22,15,0.08)',
    accent: '#b0392a',
    accent2: '#8a6a1f',
    glow: 'rgba(176,57,42,0.10)',
    glow2: 'rgba(138,106,31,0.10)',
    grain: 0.07,
    vignette: 0.18,
  },
  signal: {
    id: 'signal',
    name: '信',
    desc: '深蓝黑 + 电光青 + 琥珀，适合数据播报/科技',
    dark: true,
    bg1: '#050c12',
    bg2: '#0b1a24',
    ink: '#eaf6f2',
    soft: '#a9c9c2',
    muted: '#6f8d88',
    line: 'rgba(120,220,200,0.18)',
    lineSoft: 'rgba(120,220,200,0.08)',
    accent: '#46e0bf',
    accent2: '#f5b544',
    glow: 'rgba(70,224,191,0.18)',
    glow2: 'rgba(245,181,68,0.10)',
    grain: 0.05,
    vignette: 0.5,
  },
};

export function themeOf(id) {
  return THEMES[id] || THEMES.ink;
}

/** 确定性随机，同一个 seed 每次渲染出来的装饰完全一致。 */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
