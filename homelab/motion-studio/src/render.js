// HyperFrames 渲染层：生成 HTML 合成，交给无头 Chrome 逐帧抓取，ffmpeg 编码后再合入配乐。
// HTTP/任务契约保持不变，客户端仍然只提交 scene 列表并轮询同一个 job。
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  createRenderJob,
  executeRenderJob,
  RenderCancelledError,
} from '@hyperframes/producer';
import { buildCompositionHtml } from './html.js';
import { renderAudio } from './audio.js';

const GSAP_PATH = fileURLToPath(new URL('../node_modules/gsap/dist/gsap.min.js', import.meta.url));

export class RenderCanceled extends Error {
  constructor() {
    super('渲染已取消');
    this.code = 'canceled';
  }
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ['ignore', 'ignore', 'pipe'] });
    let stderr = '';
    child.stderr.on('data', (chunk) => {
      stderr = `${stderr}${chunk.toString()}`.slice(-8000);
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      const error = new Error(
        `${command} 退出码 ${code}：${stderr.split('\n').slice(-3).join(' ').trim()}`,
      );
      error.code = 'encode_failed';
      reject(error);
    });
  });
}

function probeDuration(file) {
  return new Promise((resolve) => {
    const child = spawn(
      'ffprobe',
      ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', file],
      { stdio: ['ignore', 'pipe', 'ignore'] },
    );
    let output = '';
    child.stdout.on('data', (chunk) => {
      output += chunk.toString();
    });
    child.on('error', () => resolve(0));
    child.on('close', (code) => {
      const value = Number(output.trim());
      resolve(code === 0 && Number.isFinite(value) ? value : 0);
    });
  });
}

function prepareProject(dir, plan) {
  return (async () => {
    await fs.mkdir(path.join(dir, 'vendor'), { recursive: true });
    await fs.writeFile(path.join(dir, 'index.html'), buildCompositionHtml(plan));
    await fs.copyFile(GSAP_PATH, path.join(dir, 'vendor', 'gsap.min.js'));
  })();
}

async function cleanupProject(dir) {
  await fs.rm(path.join(dir, 'index.html'), { force: true }).catch(() => {});
  await fs.rm(path.join(dir, 'vendor'), { recursive: true, force: true }).catch(() => {});
}

/**
 * 渲染整条片子。
 * @param {object} plan buildPlan 的结果
 * @param {object} options { outPath, posterPath, onProgress, isCanceled }
 */
export async function renderVideo(plan, { outPath, posterPath, onProgress, isCanceled }) {
  const { width, height, fps, totalDuration } = plan;
  const dir = path.dirname(outPath);
  const silentPath = path.join(dir, 'render.mp4');
  const audioPath = plan.audio ? path.join(dir, 'audio.wav') : null;
  const totalFrames = Math.max(1, Math.round(totalDuration * fps));
  const warnings = [];

  const report = (stage, progress, framesDone = 0) => {
    if (!onProgress) return;
    onProgress({
      stage,
      progress: Math.max(0, Math.min(1, progress)),
      frames_done: Math.min(totalFrames, Math.max(0, framesDone)),
      frames_total: totalFrames,
    });
  };

  try {
    if (isCanceled && isCanceled()) throw new RenderCanceled();

    let audioResult = null;
    if (audioPath) {
      report('合成音轨', 0.02, 0);
      audioResult = await renderAudio(plan, audioPath);
      if (audioResult.peak < 0.02) warnings.push('配乐音量过低，检查音效合成');
      report('合成音轨', 0.08, 0);
    }

    if (isCanceled && isCanceled()) throw new RenderCanceled();
    await prepareProject(dir, plan);
    report('准备', 0.09, 0);

    const config = {
      fps,
      quality: process.env.HYPERFRAMES_QUALITY || 'standard',
      format: 'mp4',
    };
    const workers = Number(process.env.HYPERFRAMES_WORKERS || 0);
    if (Number.isFinite(workers) && workers > 0) config.workers = workers;

    const controller = new AbortController();
    const progressBase = 0.09;
    const progressSpan = 0.83;
    const job = createRenderJob(config);

    try {
      await executeRenderJob(
        job,
        dir,
        silentPath,
        (currentJob) => {
          if (isCanceled && isCanceled()) controller.abort();
          // HyperFrames 的 job.progress 是 0~100，不是 0~1
          const progress = Math.max(0, Math.min(1, (Number(currentJob.progress) || 0) / 100));
          report(
            '渲染中',
            progressBase + progress * progressSpan,
            Math.round(progress * totalFrames),
          );
        },
        controller.signal,
        () => {
          if (isCanceled && isCanceled()) throw new RenderCanceled();
        },
      );
    } catch (error) {
      if (
        error instanceof RenderCancelledError ||
        error?.name === 'RenderCancelledError' ||
        error?.reason === 'user_cancelled' ||
        error?.reason === 'aborted'
      ) {
        throw new RenderCanceled();
      }
      throw error;
    }

    const stat = await fs.stat(silentPath);

    if (audioPath) {
      report('封装中', 0.94, totalFrames);
      await run('ffmpeg', [
        '-hide_banner',
        '-loglevel',
        'error',
        '-y',
        '-i',
        silentPath,
        '-i',
        audioPath,
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
        '-c:v',
        'copy',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-shortest',
        '-movflags',
        '+faststart',
        outPath,
      ]);
      await fs.rm(silentPath, { force: true }).catch(() => {});
      await fs.rm(audioPath, { force: true }).catch(() => {});
    } else {
      await fs.rename(silentPath, outPath);
    }

    const posterAt = Math.min(1.5, Math.max(0.2, plan.scenes[0].duration * 0.45));
    try {
      report('生成封面', 0.97, totalFrames);
      await run('ffmpeg', [
        '-hide_banner',
        '-loglevel',
        'error',
        '-y',
        '-ss',
        String(posterAt),
        '-i',
        outPath,
        '-frames:v',
        '1',
        posterPath,
      ]);
    } catch (error) {
      warnings.push(`封面生成失败：${String(error.message || error).slice(0, 160)}`);
    }

    const duration = await probeDuration(outPath);
    if (!duration) {
      warnings.push('无法读取成片时长');
    } else if (Math.abs(duration - totalDuration) > 0.25) {
      warnings.push(`成片时长 ${duration.toFixed(2)}s 与计划 ${totalDuration.toFixed(2)}s 不一致`);
    }

    const finalStat = await fs.stat(outPath);
    if (finalStat.size < 1024) warnings.push('成片体积异常，编码可能失败');
    await cleanupProject(dir);

    return {
      frames: totalFrames,
      width,
      height,
      fps,
      duration_ms: Math.round((duration || totalDuration) * 1000),
      bytes: finalStat.size,
      audio: Boolean(audioPath),
      audio_bytes: audioResult?.bytes || 0,
      checks: {
        passed: warnings.length === 0,
        warnings: warnings.slice(0, 12),
      },
    };
  } catch (error) {
    await fs.rm(silentPath, { force: true }).catch(() => {});
    await fs.rm(outPath, { force: true }).catch(() => {});
    await fs.rm(posterPath, { force: true }).catch(() => {});
    if (audioPath) await fs.rm(audioPath, { force: true }).catch(() => {});
    await cleanupProject(dir);
    throw error;
  }
}
