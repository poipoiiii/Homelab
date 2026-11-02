// 场景绘制：封面 / 章节 / 列表 / 数字 / 引用 / 结尾。
// 每个场景只负责内容，背景、颗粒、暗角、转场由 render.js 统一处理。
import {
  W,
  H,
  clamp,
  easeOutCubic,
  mulberry32,
  measure,
  drawText,
  drawParagraph,
  fitSize,
  wrapText,
  roundRectPath,
  drawChip,
  familyFor,
} from './gfx.js';
import { drawPortraitArt, PORTRAIT_STYLES } from './portrait.js';

const PAD = 136;
const INNER = 120;

function reveal(t, delay = 0, dur = 0.6) {
  return easeOutCubic(clamp((t - delay) / dur));
}

function pad2(n) {
  return String(n).padStart(2, '0');
}

export function fmtDuration(seconds) {
  const total = Math.max(1, Math.round(seconds));
  return total >= 60 ? `${Math.floor(total / 60)} 分 ${total % 60} 秒` : `${total} 秒`;
}

function drawTitleLines(ctx, lines, x, yTop, size, theme, t, delayBase = 0.14) {
  const lh = size * 1.12;
  lines.forEach((line, i) => {
    const e = reveal(t, delayBase + i * 0.1, 0.72);
    if (e <= 0.001) return;
    const y = yTop + i * lh + (1 - e) * 28;
    ctx.save();
    ctx.textBaseline = 'top';
    ctx.textAlign = 'left';
    ctx.font = `700 ${size}px ${theme.fonts.serif}`;
    if (theme.dark) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = e * 0.22;
      ctx.fillStyle = '#ff3b30';
      ctx.fillText(line, x - 3, y);
      ctx.fillStyle = '#22cfff';
      ctx.fillText(line, x + 3, y);
      ctx.globalCompositeOperation = 'source-over';
    }
    ctx.globalAlpha = e;
    ctx.fillStyle = theme.ink;
    ctx.fillText(line, x, y);
    ctx.restore();
  });
  return yTop + lines.length * lh;
}

function drawCornerTicks(ctx, theme, alpha = 0.35) {
  ctx.save();
  ctx.strokeStyle = theme.accent;
  ctx.globalAlpha = alpha;
  ctx.lineWidth = 2;
  const len = 26;
  const m = 56;
  const corners = [
    [m, m, 1, 1],
    [W - m, m, -1, 1],
    [m, H - m, 1, -1],
    [W - m, H - m, -1, -1],
  ];
  for (const [x, y, sx, sy] of corners) {
    ctx.beginPath();
    ctx.moveTo(x, y + sy * len);
    ctx.lineTo(x, y);
    ctx.lineTo(x + sx * len, y);
    ctx.stroke();
  }
  ctx.restore();
}

function drawBarcode(ctx, x, y, w, h, seed, theme) {
  const rand = mulberry32(seed);
  ctx.save();
  ctx.fillStyle = theme.soft;
  ctx.globalAlpha = 0.4;
  let cursor = x;
  while (cursor < x + w) {
    const bw = 2 + Math.floor(rand() * 5);
    const bh = h * (0.55 + rand() * 0.45);
    ctx.fillRect(cursor, y + (h - bh) / 2, bw, bh);
    cursor += bw + 3 + Math.floor(rand() * 5);
  }
  ctx.restore();
}

function drawSeal(ctx, x, y, size, text, theme) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(-0.12);
  ctx.strokeStyle = theme.accent;
  ctx.globalAlpha = 0.85;
  ctx.lineWidth = 4;
  roundRectPath(ctx, -size / 2, -size / 2, size, size, 6);
  ctx.stroke();
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 1.5;
  roundRectPath(ctx, -size / 2 + 9, -size / 2 + 9, size - 18, size - 18, 3);
  ctx.stroke();
  ctx.globalAlpha = 0.9;
  ctx.fillStyle = theme.accent;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = `700 ${Math.floor(size * 0.34)}px ${theme.fonts.serif}`;
  ctx.fillText(text, 0, 2);
  ctx.restore();
}

// ------------------------------------------------------------------ 封面

