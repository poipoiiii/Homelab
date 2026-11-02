// 人像画板：程序化古典侧脸胸像 + 每个罪名的专属符号与色调。
// 纯 canvas 绘制，不依赖外部图片；坐标以胸像中心为原点，整体 770×840。
import { mulberry32, clamp, lerp } from './gfx.js';

export const PORTRAIT_STYLES = {
  pride: { accent: '#d8a13a', latin: 'SUPERBIA', motif: 'crown' },
  envy: { accent: '#6fae6a', latin: 'INVIDIA', motif: 'serpent' },
  wrath: { accent: '#d94a30', latin: 'IRA', motif: 'flame' },
  sloth: { accent: '#7d93b2', latin: 'ACEDIA', motif: 'clock' },
  greed: { accent: '#c9a227', latin: 'AVARITIA', motif: 'coins' },
  gluttony: { accent: '#d98a3a', latin: 'GULA', motif: 'cutlery' },
  lust: { accent: '#c95f7a', latin: 'LUXURIA', motif: 'rose' },
  figure: { accent: '#9aa7b8', latin: 'FIGURE', motif: 'none' },
};

function bustPath(ctx) {
  ctx.beginPath();
  ctx.moveTo(-260, 800);
  ctx.bezierCurveTo(-240, 640, -180, 560, -90, 520);
  ctx.bezierCurveTo(-70, 470, -60, 430, -55, 390);
  ctx.bezierCurveTo(-140, 350, -170, 250, -150, 140);
  ctx.bezierCurveTo(-130, 30, -20, -40, 90, -40);
  ctx.bezierCurveTo(210, -40, 280, 60, 285, 160);
  ctx.bezierCurveTo(288, 190, 276, 210, 280, 226);
  ctx.bezierCurveTo(296, 252, 330, 280, 340, 306);
  ctx.bezierCurveTo(344, 318, 330, 324, 316, 326);
  ctx.bezierCurveTo(322, 338, 328, 348, 320, 358);
  ctx.bezierCurveTo(328, 366, 326, 378, 312, 386);
  ctx.bezierCurveTo(316, 406, 306, 424, 284, 436);
  ctx.bezierCurveTo(270, 444, 258, 450, 250, 458);
  ctx.bezierCurveTo(258, 500, 286, 530, 330, 552);
  ctx.bezierCurveTo(420, 590, 480, 680, 510, 800);
  ctx.closePath();
}

function drawPartialPolyline(ctx, points, progress) {
  if (progress <= 0) return;
  const lengths = [];
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    const d = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    lengths.push(d);
    total += d;
  }
  let remaining = total * clamp(progress);
  ctx.beginPath();
  ctx.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length; i += 1) {
    const seg = lengths[i - 1];
    if (remaining <= 0) break;
    const take = Math.min(remaining, seg);
    const ratio = seg === 0 ? 0 : take / seg;
    ctx.lineTo(
      lerp(points[i - 1][0], points[i][0], ratio),
      lerp(points[i - 1][1], points[i][1], ratio),
    );
    remaining -= take;
  }
  ctx.stroke();
}

const CRACKS = [
  [
    [-60, -10],
    [0, 60],
    [-24, 130],
    [30, 190],
    [14, 250],
  ],
  [
    [170, 40],
    [150, 110],
    [196, 158],
    [176, 220],
  ],
  [
    [-110, 300],
    [-58, 330],
    [-86, 382],
    [-40, 418],
  ],
];

function drawCrown(ctx, accent) {
  ctx.save();
  ctx.translate(0, 36);
  ctx.globalAlpha = 0.9;
  const grad = ctx.createLinearGradient(-160, -180, 200, -40);
  grad.addColorStop(0, accent);
  grad.addColorStop(1, 'rgba(255,230,170,0.85)');
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.moveTo(-170, -58);
  ctx.lineTo(-150, -180);
  ctx.lineTo(-96, -74);
  ctx.lineTo(-30, -212);
  ctx.lineTo(28, -74);
  ctx.lineTo(96, -196);
  ctx.lineTo(142, -70);
  ctx.lineTo(196, -150);
  ctx.lineTo(210, -52);
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = 0.5;
  ctx.fillStyle = '#1a1510';
  ctx.fillRect(-170, -62, 380, 10);
  ctx.restore();
}

