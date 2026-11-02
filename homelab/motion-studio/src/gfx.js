// 基础绘图层：主题、字体、文本排版、背景、颗粒、转场。
// 所有坐标都按 1920×1080 设计；渲染时由调用方整体 scale，720p 直接缩放。
import { createCanvas } from '@napi-rs/canvas';

export const W = 1920;
export const H = 1080;

export const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const easeOutCubic = (t) => 1 - Math.pow(1 - clamp(t), 3);
export const easeInOutCubic = (t) =>
  clamp(t) < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * clamp(t) + 2, 3) / 2;
export const easeOutExpo = (t) => (clamp(t) >= 1 ? 1 : 1 - Math.pow(2, -10 * clamp(t)));

/** 确定性随机，同一个 seed 每次渲染出来的粒子/装饰完全一致。 */
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

export const CJK = /[\u3400-\u9fff\uf900-\ufaff]/;

const FONT_SANS =
  process.env.FONT_SANS || '"Noto Sans CJK SC","Noto Sans SC","Source Han Sans SC",sans-serif';
const FONT_SERIF =
  process.env.FONT_SERIF || '"Noto Serif CJK SC","Noto Serif SC","Source Han Serif SC",serif';
const FONT_MONO = process.env.FONT_MONO || '"DejaVu Sans Mono","Noto Sans Mono",monospace';

/** 中文绝不能落到 MONO（DejaVu 没有中文字形，会变方块）。 */
export function familyFor(text, preferred = 'sans') {
  if (CJK.test(String(text ?? ''))) return 'sans';
  return preferred;
}

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
    fonts: { sans: FONT_SANS, serif: FONT_SERIF, mono: FONT_MONO },
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
    fonts: { sans: FONT_SANS, serif: FONT_SERIF, mono: FONT_MONO },
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
    fonts: { sans: FONT_SANS, serif: FONT_SERIF, mono: FONT_MONO },
  },
};

export function themeOf(id) {
  return THEMES[id] || THEMES.ink;
}

// ------------------------------------------------------------------ 溢出监控

export const monitor = {
  warnings: new Set(),
  reset() {
    this.warnings.clear();
  },
  warn(message) {
    if (this.warnings.size < 60) this.warnings.add(message);
  },
  list() {
    return [...this.warnings];
  },
};

// ------------------------------------------------------------------ 字体与文本

export function setFont(ctx, theme, { size = 32, weight = 400, family = 'sans', italic = false }) {
  ctx.font = `${italic ? 'italic ' : ''}${weight} ${size}px ${theme.fonts[family] || theme.fonts.sans}`;
}

export function measure(ctx, text, opts) {
  setFont(ctx, opts.theme, { ...opts, family: familyFor(text, opts.family || 'sans') });
  return ctx.measureText(String(text ?? '')).width;
}