function drawCover(ctx, scene, t, theme, meta) {
  const data = scene.data;
  const kicker = reveal(t, 0.04, 0.6);

  // 顶部小标
  ctx.save();
  ctx.globalAlpha = kicker;
  ctx.fillStyle = theme.accent;
  ctx.fillRect(PAD, 150, 8, 46);
  drawText(ctx, data.kicker || '', PAD + 28, 174, {
    theme,
    size: 30,
    weight: 500,
    family: 'sans',
    color: theme.soft,
    baseline: 'middle',
    maxWidth: 900,
  });
  ctx.restore();

  // 右侧装饰环
  const cx = W - 336;
  const cy = 432;
  ctx.save();
  ctx.globalAlpha = 0.3;
  ctx.strokeStyle = theme.line;
  ctx.lineWidth = 1.5;
  for (const r of [196, 258, 308]) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha = 0.6;
  ctx.strokeStyle = theme.accent;
  const ticks = 60;
  for (let i = 0; i < ticks; i += 1) {
    const a = (i / ticks) * Math.PI * 2 + t * 0.06;
    const r1 = 308;
    const r2 = i % 5 === 0 ? 292 : 300;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
    ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2);
    ctx.stroke();
  }
  ctx.restore();

  // 标题
  const titleMaxWidth = 1160;
  const title = data.title || '';
  const size = fitSize(ctx, title, titleMaxWidth, {
    theme,
    max: 136,
    min: 60,
    maxLines: 3,
    weight: 700,
    family: 'serif',
  });
  const lines = wrapText(ctx, title, titleMaxWidth, {
    theme,
    size,
    weight: 700,
    family: 'serif',
  });
  const titleTop = 262;
  const titleBottom = drawTitleLines(ctx, lines, PAD, titleTop, size, theme, t);

  // 副标题
  if (data.subtitle) {
    const e = reveal(t, 0.32, 0.7);
    drawParagraph(ctx, data.subtitle, PAD, titleBottom + 22, 1000, {
      theme,
      size: 32,
      weight: 400,
      family: 'sans',
      color: theme.soft,
      lineHeight: 48,
      maxLines: 2,
      alpha: e,
    });
  }

  // 底部信息
  const ruleE = reveal(t, 0.42, 0.8);
  ctx.save();
  ctx.globalAlpha = 0.35 * ruleE;
  ctx.fillStyle = theme.line;
  ctx.fillRect(PAD, H - 216, (W - PAD * 2) * ruleE, 1);
  ctx.globalAlpha = 0.9 * ruleE;
  ctx.fillStyle = theme.accent;
  ctx.fillRect(PAD, H - 219, 74 * ruleE, 3);
  ctx.restore();

  const stats = meta.stats || {};
  const metaItems = [
    ['条目', `${stats.items ?? 0}`],
    ['章节', `${stats.sections ?? 0}`],
    ['时长', fmtDuration(meta.durationSec || 0)],
  ];
  let mx = PAD;
  for (const [label, value] of metaItems) {
    drawText(ctx, label, mx, H - 162, {
      theme,
      size: 22,
      family: 'sans',
      color: theme.muted,
      baseline: 'middle',
      alpha: 0.9 * ruleE,
    });
    drawText(ctx, value, mx + 54, H - 162, {
      theme,
      size: 28,
      weight: 600,
      family: 'mono',
      color: theme.ink,
      baseline: 'middle',
      alpha: 0.9 * ruleE,
    });
    mx += 250;
  }
  drawText(ctx, data.date || '', W - PAD, H - 162, {
    theme,
    size: 24,
    family: 'mono',
    color: theme.muted,
    align: 'right',
    baseline: 'middle',
    alpha: 0.9 * ruleE,
    maxWidth: 340,
  });

  if (data.footer) {
    drawText(ctx, data.footer, PAD, H - 96, {
      theme,
      size: 22,
      family: 'sans',
      color: theme.muted,
      alpha: 0.8 * ruleE,
      maxWidth: 1200,
    });
  }

  // 右下角条码与印章
  drawBarcode(ctx, W - PAD - 260, H - 330, 260, 64, scene.seed, theme);
  drawSeal(ctx, W - PAD - 96, H - 470, 132, '核验', theme);

  drawCornerTicks(ctx, theme, 0.4 * reveal(t, 0.2, 0.6));
}

// ------------------------------------------------------------------ 章节