function drawSerpent(ctx, accent) {
  ctx.save();
  ctx.lineCap = 'round';
  ctx.strokeStyle = accent;
  ctx.globalAlpha = 0.85;
  ctx.lineWidth = 16;
  ctx.beginPath();
  ctx.moveTo(252, 452);
  ctx.bezierCurveTo(330, 520, 330, 600, 250, 616);
  ctx.bezierCurveTo(180, 630, 140, 590, 120, 540);
  ctx.stroke();
  ctx.globalAlpha = 0.35;
  ctx.strokeStyle = '#0a0d0a';
  ctx.lineWidth = 5;
  ctx.stroke();
  // 蛇头
  ctx.globalAlpha = 0.95;
  ctx.fillStyle = accent;
  ctx.beginPath();
  ctx.moveTo(120, 540);
  ctx.lineTo(66, 520);
  ctx.lineTo(92, 566);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = '#101410';
  ctx.beginPath();
  ctx.arc(96, 540, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawFlame(ctx, accent) {
  ctx.save();
  const grad = ctx.createLinearGradient(0, 620, 0, 160);
  grad.addColorStop(0, 'rgba(217,74,48,0)');
  grad.addColorStop(0.45, accent);
  grad.addColorStop(1, 'rgba(255,190,90,0.9)');
  ctx.fillStyle = grad;
  ctx.globalAlpha = 0.55;
  const flames = [
    [
      [-300, 680],
      [-260, 470],
      [-210, 560],
      [-160, 380],
      [-110, 590],
      [-60, 500],
      [-40, 700],
    ],
    [
      [300, 700],
      [330, 500],
      [380, 590],
      [430, 430],
      [470, 620],
      [520, 540],
      [540, 720],
    ],
  ];
  for (const flame of flames) {
    ctx.beginPath();
    ctx.moveTo(flame[0][0], flame[0][1]);
    for (let i = 1; i < flame.length; i += 1) ctx.lineTo(flame[i][0], flame[i][1]);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();
}

function drawClock(ctx, accent, t) {
  ctx.save();
  ctx.translate(20, 40);
  ctx.globalAlpha = 0.3;
  ctx.strokeStyle = accent;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(0, 0, 330, 0, Math.PI * 2);
  ctx.stroke();
  for (let i = 0; i < 12; i += 1) {
    const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * 300, Math.sin(a) * 300);
    ctx.lineTo(Math.cos(a) * (i % 3 === 0 ? 262 : 282), Math.sin(a) * (i % 3 === 0 ? 262 : 282));
    ctx.stroke();
  }
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 4;
  const minute = t * 0.5 + Math.PI / 3;
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(Math.cos(minute) * 220, Math.sin(minute) * 220);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(Math.cos(minute * 0.12 + 1.2) * 130, Math.sin(minute * 0.12 + 1.2) * 130);
  ctx.stroke();
  ctx.restore();
}

function drawCoins(ctx, accent, seed) {
  const rand = mulberry32(seed * 31 + 7);
  ctx.save();
  ctx.globalAlpha = 0.55;
  ctx.strokeStyle = accent;
  ctx.fillStyle = 'rgba(0,0,0,0.25)';
  ctx.lineWidth = 3;
  for (let i = 0; i < 14; i += 1) {
    const x = -360 + rand() * 760;
    const y = 220 + rand() * 560;
    const r = 18 + rand() * 26;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, r * 0.55, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawCutlery(ctx, accent) {
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = accent;
  ctx.lineCap = 'round';
  ctx.lineWidth = 12;
  // 叉
  ctx.beginPath();
  ctx.moveTo(-350, 720);
  ctx.lineTo(-230, 300);
  ctx.stroke();
  ctx.lineWidth = 7;
  for (let i = 0; i < 4; i += 1) {
    ctx.beginPath();
    ctx.moveTo(-268 + i * 22, 300);
    ctx.lineTo(-282 + i * 22, 190);
    ctx.stroke();
  }
  // 勺
  ctx.lineWidth = 12;
  ctx.beginPath();
  ctx.moveTo(470, 730);
  ctx.lineTo(360, 360);
  ctx.stroke();
  ctx.beginPath();
  ctx.ellipse(348, 300, 44, 66, -0.18, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function drawRose(ctx, accent) {
  ctx.save();
  ctx.translate(330, 540);
  ctx.globalAlpha = 0.75;
  ctx.strokeStyle = accent;
  ctx.lineWidth = 3;
  for (let i = 0; i < 7; i += 1) {
    const r = 26 + i * 18;
    const a0 = -0.4 + i * 0.35;
    ctx.beginPath();
    ctx.arc(0, 0, r, a0, a0 + Math.PI * 1.35);
    ctx.stroke();
  }
  ctx.globalAlpha = 0.4;
  ctx.fillStyle = accent;
  ctx.beginPath();
  ctx.arc(0, 0, 18, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawMotif(ctx, motif, accent, seed, t) {
  switch (motif) {
    case 'crown':
      drawCrown(ctx, accent);
      break;
    case 'serpent':
      drawSerpent(ctx, accent);
      break;
    case 'flame':
      drawFlame(ctx, accent);
      break;
    case 'clock':
      drawClock(ctx, accent, t);
      break;
    case 'coins':
      drawCoins(ctx, accent, seed);
      break;
    case 'cutlery':
      drawCutlery(ctx, accent);
      break;
    case 'rose':
      drawRose(ctx, accent);
      break;
    default:
      break;
  }
}

/**
 * 画一整块人像：光环、点阵、胸像、裂纹、五官、符号。
 * e 是入场进度 0..1，用于整体淡入和裂纹绘制。
 */
export function drawPortraitArt(ctx, {
  variant,
  accent,
  t,
  cx,
  cy,
  scale = 0.82,
  mirror = false,
  seed = 7,
  e = 1,
  fadeColor = '#0a0c0b',
}) {
  const style = PORTRAIT_STYLES[variant] || PORTRAIT_STYLES.pride;
  ctx.save();
  ctx.translate(cx, cy + (1 - e) * 34);
  ctx.scale((mirror ? -1 : 1) * scale, scale);
  ctx.translate(-125, -380);
  ctx.globalAlpha = e;

  // 光环与刻度
  ctx.save();
  ctx.strokeStyle = accent;
  ctx.globalAlpha = 0.18 * e;
  ctx.lineWidth = 1.5;
  for (const r of [318, 360]) {
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha = 0.5 * e;
  for (let i = 0; i < 72; i += 1) {
    const a = (i / 72) * Math.PI * 2 + t * 0.06;
    const r1 = 360;
    const r2 = i % 6 === 0 ? 338 : 350;
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1);
    ctx.lineTo(Math.cos(a) * r2, Math.sin(a) * r2);
    ctx.stroke();
  }
  ctx.restore();

  // 点阵背景
  ctx.save();
  ctx.globalAlpha = 0.10 * e;
  ctx.fillStyle = accent;
  for (let gx = -360; gx <= 360; gx += 48) {
    for (let gy = -360; gy <= 360; gy += 48) {
      if (gx * gx + gy * gy > 330 * 330) continue;
      ctx.beginPath();
      ctx.arc(gx, gy, 1.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();

  // 部分符号画在胸像背后，避免穿过面部
  const behindMotif = ['clock', 'coins', 'cutlery', 'flame'].includes(style.motif);
  if (behindMotif) drawMotif(ctx, style.motif, accent, seed, t);

  // 胸像主体
  ctx.save();
  bustPath(ctx);
  ctx.clip();

  const base = ctx.createLinearGradient(-260, -40, 510, 800);
  base.addColorStop(0, '#0b0c0d');
  base.addColorStop(0.42, '#2e2923');
  base.addColorStop(0.74, '#6b5c4b');
  base.addColorStop(1, '#a88f72');
  ctx.fillStyle = base;
  ctx.fillRect(-400, -120, 960, 960);

  const tint = ctx.createLinearGradient(-100, 0, 510, 0);
  tint.addColorStop(0, 'rgba(0,0,0,0)');
  tint.addColorStop(0.58, 'rgba(0,0,0,0)');
  tint.addColorStop(1, accent);
  ctx.globalAlpha = 0.5 * e;
  ctx.fillStyle = tint;
  ctx.fillRect(-400, -120, 960, 960);
  ctx.globalAlpha = e;

  const key = ctx.createRadialGradient(250, 110, 30, 250, 110, 420);
  key.addColorStop(0, accent);
  key.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.globalAlpha = 0.18 * e;
  ctx.fillStyle = key;
  ctx.fillRect(-400, -120, 960, 960);
  ctx.globalAlpha = e;

  const shadow = ctx.createRadialGradient(-140, -80, 40, -140, -80, 520);
  shadow.addColorStop(0, 'rgba(0,0,0,0.72)');
  shadow.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = shadow;
  ctx.fillRect(-400, -120, 960, 960);

  // 扫描线
  ctx.globalAlpha = 0.12 * e;
  ctx.fillStyle = '#000';
  for (let y = -60; y < 820; y += 6) ctx.fillRect(-300, y, 900, 1.4);

  // 底部融进背景，避免硬切
  ctx.globalAlpha = 1;
  const fade = ctx.createLinearGradient(0, 610, 0, 815);
  fade.addColorStop(0, 'rgba(10,12,11,0)');
  fade.addColorStop(1, fadeColor);
  ctx.fillStyle = fade;
  ctx.fillRect(-340, 610, 920, 220);
  ctx.restore();

  // 边缘光
  ctx.save();
  ctx.globalAlpha = 0.65 * e;
  const rim = ctx.createLinearGradient(-200, 0, 500, 200);
  rim.addColorStop(0, 'rgba(255,255,255,0.05)');
  rim.addColorStop(0.6, accent);
  rim.addColorStop(1, 'rgba(255,255,255,0.15)');
  ctx.strokeStyle = rim;
  ctx.lineWidth = 3;
  bustPath(ctx);
  ctx.stroke();
  ctx.restore();

  // 裂纹
  ctx.save();
  ctx.strokeStyle = accent;
  ctx.lineWidth = 1.8;
  ctx.globalAlpha = 0.55 * e;
  CRACKS.forEach((crack, i) => drawPartialPolyline(ctx, crack, clamp((e - i * 0.15) / 0.6)));
  ctx.restore();

  // 五官
  ctx.save();
  ctx.globalAlpha = 0.85 * e;
  // 眉
  ctx.strokeStyle = 'rgba(8,8,9,0.9)';
  ctx.lineWidth = 12;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(206, 208);
  ctx.quadraticCurveTo(248, 194, 288, 220);
  ctx.stroke();
  // 眼窝
  ctx.fillStyle = 'rgba(10,10,11,0.9)';
  ctx.beginPath();
  ctx.ellipse(246, 242, 26, 12, -0.16, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = accent;
  ctx.globalAlpha = 0.9 * e;
  ctx.beginPath();
  ctx.arc(254, 240, 4.2, 0, Math.PI * 2);
  ctx.fill();
  // 鼻梁阴影
  ctx.globalAlpha = 0.5 * e;
  ctx.strokeStyle = 'rgba(10,10,11,0.8)';
  ctx.lineWidth = 8;
  ctx.beginPath();
  ctx.moveTo(292, 232);
  ctx.quadraticCurveTo(312, 270, 318, 304);
  ctx.stroke();
  // 嘴唇
  ctx.globalAlpha = 0.8 * e;
  ctx.strokeStyle = 'rgba(8,8,9,0.9)';
  ctx.lineWidth = 5;
  ctx.beginPath();
  ctx.moveTo(300, 346);
  ctx.quadraticCurveTo(316, 350, 326, 354);
  ctx.stroke();
  ctx.restore();

  if (!behindMotif) drawMotif(ctx, style.motif, accent, seed, t);

  ctx.restore();
}