function tokenize(text) {
  const pattern = /[A-Za-z0-9]+(?:['’\-_.][A-Za-z0-9]+)*|[ \t]+|[\s\S]/gu;
  return String(text ?? '').match(pattern) || [];
}

export function wrapText(ctx, text, maxWidth, opts) {
  const paragraphs = String(text ?? '').split(/\r?\n/);
  const lines = [];
  for (const paragraph of paragraphs) {
    if (paragraph === '') {
      lines.push('');
      continue;
    }
    let line = '';
    for (const token of tokenize(paragraph)) {
      const candidate = line + token;
      if (line && measure(ctx, candidate, opts) > maxWidth) {
        lines.push(line.trimEnd());
        line = token.trimStart();
      } else {
        line = candidate;
      }
    }
    lines.push(line.trimEnd());
  }
  return lines;
}

export function ellipsize(ctx, text, maxWidth, opts) {
  let out = String(text ?? '');
  if (measure(ctx, out, opts) <= maxWidth) return out;
  const chars = [...out];
  while (chars.length > 1 && measure(ctx, `${chars.join('')}…`, opts) > maxWidth) chars.pop();
  return `${chars.join('')}…`;
}

/** 单行文本；超宽自动省略并记一条监控告警。 */
export function drawText(ctx, text, x, y, opts) {
  const value = String(text ?? '');
  if (!value) return 0;
  const size = opts.size ?? 32;
  const theme = opts.theme;
  // MONO 字体没有中文字形，含中文时自动退回 SANS，避免出现方块
  const options = { ...opts, family: familyFor(value, opts.family || 'sans') };
  setFont(ctx, theme, options);
  const maxWidth = opts.maxWidth ?? W - 80;
  const finalText = ellipsize(ctx, value, maxWidth, options);
  if (finalText !== value) monitor.warn(`文本超宽已省略：${value.slice(0, 24)}…`);
  ctx.save();
  ctx.globalAlpha = opts.alpha ?? 1;
  ctx.fillStyle = opts.color || theme.ink;
  ctx.textAlign = opts.align || 'left';
  ctx.textBaseline = opts.baseline || 'alphabetic';
  ctx.fillText(finalText, x, y);
  ctx.restore();
  return measure(ctx, finalText, options);
}

/**
 * 段落文本，返回实际高度。
 * yTop 是文本框顶部（不是基线），内部用 textBaseline=top 排版。
 */
export function drawParagraph(ctx, text, x, yTop, maxWidth, opts) {
  const theme = opts.theme;
  const size = opts.size ?? 32;
  const options = { ...opts, family: familyFor(text, opts.family || 'sans') };
  const lh = opts.lineHeight ?? size * 1.32;
  const maxLines = opts.maxLines ?? 99;
  const all = wrapText(ctx, text, maxWidth, options);
  let lines = all;
  let truncated = false;
  if (all.length > maxLines) {
    truncated = true;
    lines = all.slice(0, maxLines);
    lines[maxLines - 1] = ellipsize(ctx, `${lines[maxLines - 1]}…`, maxWidth, options);
    monitor.warn(`段落超出 ${maxLines} 行：${String(text).slice(0, 20)}…`);
  }
  setFont(ctx, theme, options);
  ctx.save();
  ctx.globalAlpha = opts.alpha ?? 1;
  ctx.fillStyle = opts.color || theme.ink;
  ctx.textAlign = opts.align || 'left';
  ctx.textBaseline = 'top';
  lines.forEach((line, i) => {
    ctx.fillText(line, x, yTop + i * lh);
  });
  ctx.restore();
  return { height: lines.length * lh, lines: lines.length, truncated };
}

/** 二分找能放进 maxLines 行的最大字号。 */
export function fitSize(ctx, text, maxWidth, opts) {
  const max = opts.max ?? 120;
  const min = opts.min ?? 48;
  const maxLines = opts.maxLines ?? 2;
  let lo = min;
  let hi = max;
  for (let i = 0; i < 9; i += 1) {
    const mid = (lo + hi) / 2;
    const lines = wrapText(ctx, text, maxWidth, { ...opts, size: mid });
    const widest = Math.max(...lines.map((line) => measure(ctx, line, { ...opts, size: mid })), 0);
    if (lines.length <= maxLines && widest <= maxWidth) lo = mid;
    else hi = mid;
  }
  return Math.floor(lo);
}

export function roundRectPath(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

export function drawChip(ctx, text, x, y, theme, { size = 24, accent = false } = {}) {
  setFont(ctx, theme, { size, weight: 500, family: 'sans' });
  const padX = 20;
  const width = ctx.measureText(text).width + padX * 2;
  const height = size + 22;
  ctx.save();
  roundRectPath(ctx, x, y, width, height, height / 2);
  ctx.fillStyle = accent ? theme.accent : 'transparent';
  ctx.strokeStyle = accent ? theme.accent : theme.line;
  ctx.lineWidth = 1.5;
  if (accent) ctx.fill();
  else ctx.stroke();
  ctx.fillStyle = accent ? (theme.dark ? '#101210' : '#fff8e8') : theme.soft;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.font = `${size}px ${theme.fonts.sans}`;
  ctx.fillText(text, x + padX, y + height / 2 + 1);
  ctx.restore();
  return width;
}

// ------------------------------------------------------------------ 背景与氛围

let grainTiles = null;
function getGrainTile(dark) {
  if (!grainTiles) grainTiles = {};
  const key = dark ? 'light' : 'dark';
  if (grainTiles[key]) return grainTiles[key];
  const size = 180;
  const tile = createCanvas(size, size);
  const g = tile.getContext('2d');
  const image = g.createImageData(size, size);
  for (let i = 0; i < image.data.length; i += 4) {
    // 稀疏颗粒：只有约 22% 的像素有值，避免整帧噪点把码率顶爆
    const hit = Math.random() < 0.22;
    const v = dark ? 150 + Math.random() * 105 : 40 + Math.random() * 90;
    image.data[i] = v;
    image.data[i + 1] = v;
    image.data[i + 2] = v;
    image.data[i + 3] = hit ? 70 + Math.random() * 110 : 0;
  }
  g.putImageData(image, 0, 0);
  grainTiles[key] = tile;
  return tile;
}

function glow(ctx, x, y, radius, color) {
  const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
  grad.addColorStop(0, color);
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.save();
  ctx.fillStyle = grad;
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
  ctx.restore();
}

export function drawBackground(ctx, theme, t, seed = 7) {
  const grad = ctx.createLinearGradient(0, 0, W * 0.7, H);
  grad.addColorStop(0, theme.bg1);
  grad.addColorStop(0.62, theme.bg2);
  grad.addColorStop(1, theme.bg1);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  const rand = mulberry32(seed * 977 + 13);
  glow(ctx, W * (0.74 + 0.04 * Math.sin(t * 0.35)), H * 0.24, 760, theme.glow);
  glow(ctx, W * 0.16, H * (0.78 + 0.03 * Math.cos(t * 0.3)), 640, theme.glow2);

  // 细网格：纸主题做成横线稿纸，深色主题做成工程网格
  ctx.save();
  ctx.strokeStyle = theme.lineSoft;
  ctx.lineWidth = 1;
  if (theme.dark) {
    const step = 120;
    const drift = (t * 8) % step;
    for (let x = -step + drift; x < W + step; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
      ctx.stroke();
    }
    for (let y = 0; y < H; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.stroke();
    }
  } else {
    for (let y = 74; y < H; y += 58) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.stroke();
    }
    ctx.strokeStyle = theme.accent;
    ctx.globalAlpha = 0.18;
    ctx.beginPath();
    ctx.moveTo(118, 0);
    ctx.lineTo(118, H);
    ctx.stroke();
  }
  ctx.restore();

  // 缓慢飘移的微尘/粒子
  const count = theme.dark ? 64 : 26;
  ctx.save();
  for (let i = 0; i < count; i += 1) {
    const baseX = rand() * W;
    const baseY = rand() * H;
    const speed = 6 + rand() * 22;
    const x = (baseX + Math.sin(t * 0.4 + i) * 26 + W) % W;
    const y = (baseY - t * speed + H * 10) % H;
    const r = 0.8 + rand() * 2.2;
    ctx.globalAlpha = 0.08 + rand() * 0.22;
    ctx.fillStyle = i % 7 === 0 ? theme.accent2 : theme.ink;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  // 斜向色带，给画面一点方向感
  ctx.save();
  ctx.globalAlpha = theme.dark ? 0.045 : 0.05;
  ctx.translate(W * 0.62, 0);
  ctx.rotate(-0.32);
  for (let i = 0; i < 7; i += 1) {
    ctx.fillStyle = i % 2 ? theme.accent : theme.ink;
    ctx.fillRect(i * 130, -260, 18, H * 2);
  }
  ctx.restore();
}

export function drawGrain(ctx, theme, frameIndex) {
  const tile = getGrainTile(theme.dark);
  const pattern = ctx.createPattern(tile, 'repeat');
  if (!pattern) return;
  ctx.save();
  ctx.globalAlpha = theme.grain;
  ctx.globalCompositeOperation = theme.dark ? 'lighter' : 'multiply';
  const ox = (frameIndex * 37) % 180;
  const oy = (frameIndex * 61) % 180;
  ctx.translate(-ox, -oy);
  ctx.fillStyle = pattern;
  ctx.fillRect(0, 0, W + 360, H + 360);
  ctx.restore();
}

export function drawVignette(ctx, theme) {
  const grad = ctx.createRadialGradient(W / 2, H / 2, H * 0.28, W / 2, H / 2, H * 0.82);
  grad.addColorStop(0, 'rgba(0,0,0,0)');
  grad.addColorStop(1, theme.dark ? `rgba(0,0,0,${theme.vignette})` : `rgba(70,52,20,${theme.vignette})`);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);
}

export function drawSafeFrame(ctx, theme) {
  ctx.save();
  ctx.strokeStyle = theme.lineSoft;
  ctx.lineWidth = 1;
  ctx.strokeRect(56, 44, W - 112, H - 88);
  ctx.restore();
}

// ------------------------------------------------------------------ 转场

export const TRANSITIONS = ['wipe', 'slide', 'blinds', 'zoom', 'flash', 'split', 'cut'];

export function drawTransition(ctx, from, to, kind, p, theme) {
  const e = easeInOutCubic(p);
  ctx.save();
  ctx.globalAlpha = 1;
  switch (kind) {
    case 'slide': {
      ctx.drawImage(from, -W * e, 0, W, H);
      ctx.drawImage(to, W * (1 - e), 0, W, H);
      ctx.fillStyle = theme.accent;
      ctx.globalAlpha = 0.85;
      ctx.fillRect(W * (1 - e) - 3, 0, 6, H);
      break;
    }
    case 'wipe': {
      ctx.drawImage(from, 0, 0, W, H);
      const bands = 4;
      const bh = H / bands;
      for (let i = 0; i < bands; i += 1) {
        const q = easeOutCubic(clamp((p - i * 0.08) / (1 - i * 0.08)));
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, i * bh, W * q, bh);
        ctx.clip();
        ctx.drawImage(to, 0, 0, W, H);
        ctx.restore();
        ctx.fillStyle = theme.accent;
        ctx.globalAlpha = 0.7;
        ctx.fillRect(W * q - 3, i * bh, 6, bh);
        ctx.globalAlpha = 1;
      }
      break;
    }
    case 'blinds': {
      ctx.drawImage(from, 0, 0, W, H);
      const bars = 14;
      const bw = W / bars;
      for (let i = 0; i < bars; i += 1) {
        const q = easeOutCubic(clamp((p - (i % 5) * 0.06) / 0.82));
        ctx.save();
        ctx.beginPath();
        ctx.rect(i * bw, 0, bw, H * q);
        ctx.clip();
        ctx.drawImage(to, 0, 0, W, H);
        ctx.restore();
      }
      ctx.fillStyle = theme.accent;
      ctx.globalAlpha = 0.5;
      ctx.fillRect(0, H * e - 2, W, 4);
      break;
    }
    case 'zoom': {
      ctx.globalAlpha = 1 - e;
      ctx.drawImage(from, -W * 0.02, -H * 0.02, W * 1.04, H * 1.04);
      ctx.globalAlpha = e;
      const s = 0.94 + 0.06 * e;
      const dw = W * s;
      const dh = H * s;
      ctx.drawImage(to, (W - dw) / 2, (H - dh) / 2, dw, dh);
      break;
    }
    case 'flash': {
      ctx.drawImage(p < 0.5 ? from : to, 0, 0, W, H);
      ctx.globalAlpha = Math.pow(Math.sin(Math.PI * p), 2) * 0.9;
      ctx.fillStyle = theme.dark ? theme.ink : theme.accent;
      ctx.fillRect(0, 0, W, H);
      ctx.globalAlpha = Math.pow(Math.sin(Math.PI * p), 3);
      ctx.fillStyle = theme.accent;
      ctx.fillRect(0, H / 2 - 3, W, 6);
      break;
    }
    case 'split': {
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, W / 2, H);
      ctx.clip();
      ctx.drawImage(to, 0, -H * (1 - e), W, H);
      ctx.restore();
      ctx.save();
      ctx.beginPath();
      ctx.rect(W / 2, 0, W / 2, H);
      ctx.clip();
      ctx.drawImage(from, 0, H * e, W, H);
      ctx.restore();
      ctx.fillStyle = theme.accent;
      ctx.globalAlpha = 0.8;
      ctx.fillRect(W / 2 - 2, 0, 4, H);
      break;
    }
    default:
      ctx.drawImage(to, 0, 0, W, H);
  }
  ctx.restore();
}