function drawSection(ctx, scene, t, theme) {
  const data = scene.data;
  const idx = data.index || 0;

  // 右侧大号章节数字
  ctx.save();
  ctx.globalAlpha = 0.09 * reveal(t, 0.05, 0.7);
  ctx.fillStyle = theme.ink;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'top';
  ctx.font = `700 300px ${theme.fonts.mono}`;
  ctx.fillText(pad2(idx + 1), W - PAD + 24, 96);
  ctx.restore();

  // 左侧竖线
  const lineE = reveal(t, 0.1, 0.7);
  ctx.save();
  ctx.fillStyle = theme.accent;
  ctx.globalAlpha = 0.9;
  ctx.fillRect(PAD - 34, 352, 6, 220 * lineE);
  ctx.restore();

  drawText(ctx, 'CHAPTER', PAD, 322, {
    theme,
    size: 22,
    weight: 500,
    family: 'mono',
    color: theme.muted,
    baseline: 'middle',
    alpha: reveal(t, 0.12, 0.6),
  });

  const headingSize = fitSize(ctx, data.heading || '', 1180, {
    theme,
    max: 82,
    min: 52,
    maxLines: 2,
    weight: 600,
    family: 'serif',
  });
  drawParagraph(ctx, data.heading || '', PAD, 388, 1180, {
    theme,
    size: headingSize,
    weight: 600,
    family: 'serif',
    color: theme.ink,
    lineHeight: headingSize * 1.22,
    maxLines: 2,
    alpha: reveal(t, 0.2, 0.75),
  });

  if (data.caption) {
    drawText(ctx, data.caption, PAD, 596, {
      theme,
      size: 30,
      family: 'sans',
      color: theme.soft,
      alpha: reveal(t, 0.32, 0.7),
      maxWidth: 1080,
    });
  }

  // 章节进度
  const total = data.total || 1;
  const startX = PAD;
  const y = H - 176;
  const gap = 18;
  for (let i = 0; i < Math.min(total, 16); i += 1) {
    const active = i === idx;
    ctx.save();
    ctx.globalAlpha = active ? 1 : 0.4;
    ctx.fillStyle = active ? theme.accent : theme.line;
    ctx.fillRect(startX + i * gap, y, active ? 34 : 10, 4);
    ctx.restore();
  }
  drawText(ctx, `${pad2(idx + 1)} / ${pad2(total)}`, W - PAD, y + 2, {
    theme,
    size: 22,
    family: 'mono',
    color: theme.muted,
    align: 'right',
    baseline: 'middle',
  });

  if (data.count) {
    drawText(ctx, `${data.count} 条记录`, PAD, H - 116, {
      theme,
      size: 24,
      family: 'sans',
      color: theme.muted,
      alpha: reveal(t, 0.4, 0.7),
    });
  }

  drawCornerTicks(ctx, theme, 0.25);
}

// ------------------------------------------------------------------ 列表

function drawList(ctx, scene, t, theme) {
  const data = scene.data;
  const items = data.items || [];
  const n = items.length;
  const page = data.page || 1;
  const pages = data.pages || 1;

  // 顶部
  drawText(ctx, data.heading || '', INNER, 88, {
    theme,
    size: 30,
    weight: 500,
    family: 'sans',
    color: theme.soft,
    baseline: 'middle',
    maxWidth: W - INNER * 2 - 320,
    alpha: reveal(t, 0.02, 0.6),
  });
  drawText(ctx, `${pad2(page)} / ${pad2(pages)}`, W - INNER, 88, {
    theme,
    size: 22,
    family: 'mono',
    color: theme.muted,
    align: 'right',
    baseline: 'middle',
    alpha: reveal(t, 0.02, 0.6),
  });

  const ruleE = reveal(t, 0.06, 0.7);
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.fillStyle = theme.line;
  ctx.fillRect(INNER, 132, (W - INNER * 2) * ruleE, 1);
  ctx.restore();

  const top = 196;
  const available = H - top - 120;
  const rowH = Math.min(180, available / Math.max(n, 1));
  // 条目少时把整块略微下移，避免页面下半部分空一大截（但不要沉到页面中央）
  const blockTop = top + Math.min(90, Math.max(0, (available - rowH * n) / 2));
  const labelSize = rowH >= 150 ? 50 : rowH >= 110 ? 44 : 36;
  const showNote = rowH >= 112;

  items.forEach((item, i) => {
    const e = reveal(t, 0.16 + i * 0.14, 0.55);
    if (e <= 0.001) return;
    const y = blockTop + i * rowH;
    const cy = y + rowH * 0.46;
    ctx.save();
    ctx.globalAlpha = e;
    ctx.translate(0, (1 - e) * 26);

    // 序号
    drawText(ctx, pad2(i + 1 + (page - 1) * (data.pageSize || n)), INNER, cy, {
      theme,
      size: 22,
      family: 'mono',
      color: i === 0 && page === 1 ? theme.accent : theme.muted,
      baseline: 'middle',
      alpha: 0.9,
      maxWidth: 40,
    });

    const labelX = INNER + 62;
    const valueText = String(item.value ?? '');
    const valueFamily = familyFor(valueText, 'mono');
    const valueSize = rowH >= 150 ? 40 : rowH >= 110 ? 36 : 30;
    const valueWidth = valueText
      ? Math.min(420, measure(ctx, valueText, { theme, size: valueSize, family: valueFamily, weight: 600 }) + 8)
      : 0;
    const labelMax = W - INNER - valueWidth - 60 - labelX;

    drawText(ctx, String(item.label ?? ''), labelX, cy - (showNote && item.note ? 14 : 0), {
      theme,
      size: labelSize,
      weight: 500,
      family: familyFor(item.label, 'sans'),
      color: theme.ink,
      baseline: 'middle',
      maxWidth: labelMax,
    });

    if (showNote && item.note) {
      drawText(ctx, String(item.note), labelX, cy + 26, {
        theme,
        size: 22,
        family: 'sans',
        color: theme.muted,
        baseline: 'middle',
        maxWidth: labelMax,
        alpha: 0.95,
      });
    }

    if (valueText) {
      drawText(ctx, valueText, W - INNER, cy, {
        theme,
        size: valueSize,
        weight: 600,
        family: valueFamily,
        color: theme.accent,
        align: 'right',
        baseline: 'middle',
        maxWidth: 420,
      });
    }

    ctx.globalAlpha = 0.14 * e;
    ctx.fillStyle = theme.line;
    ctx.fillRect(INNER, y + rowH - 12, (W - INNER * 2) * e, 1);
    ctx.restore();
  });

  if (data.footer) {
    drawText(ctx, data.footer, INNER, H - 70, {
      theme,
      size: 20,
      family: 'sans',
      color: theme.muted,
      alpha: 0.75 * reveal(t, 0.5, 0.8),
      maxWidth: W - INNER * 2,
    });
  }
}

