// 逐帧渲染 + ffmpeg 管道编码。1080p30 在本机约 30~50ms/帧，48 秒片约 1~2 分钟。
import { createCanvas } from '@napi-rs/canvas';
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import {
  W,
  H,
  easeOutCubic,
  themeOf,
  monitor,
  drawBackground,
  drawGrain,
  drawVignette,
  drawTransition,
} from './gfx.js';
import { drawSceneContent } from './scenes.js';
import { renderAudio } from './audio.js';

export class RenderCanceled extends Error {
  constructor() {
    super('渲染已取消');
    this.code = 'canceled';
  }
}

function locate(scenes, t) {
  let acc = 0;
  for (let i = 0; i < scenes.length; i += 1) {
    const scene = scenes[i];
    if (t < acc + scene.duration || i === scenes.length - 1) {
      const local = Math.max(0, t - acc);
      const tr = scene.transition;
      if (i > 0 && tr && tr.kind !== 'cut' && local < tr.duration) {
        const prev = scenes[i - 1];
        return {
          index: i,
          local,
          transition: {
            kind: tr.kind,
            progress: easeOutCubic(local / Math.max(tr.duration, 0.001)),
            prevIndex: i - 1,
            prevLocal: Math.max(0, prev.duration - tr.duration + local),
          },
        };
      }
      return { index: i, local, transition: null };
    }
    acc += scene.duration;
  }
  const last = scenes.length - 1;
  return { index: last, local: scenes[last].duration, transition: null };
}

