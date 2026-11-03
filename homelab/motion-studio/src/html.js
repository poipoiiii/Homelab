// 把 motion-studio 的场景数据生成一份 HyperFrames HTML 合成。
// 客户端协议不变，仍在用 cover/section/list/stat/quote/portrait/end 这套字段。
import { W, themeOf } from './theme.js';

const ESCAPES = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ESCAPES[char]);
const num = (value) => Number(value || 0).toFixed(3);
const pad2 = (value) => String(value).padStart(2, '0');

const PORTRAIT_STYLES = {
  pride: { char: '傲', color: '#d8b25a' },
  envy: { char: '妒', color: '#7fae7a' },
  wrath: { char: '怒', color: '#d94a30' },
  sloth: { char: '惰', color: '#8a9499' },
  greed: { char: '贪', color: '#c08a3e' },
  gluttony: { char: '食', color: '#a86b45' },
  lust: { char: '欲', color: '#c25b7a' },
  figure: { char: '人', color: '' },
};

function splitTitle(text, maxChars) {
  const source = String(text || '').trim();
  const chars = [...source];
  if (chars.length <= maxChars) return [source];

  // 英文单词/数字不拆开；优先在空格或标点处换行，找不到再按字符数切。
  const tokens =
    source.match(/[A-Za-z0-9]+(?:['’\-_.][A-Za-z0-9]+)*|\s+|[\s\S]/gu) || [];
  const target = Math.ceil(chars.length / 2);
  let acc = 0;
  let best = null;
  let fallback = null;
  for (let index = 0; index < tokens.length - 1; index += 1) {
    acc += [...tokens[index]].length;
    const boundary = index + 1;
    const next = tokens[boundary] || '';
    const afterPunctuation = /[，。；：、,.!?]/.test(tokens[index]);
    const beforeSpace = /^\s+$/.test(next);
    if (beforeSpace || afterPunctuation) {
      if (best === null || Math.abs(acc - target) < Math.abs(best.acc - target)) {
        best = { boundary, acc };
      }
    }
    if (fallback === null || Math.abs(acc - target) < Math.abs(fallback.acc - target)) {
      fallback = { boundary, acc };
    }
  }

  const cut = best?.boundary ?? fallback?.boundary ?? Math.ceil(tokens.length / 2);
  const first = tokens.slice(0, cut).join('').trim();
  const second = tokens.slice(cut).join('').trim();
  if (first && second) return [first, second];
  return [chars.slice(0, target).join(''), chars.slice(target).join('')];
}

function titleSize(lines, base = 154) {
  const longest = Math.max(...lines.map((line) => [...line].length), 1);
  if (longest <= 8) return base;
  if (longest <= 11) return Math.round(base * 0.86);
  if (longest <= 14) return Math.round(base * 0.7);
  if (longest <= 18) return Math.round(base * 0.55);
  return Math.round(base * 0.46);
}

function linesHtml(lines) {
  return lines
    .map(
      (line) =>
        `<span class="line"><span class="line-inner">${esc(line)}</span></span>`,
    )
    .join('');
}

function coverScene(scene, index) {
  const data = scene.data || {};
  const lines = splitTitle(data.title || '', 9);
  const size = titleSize(lines, 154);
  const metaLeft = data.date || '';
  const metaRight = data.footer || '';
  return `
    <section class="clip scene cover" id="s${index}" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="0">
      <div class="halo"></div>
      <div class="rule"></div>
      <div class="cover-inner">
        <div class="kicker">${esc(data.kicker || '')}</div>
        <h1 class="title" style="font-size:${size}px">${linesHtml(lines)}</h1>
        <p class="sub">${esc(data.subtitle || '')}</p>
      </div>
      <div class="meta"><span>${esc(metaLeft)}</span><span>${esc(metaRight)}</span></div>
    </section>`;
}

function sectionScene(scene, index) {
  const data = scene.data || {};
  const heading = data.heading || '';
  const size = [...heading].length <= 12 ? 96 : [...heading].length <= 20 ? 76 : 60;
  const flip = (scene.seed || 0) % 2 === 1;
  const ghost = pad2((data.index || 0) + 1);
  return `
    <section class="clip scene section${flip ? ' flip' : ''}" id="s${index}" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="0">
      <div class="section-ghost">${ghost}</div>
      <div class="section-inner">
        <div class="section-index">${pad2((data.index || 0) + 1)} / ${pad2(data.total || 1)}</div>
        <h2 class="section-title" style="font-size:${size}px">${esc(heading)}</h2>
        ${data.caption ? `<p class="section-caption">${esc(data.caption)}</p>` : ''}
        ${data.count ? `<div class="section-count">${Number(data.count)} 条</div>` : ''}
      </div>
    </section>`;
}

function listScene(scene, index) {
  const data = scene.data || {};
  const items = Array.isArray(data.items) ? data.items : [];
  const flip = (scene.seed || 0) % 2 === 1;
  const headingSize = [...(data.heading || '')].length <= 12 ? 68 : 58;
  const dense =
    items.length > 4 ||
    items.some(
      (item) => [...(item.label || '')].length > 14 || [...(item.note || '')].length > 30,
    );
  const pageLabel =
    data.page && data.pages ? `PAGE ${data.page} / ${data.pages}` : 'LIST';
  return `
    <section class="clip scene list${flip ? ' flip' : ''}${dense ? ' dense' : ''}" id="s${index}" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="0">
      <div class="list-head">
        <div class="kicker">${pageLabel}</div>
        ${data.heading ? `<h2 style="font-size:${headingSize}px">${esc(data.heading)}</h2>` : ''}
        ${data.footer ? `<p>${esc(data.footer)}</p>` : ''}
      </div>
      <div class="rows">
        ${items
          .map(
            (item, itemIndex) => `
          <div class="row">
            <span class="idx">${pad2(itemIndex + 1)}</span>
            <span class="label">${esc(item.label || '')}</span>
            <span class="value">${esc(item.value || '')}</span>
            <span class="note">${esc(item.note || '')}</span>
          </div>`,
          )
          .join('')}
      </div>
    </section>`;
}

function statScene(scene, index) {
  const data = scene.data || {};
  const items = Array.isArray(data.items) ? data.items : [];
  return `
    <section class="clip scene stat" id="s${index}" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="0">
      <div class="stat-head kicker">${esc(data.title || 'DATA')}</div>
      <div class="stats">
        ${items
          .map((item) => {
            const value = item.value || '';
            const size = [...value].length <= 6 ? 120 : [...value].length <= 10 ? 96 : 76;
            return `
          <div class="stat-item">
            <div class="stat-value" style="font-size:${size}px">${esc(value)}</div>
            <div class="stat-label">${esc(item.label || '')}</div>
            ${item.note ? `<div class="stat-note">${esc(item.note)}</div>` : ''}
          </div>`;
          })
          .join('')}
      </div>
    </section>`;
}

function quoteScene(scene, index) {
  const data = scene.data || {};
  const text = String(data.text || '');
  const length = [...text].length;
  const size = length <= 24 ? 96 : length <= 48 ? 80 : length <= 96 ? 64 : length <= 160 ? 52 : 44;
  return `
    <section class="clip scene quote" id="s${index}" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="0">
      <div class="quote-mark">“</div>
      <blockquote class="quote-text" style="font-size:${size}px">${esc(text).replace(/\n/g, '<br>')}</blockquote>
      ${data.author ? `<div class="quote-author">—— ${esc(data.author)}</div>` : ''}
    </section>`;
}

function portraitScene(scene, index) {
  const data = scene.data || {};
  const style = PORTRAIT_STYLES[data.variant] || PORTRAIT_STYLES.figure;
  const accent = data.accent || style.color || '';
  const flip = data.side === 'right' || (!data.side && (scene.seed || 0) % 2 === 1);
  const keywords = Array.isArray(data.keywords) ? data.keywords : [];
  const titleSizeValue = [...(data.title || '')].length <= 8 ? 88 : 70;
  return `
    <section class="clip scene portrait${flip ? ' flip' : ''}" id="s${index}" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="0" style="--p-accent:${esc(accent || 'var(--accent)')}">
      <div class="portrait-art">
        <div class="portrait-ring"></div>
        <div class="portrait-glyph">${esc(style.char)}</div>
      </div>
      <div class="portrait-copy">
        <div class="kicker">${pad2((data.index || 0) + 1)} / ${pad2(data.total || 1)}</div>
        <h2 style="font-size:${titleSizeValue}px">${esc(data.title || '')}</h2>
        ${data.subtitle ? `<p class="sub">${esc(data.subtitle)}</p>` : ''}
        ${data.caption ? `<p class="caption">${esc(data.caption)}</p>` : ''}
        ${
          keywords.length
            ? `<div class="keywords">${keywords
                .map(
                  (word, wordIndex) =>
                    `<span class="keyword"><b>${pad2(wordIndex + 1)}</b>${esc(word)}</span>`,
                )
                .join('')}</div>`
            : ''
        }
      </div>
    </section>`;
}

function endScene(scene, index) {
  const data = scene.data || {};
  const lines = splitTitle(data.title || '完', 9);
  const size = titleSize(lines, 112);
  return `
    <section class="clip scene end" id="s${index}" data-start="${num(scene.start)}" data-duration="${num(scene.duration)}" data-track-index="0">
      <div class="end-inner">
        <div class="kicker">END</div>
        <h2 class="end-title" style="font-size:${size}px">${linesHtml(lines)}</h2>
        ${data.subtitle ? `<p class="end-sub">${esc(data.subtitle)}</p>` : ''}
        ${data.footer ? `<div class="end-footer">${esc(data.footer)}</div>` : ''}
      </div>
    </section>`;
}

function sceneHtml(scene, index) {
  switch (scene.kind) {
    case 'cover':
      return coverScene(scene, index);
    case 'section':
      return sectionScene(scene, index);
    case 'list':
      return listScene(scene, index);
    case 'stat':
      return statScene(scene, index);
    case 'quote':
      return quoteScene(scene, index);
    case 'portrait':
      return portraitScene(scene, index);
    case 'end':
      return endScene(scene, index);
    default:
      return '';
  }
}

function sceneAnimation(scene, index) {
  const id = `#s${index}`;
  const start = scene.start;
  const at = (offset) => Number((start + offset).toFixed(3));
  const lines = [];

  if (start > 0.001) {
    lines.push(`tl.set("#flash", { opacity: 0.92 }, ${num(start)});`);
    lines.push(
      `tl.to("#flash", { opacity: 0, duration: 0.4, ease: "power2.out" }, ${num(start)});`,
    );
  }

  switch (scene.kind) {
    case 'cover':
      lines.push(
        `tl.fromTo("${id} .halo", { scale: 0.94, opacity: 0 }, { scale: 1, opacity: 1, duration: 2.2, ease: "power2.out" }, ${num(start)});`,
        `tl.fromTo("${id} .kicker", { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.65, ease: "power2.out" }, ${num(at(0.12))});`,
        `tl.fromTo("${id} .rule", { scaleY: 0 }, { scaleY: 1, duration: 0.9, ease: "power3.out" }, ${num(at(0.2))});`,
        `tl.fromTo("${id} .line-inner", { yPercent: 112 }, { yPercent: 0, duration: 1, ease: "power4.out", stagger: 0.12 }, ${num(at(0.3))});`,
        `tl.fromTo("${id} .sub", { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.75, ease: "power2.out" }, ${num(at(1.1))});`,
        `tl.fromTo("${id} .meta", { opacity: 0 }, { opacity: 1, duration: 0.6 }, ${num(at(1.45))});`,
      );
      break;
    case 'section':
      lines.push(
        `tl.fromTo("${id} .section-index", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.55, ease: "power2.out" }, ${num(at(0.1))});`,
        `tl.fromTo("${id} .section-title", { opacity: 0, y: 28 }, { opacity: 1, y: 0, duration: 0.75, ease: "power3.out" }, ${num(at(0.2))});`,
        `tl.fromTo("${id} .section-ghost", { scale: 0.94, opacity: 0 }, { scale: 1, opacity: 0.035, duration: 1.4, ease: "power2.out" }, ${num(start)});`,
      );
      if (scene.data?.caption) {
        lines.push(
          `tl.fromTo("${id} .section-caption", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.65, ease: "power2.out" }, ${num(at(0.45))});`,
        );
      }
      if (scene.data?.count) {
        lines.push(
          `tl.fromTo("${id} .section-count", { opacity: 0 }, { opacity: 1, duration: 0.5 }, ${num(at(0.65))});`,
        );
      }
      break;
    case 'list':
      lines.push(
        `tl.fromTo("${id} .list-head", { opacity: 0, y: 22 }, { opacity: 1, y: 0, duration: 0.7, ease: "power2.out" }, ${num(at(0.1))});`,
        `tl.fromTo("${id} .row", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.65, ease: "power2.out", stagger: 0.12 }, ${num(at(0.3))});`,
      );
      break;
    case 'stat':
      lines.push(
        `tl.fromTo("${id} .stat-head", { opacity: 0, y: 16 }, { opacity: 1, y: 0, duration: 0.6, ease: "power2.out" }, ${num(at(0.1))});`,
        `tl.fromTo("${id} .stat-item", { opacity: 0, y: 34 }, { opacity: 1, y: 0, duration: 0.75, ease: "power3.out", stagger: 0.14 }, ${num(at(0.3))});`,
        `tl.fromTo("${id} .stat-value", { scale: 0.94 }, { scale: 1, duration: 0.8, ease: "power3.out", stagger: 0.14 }, ${num(at(0.3))});`,
      );
      break;
    case 'quote':
      lines.push(
        `tl.fromTo("${id} .quote-mark", { opacity: 0, y: 26, scale: 0.94 }, { opacity: 0.14, y: 0, scale: 1, duration: 1, ease: "power2.out" }, ${num(at(0.08))});`,
        `tl.fromTo("${id} .quote-text", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.85, ease: "power3.out" }, ${num(at(0.2))});`,
      );
      if (scene.data?.author) {
        lines.push(
          `tl.fromTo("${id} .quote-author", { opacity: 0 }, { opacity: 1, duration: 0.6 }, ${num(at(0.8))});`,
        );
      }
      break;
    case 'portrait':
      lines.push(
        `tl.fromTo("${id} .portrait-ring", { scale: 0.9, opacity: 0 }, { scale: 1, opacity: 1, duration: 1.1, ease: "power3.out" }, ${num(start)});`,
        `tl.fromTo("${id} .portrait-glyph", { scale: 0.94, opacity: 0 }, { scale: 1, opacity: 0.92, duration: 1, ease: "power3.out" }, ${num(at(0.1))});`,
        `tl.fromTo("${id} .portrait-copy > *", { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.65, ease: "power2.out", stagger: 0.12 }, ${num(at(0.3))});`,
      );
      if (scene.data?.keywords?.length) {
        lines.push(
          `tl.fromTo("${id} .keyword", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out", stagger: 0.1 }, ${num(at(0.7))});`,
        );
      }
      break;
    case 'end':
      lines.push(
        `tl.fromTo("${id} .kicker", { opacity: 0 }, { opacity: 1, duration: 0.55 }, ${num(at(0.1))});`,
        `tl.fromTo("${id} .line-inner", { yPercent: 112 }, { yPercent: 0, duration: 1, ease: "power4.out", stagger: 0.13 }, ${num(at(0.22))});`,
      );
      if (scene.data?.subtitle) {
        lines.push(
          `tl.fromTo("${id} .end-sub", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.75 }, ${num(at(1.05))});`,
        );
      }
      if (scene.data?.footer) {
        lines.push(
          `tl.fromTo("${id} .end-footer", { opacity: 0 }, { opacity: 1, duration: 0.6 }, ${num(at(1.3))});`,
        );
      }
      break;
    default:
      break;
  }

  return lines.join('\n  ');
}

export function buildCompositionHtml(plan) {
  const theme = themeOf(plan.theme);
  const scale = plan.width / W;
  let cursor = 0;
  const scenes = plan.scenes.map((scene, index) => {
    const entry = { ...scene, start: cursor, index };
    cursor += scene.duration;
    return entry;
  });
  const total = plan.totalDuration;
  const body = scenes.map((scene, index) => sceneHtml(scene, index)).join('\n');
  const anim = scenes.map((scene, index) => sceneAnimation(scene, index)).join('\n  ');

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>${esc(plan.spec?.title || 'motion-studio')}</title>
<script src="./vendor/gsap.min.js"></script>
<style>
  /* 声明本地字体，告诉 HyperFrames 不需要去 Google Fonts 拉取，避免离线/超时 */
  @font-face { font-family: "Noto Sans CJK SC"; src: local("Noto Sans CJK SC"); font-weight: 100 900; font-style: normal; }
  @font-face { font-family: "Noto Serif CJK SC"; src: local("Noto Serif CJK SC"); font-weight: 100 900; font-style: normal; }
  @font-face { font-family: "Noto Sans Mono CJK SC"; src: local("Noto Sans Mono CJK SC"); font-weight: 100 900; font-style: normal; }

  :root {
    --bg: ${theme.bg1};
    --bg2: ${theme.bg2};
    --ink: ${theme.ink};
    --soft: ${theme.soft};
    --muted: ${theme.muted};
    --line: ${theme.line};
    --line-soft: ${theme.lineSoft};
    --accent: ${theme.accent};
    --accent2: ${theme.accent2};
    --sans: "Noto Sans CJK SC", sans-serif;
    --serif: "Noto Serif CJK SC", serif;
    --mono: "Noto Sans Mono CJK SC", monospace;
  }

  * { box-sizing: border-box; }

  html, body {
    width: ${plan.width}px;
    height: ${plan.height}px;
    margin: 0;
    padding: 0;
    overflow: hidden;
    background: var(--bg);
  }

  body {
    font-family: var(--sans);
    color: var(--ink);
    -webkit-font-smoothing: antialiased;
  }

  #root {
    position: relative;
    width: ${plan.width}px;
    height: ${plan.height}px;
    overflow: hidden;
    background: var(--bg);
  }

  .stage {
    position: absolute;
    left: 0;
    top: 0;
    width: 1920px;
    height: 1080px;
    transform-origin: 0 0;
    transform: scale(${scale});
  }

  .scene {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background:
      radial-gradient(1200px 820px at 70% 18%, var(--bg2) 0%, var(--bg) 64%),
      var(--bg);
  }

  .kicker {
    font-family: var(--mono);
    font-size: 17px;
    letter-spacing: .28em;
    color: var(--muted);
    text-transform: uppercase;
  }

  .line { display: block; overflow: hidden; padding-bottom: .06em; }
  .line-inner { display: inline-block; will-change: transform; }

  /* cover */
  .cover-inner {
    position: absolute;
    left: 196px;
    right: 180px;
    top: 160px;
    bottom: 150px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }

  .cover .kicker { margin-bottom: 34px; }
  .cover .title {
    margin: 0;
    font-family: var(--serif);
    font-weight: 600;
    line-height: 1.08;
    letter-spacing: .01em;
    font-feature-settings: "palt";
  }
  .cover .sub {
    margin: 44px 0 0;
    font-size: 31px;
    letter-spacing: .1em;
    color: var(--soft);
  }
  .cover .rule {
    position: absolute;
    left: 140px;
    top: 170px;
    bottom: 150px;
    width: 2px;
    background: var(--accent);
    transform-origin: 50% 0;
  }
  .cover .meta {
    position: absolute;
    left: 200px;
    right: 180px;
    bottom: 88px;
    display: flex;
    justify-content: space-between;
    font-family: var(--mono);
    font-size: 15px;
    letter-spacing: .2em;
    color: var(--muted);
  }
  .cover .halo {
    position: absolute;
    width: 960px;
    height: 960px;
    right: -200px;
    top: 40px;
    border: 1px solid var(--line);
    border-radius: 50%;
    opacity: 0;
  }
  .cover .halo::after {
    content: "";
    position: absolute;
    inset: 150px;
    border: 1px solid var(--line-soft);
    border-radius: 50%;
  }

  /* section */
  .section-inner {
    position: absolute;
    left: 140px;
    right: 140px;
    top: 50%;
    transform: translateY(-50%);
  }
  .section-index {
    font-family: var(--mono);
    font-size: 15px;
    letter-spacing: .22em;
    color: var(--accent);
    margin-bottom: 28px;
  }
  .section-title {
    margin: 0;
    font-family: var(--serif);
    font-weight: 600;
    line-height: 1.18;
    letter-spacing: .02em;
    font-feature-settings: "palt";
  }
  .section-caption {
    margin: 30px 0 0;
    font-size: 28px;
    line-height: 1.7;
    color: var(--muted);
    max-width: 1100px;
  }
  .section-count {
    margin-top: 26px;
    font-family: var(--mono);
    font-size: 15px;
    letter-spacing: .18em;
    color: var(--muted);
  }
  .section-ghost {
    position: absolute;
    right: -30px;
    bottom: -90px;
    font-family: var(--serif);
    font-size: 420px;
    font-weight: 700;
    line-height: 1;
    color: var(--ink);
    opacity: 0;
  }
  .section.flip .section-inner { text-align: right; }
  .section.flip .section-caption { margin-left: auto; }
  .section.flip .section-ghost { right: auto; left: -30px; }

  /* list */
  .list-head {
    position: absolute;
    left: 140px;
    top: 190px;
    width: 600px;
  }
  .list-head .kicker { margin-bottom: 26px; }
  .list-head h2 {
    margin: 0 0 24px;
    font-family: var(--serif);
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: .02em;
    font-feature-settings: "palt";
  }
  .list-head p {
    margin: 0;
    font-size: 23px;
    line-height: 1.7;
    color: var(--muted);
  }
  .rows {
    position: absolute;
    left: 800px;
    right: 140px;
    top: 190px;
  }
  .row {
    display: grid;
    grid-template-columns: 64px 320px 150px 1fr;
    gap: 0 18px;
    align-items: baseline;
    padding: 26px 0 28px;
    border-top: 1px solid var(--line);
  }
  .row .idx {
    font-family: var(--mono);
    font-size: 15px;
    letter-spacing: .16em;
    color: var(--accent);
  }
  .row .label {
    font-family: var(--serif);
    font-size: 38px;
    font-weight: 600;
    line-height: 1.3;
    letter-spacing: .02em;
  }
  .row .value {
    font-family: var(--serif);
    font-size: 30px;
    font-weight: 600;
    color: var(--accent);
    line-height: 1.3;
  }
  .row .note {
    font-size: 21px;
    line-height: 1.6;
    color: var(--muted);
  }
  .list.flip .list-head {
    left: auto;
    right: 140px;
    text-align: right;
  }
  .list.flip .rows {
    left: 140px;
    right: 800px;
  }
  .list.dense .row { padding: 18px 0 20px; }
  .list.dense .row .label { font-size: 30px; }
  .list.dense .row .value { font-size: 26px; }
  .list.dense .row .note { font-size: 19px; }

  /* stat */
  .stat-head { position: absolute; left: 140px; top: 150px; }
  .stats {
    position: absolute;
    left: 140px;
    right: 140px;
    top: 50%;
    transform: translateY(-45%);
    display: flex;
    justify-content: space-around;
    align-items: flex-start;
    gap: 60px;
  }
  .stat-item { flex: 1; max-width: 560px; text-align: center; }
  .stat-value {
    font-family: var(--serif);
    font-weight: 600;
    line-height: 1;
    letter-spacing: -.02em;
    color: var(--accent);
  }
  .stat-label {
    margin-top: 28px;
    font-family: var(--serif);
    font-size: 32px;
    font-weight: 600;
  }
  .stat-note {
    margin-top: 16px;
    font-size: 21px;
    line-height: 1.6;
    color: var(--muted);
  }

  /* quote */
  .quote-mark {
    position: absolute;
    left: 110px;
    top: 50px;
    font-family: var(--serif);
    font-size: 420px;
    line-height: .8;
    color: var(--accent);
    opacity: 0;
  }
  .quote-text {
    position: absolute;
    left: 220px;
    right: 220px;
    top: 300px;
    margin: 0;
    font-family: var(--serif);
    font-weight: 500;
    line-height: 1.45;
    letter-spacing: .02em;
    font-feature-settings: "palt";
  }
  .quote-author {
    position: absolute;
    right: 200px;
    bottom: 160px;
    font-family: var(--mono);
    font-size: 16px;
    letter-spacing: .18em;
    color: var(--muted);
  }

  /* portrait */
  .portrait-art {
    position: absolute;
    left: 90px;
    top: 80px;
    width: 700px;
    height: 920px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .portrait-ring {
    position: absolute;
    width: 640px;
    height: 640px;
    border: 1px solid var(--line);
    border-radius: 50%;
  }
  .portrait-ring::after {
    content: "";
    position: absolute;
    inset: 90px;
    border: 1px solid var(--line-soft);
    border-radius: 50%;
  }
  .portrait-glyph {
    font-family: var(--serif);
    font-size: 560px;
    font-weight: 600;
    line-height: 1;
    color: var(--p-accent);
    opacity: 0;
  }
  .portrait-copy {
    position: absolute;
    left: 900px;
    right: 140px;
    top: 210px;
  }
  .portrait-copy .kicker { margin-bottom: 26px; }
  .portrait-copy h2 {
    margin: 0 0 24px;
    font-family: var(--serif);
    font-weight: 600;
    line-height: 1.15;
    letter-spacing: .02em;
    font-feature-settings: "palt";
  }
  .portrait-copy .sub {
    margin: 0 0 20px;
    font-size: 28px;
    line-height: 1.6;
    color: var(--soft);
  }
  .portrait-copy .caption {
    margin: 0 0 40px;
    font-size: 21px;
    line-height: 1.6;
    color: var(--muted);
  }
  .keywords { display: flex; flex-wrap: wrap; gap: 16px 34px; }
  .keyword {
    font-family: var(--mono);
    font-size: 15px;
    letter-spacing: .1em;
    color: var(--muted);
  }
  .keyword b {
    margin-right: 8px;
    color: var(--p-accent);
    font-weight: 400;
  }
  .portrait.flip .portrait-art { left: auto; right: 90px; }
  .portrait.flip .portrait-copy { left: 140px; right: 900px; }

  /* end */
  .end-inner {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding-bottom: 40px;
    text-align: center;
  }
  .end-inner .kicker { margin-bottom: 46px; }
  .end-title {
    margin: 0;
    font-family: var(--serif);
    font-weight: 600;
    line-height: 1.24;
    letter-spacing: .02em;
    font-feature-settings: "palt";
  }
  .end-sub {
    margin: 38px 0 0;
    font-size: 30px;
    letter-spacing: .2em;
    color: var(--soft);
  }
  .end-footer {
    margin-top: 46px;
    font-family: var(--mono);
    font-size: 15px;
    letter-spacing: .2em;
    color: var(--muted);
  }

  /* overlays */
  .vignette {
    position: absolute;
    inset: 0;
    z-index: 40;
    pointer-events: none;
    background: radial-gradient(ellipse at 50% 48%, rgba(0,0,0,0) 42%, rgba(0,0,0,${theme.vignette}) 100%);
  }
  .grain {
    position: absolute;
    inset: 0;
    z-index: 50;
    pointer-events: none;
    opacity: ${theme.grain};
    mix-blend-mode: overlay;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.86' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.6'/%3E%3C/svg%3E");
    background-size: 220px 220px;
  }
  #progress {
    position: absolute;
    left: 0;
    bottom: 0;
    width: 1920px;
    height: 3px;
    z-index: 60;
    background: var(--accent);
    transform-origin: 0 50%;
    transform: scaleX(0);
  }
  #flash {
    position: absolute;
    inset: 0;
    z-index: 80;
    background: var(--bg);
    opacity: 0;
    pointer-events: none;
  }
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="${num(total)}" data-width="${plan.width}" data-height="${plan.height}">
  <div class="stage">
${body}
    <div class="vignette"></div>
    <div class="grain"></div>
    <div id="progress"></div>
    <div id="flash"></div>
  </div>
</div>
<script>
  const tl = gsap.timeline({ paused: true });
  tl.fromTo("#progress", { scaleX: 0 }, { scaleX: 1, duration: ${num(total)}, ease: "none" }, 0);
  ${anim}
  window.__timelines = window.__timelines || {};
  window.__timelines.main = tl;
</script>
</body>
</html>`;
}