// ------------------------------------------------------------------ 数字

function drawStat(ctx, scene, t, theme) {
  const data = scene.data;
  const items = (data.items || []).slice(0, 3);

  if (data.title) {
    drawText(ctx, data.title, PAD, 168, {
      theme,
      size: 34,
      weight: 500,
      family: 'sans',
      color: theme.soft,
      baseline: 'middle',
      alpha: reveal(t, 0.05, 0.6),
      maxWidth: W - PAD * 2,
    });
  }

  const gap = 56;
  const colW = (W - PAD * 2 - gap * (items.length - 1)) / Math.max(items.length, 1);
  items.forEach((item, i) => {
    const x = PAD + i * (colW + gap);
    const e = reveal(t, 0.14 + i * 0.12, 0.7);
    ctx.save();
    ctx.globalAlpha = e;
    ctx.translate(0, (1 - e) * 30);

    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.fillStyle = theme.accent;
    ctx.fillRect(x, 330, 72, 4);
    ctx.restore();

    const value = String(item.value ?? '');
    const size = fitSize(ctx, value, colW - 10, {
      theme,
      max: 150,
      min: 64,
      maxLines: 1,
      weight: 700,
      family: familyFor(value, 'mono'),
    });
    drawText(ctx, value, x, 430, {
      theme,
      size,
      weight: 700,
      family: familyFor(value, 'mono'),
      color: theme.ink,
      baseline: 'middle',
      maxWidth: colW - 10,
    });
    drawText(ctx, String(item.label ?? ''), x, 530, {
      theme,
      size: 28,
      weight: 500,
      family: 'sans',
      color: theme.ink,
      baseline: 'middle',
      maxWidth: colW - 10,
    });
    if (item.note) {
      drawParagraph(ctx, String(item.note), x, 562, colW - 10, {
        theme,
        size: 22,
        family: 'sans',
        color: theme.muted,
        lineHeight: 34,
        maxLines: 3,
      });
    }
    ctx.restore();
  });

  drawCornerTicks(ctx, theme, 0.25);
}

// ------------------------------------------------------------------ 引用