function hexLum(hex) {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function inkRatio(buffer, bgLum) {
  let ink = 0;
  let total = 0;
  for (let i = 0; i + 2 < buffer.length; i += 36) {
    const lum = 0.2126 * buffer[i] + 0.7152 * buffer[i + 1] + 0.0722 * buffer[i + 2];
    if (Math.abs(lum - bgLum) > 18) ink += 1;
    total += 1;
  }
  return total > 0 ? ink / total : 0;
}

function waitDrain(stream) {
  return new Promise((resolve) => {
    const done = () => {
      stream.off('drain', done);
      stream.off('close', done);
      resolve();
    };
    stream.on('drain', done);
    stream.on('close', done);
  });
}

/**
 * 渲染整条片子。
 * @param {object} plan buildPlan 的结果
 * @param {object} options { outPath, posterPath, onProgress, isCanceled }
 */
export async function renderVideo(plan, { outPath, posterPath, onProgress, isCanceled }) {
  const { width, height, fps, scenes, totalDuration } = plan;
  const theme = themeOf(plan.theme);
  const scale = width / W;
  const totalFrames = Math.max(1, Math.round(totalDuration * fps));
  const meta = {
    stats: plan.stats,
    durationSec: totalDuration,
    spec: plan.spec,
    date: plan.spec.date,
  };

  monitor.reset();

  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  const fromCanvas = createCanvas(width, height);
  const fromCtx = fromCanvas.getContext('2d');
  const toCanvas = createCanvas(width, height);
  const toCtx = toCanvas.getContext('2d');

  const renderScene = (target, scene, localTime, frameIndex) => {
    target.setTransform(1, 0, 0, 1, 0, 0);
    target.clearRect(0, 0, width, height);
    target.save();
    target.scale(scale, scale);
    drawBackground(target, theme, localTime, scene.seed);
    drawSceneContent(target, scene, localTime, theme, meta);
    drawGrain(target, theme, frameIndex);
    drawVignette(target, theme);
    target.restore();
  };

  // 先合成配乐与音效，再把 wav 作为第二路输入交给 ffmpeg
  const audioPath = plan.audio ? outPath.replace(/\.mp4$/, '.wav') : null;
  let audioResult = null;
  if (audioPath) {
    audioResult = await renderAudio(plan, audioPath);
  }

  const audioArgs = audioPath
    ? ['-i', audioPath, '-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac', '-b:a', '192k', '-shortest']
    : ['-an'];

  const args = [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-f',
    'rawvideo',
    '-pix_fmt',
    'rgba',
    '-s',
    `${width}x${height}`,
    '-r',
    String(fps),
    '-i',
    'pipe:0',
    ...audioArgs,
    '-c:v',
    'libx264',
    '-preset',
    'veryfast',
    '-crf',
    '20',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    '-colorspace',
    'bt709',
    '-color_primaries',
    'bt709',
    '-color_trc',
    'bt709',
    outPath,
  ];

  const ff = spawn('ffmpeg', args, { stdio: ['pipe', 'ignore', 'pipe'] });
  let stderr = '';
  ff.stderr.on('data', (chunk) => {
    stderr = `${stderr}${chunk.toString()}`.slice(-8000);
  });
  const closed = new Promise((resolve, reject) => {
    ff.on('error', reject);
    ff.on('close', (code) => resolve(code));
  });
  let ffClosed = false;
  closed.then(() => {
    ffClosed = true;
  });
  ff.stdin.on('error', () => {});

  const samples = [0.1, 0.32, 0.55, 0.78, 0.95].map((p) =>
    Math.min(totalFrames - 1, Math.max(0, Math.round(totalFrames * p))),
  );
  const sampleResults = [];
  const bgLum = hexLum(theme.bg1);

  try {
    for (let frame = 0; frame < totalFrames; frame += 1) {
      if (isCanceled && isCanceled()) throw new RenderCanceled();
      const t = frame / fps;
      const at = locate(scenes, t);

      if (at.transition) {
        renderScene(fromCtx, scenes[at.transition.prevIndex], at.transition.prevLocal, frame);
        renderScene(toCtx, scenes[at.index], at.local, frame);
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.globalAlpha = 1;
        ctx.clearRect(0, 0, width, height);
        ctx.save();
        ctx.scale(scale, scale);
        drawTransition(
          ctx,
          fromCanvas,
          toCanvas,
          at.transition.kind,
          at.transition.progress,
          theme,
        );
        ctx.restore();
      } else {
        renderScene(ctx, scenes[at.index], at.local, frame);
      }

      const image = ctx.getImageData(0, 0, width, height);
      const buffer = Buffer.from(image.data.buffer, image.data.byteOffset, image.data.byteLength);

      if (samples.includes(frame)) {
        sampleResults.push({ frame, ink: Number(inkRatio(buffer, bgLum).toFixed(4)) });
      }

      if (ffClosed) {
        const error = new Error(`ffmpeg 提前退出：${stderr.split('\n').slice(-2).join(' ')}`);
        error.code = 'encode_failed';
        throw error;
      }

      if (!ff.stdin.write(buffer)) {
        await waitDrain(ff.stdin);
        if (ffClosed) {
          const error = new Error(`ffmpeg 提前退出：${stderr.split('\n').slice(-2).join(' ')}`);
          error.code = 'encode_failed';
          throw error;
        }
      }

      if (onProgress && (frame % 5 === 0 || frame === totalFrames - 1)) {
        onProgress({
          stage: '渲染中',
          frames_done: frame + 1,
          frames_total: totalFrames,
          progress: (frame + 1) / totalFrames,
        });
      }
    }

    ff.stdin.end();
    const code = await closed;
    if (code !== 0) {
      const error = new Error(`ffmpeg 编码失败（退出码 ${code}）：${stderr.split('\n').slice(-3).join(' ')}`);
      error.code = 'encode_failed';
      throw error;
    }
  } catch (error) {
    if (!ff.killed) ff.kill('SIGKILL');
    await fs.rm(outPath, { force: true }).catch(() => {});
    if (audioPath) await fs.rm(audioPath, { force: true }).catch(() => {});
    throw error;
  }

  if (audioPath) await fs.rm(audioPath, { force: true }).catch(() => {});

  // 封面帧
  const posterAt = Math.min(1.5, Math.max(0.2, scenes[0].duration * 0.45));
  const at = locate(scenes, posterAt);
  renderScene(ctx, scenes[at.index], at.local, Math.round(posterAt * fps));
  await fs.writeFile(posterPath, await canvas.encode('png'));

  const stat = await fs.stat(outPath);
  const warnings = [...monitor.list()];
  if (audioResult && audioResult.peak < 0.02) {
    warnings.push('配乐音量过低，检查音效合成');
  }
  for (const sample of sampleResults) {
    if (sample.ink < 0.01) {
      warnings.push(`第 ${sample.frame} 帧画面几乎空白（墨量 ${(sample.ink * 100).toFixed(2)}%）`);
    }
  }
  if (warnings.length > 0) {
    // 只保留前 12 条，避免任务 JSON 过大
    warnings.splice(12);
  }

  return {
    frames: totalFrames,
    width,
    height,
    fps,
    duration_ms: Math.round(totalDuration * 1000),
    bytes: stat.size,
    audio: Boolean(audioPath),
    audio_bytes: audioResult?.bytes || 0,
    samples: sampleResults,
    checks: {
      passed: warnings.length === 0,
      warnings,
    },
  };
}