function drawQuote(ctx, scene, t, theme) {
  const data = scene.data;
  ctx.save();
  ctx.globalAlpha = 0.18 * reveal(t, 0.05, 0.7);
  ctx.fillStyle = theme.accent;
  ctx.font = `700 240px ${theme.fonts.serif}`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText('“', PAD - 10, 150);
  ctx.restore();

  const size = fitSize(ctx, data.text || '', 1480, {
    theme,
    max: 60,
    min: 40,
    maxLines: 4,
    weight: 500,
    family: 'serif',
  });
  drawParagraph(ctx, data.text || '', PAD + 40, 330, 1480, {
    theme,
    size,
    weight: 500,
    family: 'serif',
    color: theme.ink,
    lineHeight: size * 1.52,
    maxLines: 4,
    alpha: reveal(t, 0.15, 0.8),
  });

  if (data.author) {
    const e = reveal(t, 0.45, 0.7);
    ctx.save();
    ctx.globalAlpha = 0.5 * e;
    ctx.fillStyle = theme.line;
    ctx.fillRect(PAD + 40, 860, 90, 1);
    ctx.restore();
    drawText(ctx, `— ${data.author}`, PAD + 150, 858, {
      theme,
      size: 26,
      family: 'sans',
      color: theme.muted,
      baseline: 'middle',
      alpha: e,
      maxWidth: 900,
    });
  }

  drawCornerTicks(ctx, theme, 0.2);
}

// ------------------------------------------------------------------ 结尾

function drawEnd(ctx, scene, t, theme, meta) {
  const data = scene.data;
  const e = reveal(t, 0.05, 0.7);

  ctx.save();
  ctx.globalAlpha = e;
  ctx.fillStyle = theme.accent;
  ctx.fillRect(W / 2 - 34, 262, 68, 4);
  ctx.restore();

  const size = fitSize(ctx, data.title || '完', 1200, {
    theme,
    max: 112,
    min: 56,
    maxLines: 2,
    weight: 600,
    family: 'serif',
  });
  const lines = wrapText(ctx, data.title || '完', 1200, {
    theme,
    size,
    weight: 600,
    family: 'serif',
  });
  const lh = size * 1.18;
  const top = 342;
  lines.forEach((line, i) => {
    const lineE = reveal(t, 0.12 + i * 0.1, 0.7);
    drawText(ctx, line, W / 2, top + i * lh, {
      theme,
      size,
      weight: 600,
      family: 'serif',
      color: theme.ink,
      align: 'center',
      baseline: 'top',
      alpha: lineE,
      maxWidth: 1200,
    });
  });

  let y = top + lines.length * lh + 42;
  if (data.subtitle) {
    drawText(ctx, data.subtitle, W / 2, y, {
      theme,
      size: 30,
      family: 'sans',
      color: theme.soft,
      align: 'center',
      baseline: 'middle',
      alpha: reveal(t, 0.3, 0.7),
      maxWidth: 1100,
    });
    y += 86;
  }

  const stats = meta.stats || {};
  const chips = [
    `${stats.sections ?? 0} 个章节`,
    `${stats.items ?? 0} 条记录`,
    fmtDuration(meta.durationSec || 0),
  ];
  let cx = W / 2 - (chips.length * 190) / 2 + 20;
  chips.forEach((text, i) => {
    const e = reveal(t, 0.4 + i * 0.1, 0.5);
    if (e <= 0.001) return;
    ctx.save();
    ctx.globalAlpha = e;
    const width = drawChip(ctx, text, cx, y, theme, { size: 24, accent: i === 0 });
    ctx.restore();
    cx += width + 16;
  });

  if (data.footer) {
    drawText(ctx, data.footer, W / 2, H - 126, {
      theme,
      size: 22,
      family: 'sans',
      color: theme.muted,
      align: 'center',
      baseline: 'middle',
      alpha: 0.8 * reveal(t, 0.5, 0.8),
      maxWidth: 1200,
    });
  }

  drawSeal(ctx, W / 2, H - 250, 116, '归档', theme);
  drawCornerTicks(ctx, theme, 0.25);
}

// ------------------------------------------------------------------ 人像

function drawPortrait(ctx, scene, t, theme) {
  const data = scene.data;
  const style = PORTRAIT_STYLES[data.variant] || PORTRAIT_STYLES.pride;
  const accent = data.accent || style.accent;
  const index = data.index ?? 0;
  const total = data.total ?? 1;
  const side = data.side || (index % 2 === 0 ? 'right' : 'left');
  const artX = side === 'right' ? 1430 : 500;
  const textX = side === 'right' ? PAD : 1030;
  const textWidth = side === 'right' ? 840 : 760;
  const e = reveal(t, 0.04, 0.9);

  // 背后的速度线
  ctx.save();
  ctx.globalAlpha = 0.22 * e;
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2;
  for (let i = 0; i < 5; i += 1) {
    const offset = i * 46;
    ctx.beginPath();
    ctx.moveTo(artX - 260 + offset, 0);
    ctx.lineTo(artX + 120 + offset, H);
    ctx.stroke();
  }
  ctx.restore();

  drawPortraitArt(ctx, {
    variant: data.variant,
    accent,
    t,
    cx: artX,
    cy: 632,
    scale: 0.82 * (1 + 0.012 * e),
    mirror: side === 'left',
    seed: scene.seed,
    e,
    fadeColor: theme.bg1,
  });

  // 编号 + 拉丁名
  const eyebrowE = reveal(t, 0.12, 0.6);
  ctx.save();
  ctx.globalAlpha = eyebrowE;
  ctx.fillStyle = accent;
  ctx.fillRect(textX, 232, 42, 4);
  ctx.restore();
  drawText(ctx, `${pad2(index + 1)} / ${pad2(total)}`, textX, 268, {
    theme,
    size: 22,
    weight: 600,
    family: 'mono',
    color: accent,
    baseline: 'middle',
    alpha: eyebrowE,
  });
  drawText(ctx, style.latin, textX + 132, 268, {
    theme,
    size: 22,
    weight: 500,
    family: 'mono',
    color: theme.muted,
    baseline: 'middle',
    alpha: eyebrowE,
    maxWidth: 520,
  });

  // 标题与说明
  const titleE = reveal(t, 0.2, 0.75);
  const titleSize = fitSize(ctx, data.title || '', textWidth, {
    theme,
    max: 108,
    min: 64,
    maxLines: 1,
    weight: 700,
    family: 'serif',
  });
  drawText(ctx, data.title || '', textX, 340, {
    theme,
    size: titleSize,
    weight: 700,
    family: 'serif',
    color: theme.ink,
    baseline: 'middle',
    alpha: titleE,
    maxWidth: textWidth,
  });
  if (data.subtitle) {
    drawParagraph(ctx, data.subtitle, textX, 412, textWidth, {
      theme,
      size: 30,
      family: 'sans',
      color: theme.soft,
      lineHeight: 46,
      maxLines: 2,
      alpha: reveal(t, 0.32, 0.7),
    });
  }
  if (data.caption) {
    drawText(ctx, data.caption, textX, 528, {
      theme,
      size: 22,
      family: 'sans',
      color: theme.muted,
      baseline: 'middle',
      alpha: reveal(t, 0.4, 0.7),
      maxWidth: textWidth,
    });
  }

  // 关键词
  const keywords = data.keywords || [];
  keywords.slice(0, 4).forEach((word, i) => {
    const rowE = reveal(t, 0.46 + i * 0.09, 0.55);
    const y = 610 + i * 66;
    drawText(ctx, pad2(i + 1), textX, y, {
      theme,
      size: 18,
      family: 'mono',
      color: accent,
      baseline: 'middle',
      alpha: rowE,
    });
    drawText(ctx, word, textX + 52, y, {
      theme,
      size: 30,
      weight: 500,
      family: 'sans',
      color: theme.ink,
      baseline: 'middle',
      alpha: rowE,
      maxWidth: textWidth - 60,
    });
    ctx.save();
    ctx.globalAlpha = 0.18 * rowE;
    ctx.fillStyle = theme.line;
    ctx.fillRect(textX, y + 30, textWidth * rowE, 1);
    ctx.restore();
  });

  // 底部进度
  const barE = reveal(t, 0.5, 0.7);
  ctx.save();
  ctx.globalAlpha = 0.4 * barE;
  ctx.fillStyle = theme.line;
  ctx.fillRect(textX, H - 118, textWidth, 1);
  ctx.globalAlpha = 0.95 * barE;
  ctx.fillStyle = accent;
  ctx.fillRect(textX, H - 121, 80, 3);
  ctx.restore();

  drawCornerTicks(ctx, theme, 0.22);
}

// ------------------------------------------------------------------ 出口

export function drawSceneContent(ctx, scene, t, theme, meta) {
  switch (scene.kind) {
    case 'cover':
      drawCover(ctx, scene, t, theme, meta);
      break;
    case 'section':
      drawSection(ctx, scene, t, theme);
      break;
    case 'list':
      drawList(ctx, scene, t, theme);
      break;
    case 'stat':
      drawStat(ctx, scene, t, theme);
      break;
    case 'quote':
      drawQuote(ctx, scene, t, theme);
      break;
    case 'end':
      drawEnd(ctx, scene, t, theme, meta);
      break;
    case 'portrait':
      drawPortrait(ctx, scene, t, theme);
      break;
    default:
      break;
  }
}
