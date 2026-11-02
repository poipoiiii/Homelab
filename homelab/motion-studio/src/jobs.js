// 任务队列：单进程内存队列 + 文件持久化，渲染并发默认 1（CPU 密集，保护其他容器）。
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { buildPlan } from './plan.js';
import { validateSpec } from './validate.js';
import { renderVideo, RenderCanceled } from './render.js';

export class JobError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function now() {
  return Date.now();
}

export class JobStore {
  constructor({ dataDir, concurrency = 1, maxJobs = 200, maxQueue = 8, keepDays = 14, log = console.log }) {
    this.dataDir = dataDir;
    this.jobsDir = path.join(dataDir, 'jobs');
    this.concurrency = Math.max(1, concurrency);
    this.maxJobs = Math.max(10, maxJobs);
    this.maxQueue = Math.max(1, maxQueue);
    this.keepDays = Math.max(1, keepDays);
    this.log = log;
    this.jobs = new Map();
    this.running = 0;
    this.stopping = false;
  }

  async init() {
    await fs.mkdir(this.jobsDir, { recursive: true });
    const entries = await fs.readdir(this.jobsDir, { withFileTypes: true }).catch(() => []);
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const file = path.join(this.jobsDir, entry.name, 'job.json');
      try {
        const job = JSON.parse(await fs.readFile(file, 'utf8'));
        if (job.status === 'queued') {
          // 重启后内存里的 plan 丢了，用持久化的 spec 重建一份，接着排队
          try {
            job._plan = buildPlan(job.spec);
          } catch {
            job.status = 'failed';
            job.stage = '恢复失败';
            job.finished_at = now();
            job.error = { code: 'interrupted', message: '服务重启后无法恢复排队任务，请重新提交' };
            await this.save(job);
          }
        }
        if (job.status === 'running' || job.status === 'cancel_requested') {
          job.status = job.status === 'cancel_requested' ? 'canceled' : 'failed';
          job.stage = job.status === 'canceled' ? '已取消' : '服务重启，任务中断';
          job.finished_at = job.finished_at || now();
          job.error =
            job.status === 'failed'
              ? { code: 'interrupted', message: '服务重启，任务被中断，请重新提交' }
              : undefined;
          await this.save(job);
        }
        this.jobs.set(job.id, job);
      } catch {
        // 损坏的任务目录直接跳过，不影响启动
      }
    }
    await this.cleanup();
    this.log(`任务恢复完成：${this.jobs.size} 个历史任务，${this.queued().length} 个排队中`);
    this.cleanupTimer = setInterval(() => {
      this.cleanup().catch(() => {});
    }, 6 * 3600 * 1000);
    this.cleanupTimer.unref?.();
    this.pump();
  }

  queued() {
    return [...this.jobs.values()]
      .filter((job) => job.status === 'queued')
      .sort((a, b) => a.created_at - b.created_at);
  }

  queuePosition(job) {
    if (job.status !== 'queued') return 0;
    const list = this.queued();
    const index = list.findIndex((item) => item.id === job.id);
    return index < 0 ? 0 : index + 1;
  }

  publicJob(job) {
    return {
      id: job.id,
      status: job.status,
      stage: job.stage || '',
      progress: Number((job.progress || 0).toFixed(3)),
      frames_done: job.frames_done || 0,
      frames_total: job.frames_total || 0,
      queue_position: this.queuePosition(job),
      created_at: job.created_at,
      started_at: job.started_at || null,
      finished_at: job.finished_at || null,
      elapsed_ms: job.elapsed_ms || 0,
      template: job.template,
      theme: job.theme,
      title: job.title,
      width: job.width || 0,
      height: job.height || 0,
      fps: job.fps || 0,
      duration_ms: job.duration_ms || 0,
      bytes: job.bytes || 0,
      stats: job.stats || {},
      video_url: job.status === 'succeeded' ? `/api/v1/jobs/${job.id}/video` : null,
      poster_url: job.status === 'succeeded' ? `/api/v1/jobs/${job.id}/poster` : null,
      checks: job.checks || null,
      error: job.error || null,
    };
  }

  async create(input) {
    if (this.stopping) throw new JobError(503, 'shutting_down', '服务正在停止，稍后再试');
    const spec = validateSpec(input);
    const plan = buildPlan(spec);
    if (this.queued().length >= this.maxQueue) {
      throw new JobError(429, 'queue_full', `排队任务已达上限（${this.maxQueue} 个），稍后再试`);
    }

    const id = `ms_${now().toString(36)}${crypto.randomBytes(2).toString('hex')}`;
    const dir = path.join(this.jobsDir, id);
    await fs.mkdir(dir, { recursive: true });
    const job = {
      id,
      status: 'queued',
      stage: '排队中',
      progress: 0,
      frames_done: 0,
      frames_total: Math.round(plan.totalDuration * plan.fps),
      created_at: now(),
      started_at: null,
      finished_at: null,
      elapsed_ms: 0,
      template: plan.template,
      theme: plan.theme,
      title: spec.title || spec.scenes.find((s) => s.type === 'cover')?.title || '',
      width: plan.width,
      height: plan.height,
      fps: plan.fps,
      duration_ms: Math.round(plan.totalDuration * 1000),
      bytes: 0,
      stats: plan.stats,
      spec,
    };
    this.jobs.set(id, job);
    job._plan = plan;
    job._dir = dir;
    await this.save(job);
    this.log(`新任务 ${id}：${job.title} / ${plan.scenes.length} 个场景 / ${plan.totalDuration.toFixed(1)}s`);
    this.pump();
    return this.publicJob(job);
  }

  get(id) {
    return this.jobs.get(id) || null;
  }

  list({ status = 'all', limit = 20, before = null } = {}) {
    const size = Math.min(50, Math.max(1, Number(limit) || 20));
    let jobs = [...this.jobs.values()];
    if (status === 'active') {
      jobs = jobs.filter((job) => ['queued', 'running', 'cancel_requested'].includes(job.status));
    } else if (status && status !== 'all') {
      jobs = jobs.filter((job) => job.status === status);
    }
    jobs.sort((a, b) => b.created_at - a.created_at);
    if (before) {
      const cursor = Number(before);
      if (Number.isFinite(cursor)) jobs = jobs.filter((job) => job.created_at < cursor);
    }
    const page = jobs.slice(0, size);
    return {
      jobs: page.map((job) => this.publicJob(job)),
      next_cursor: jobs.length > size ? page[page.length - 1].created_at : null,
    };
  }

  async cancel(id) {
    const job = this.jobs.get(id);
    if (!job) throw new JobError(404, 'not_found', '任务不存在');
    if (job.status === 'queued') {
      job.status = 'canceled';
      job.stage = '已取消';
      job.finished_at = now();
      await this.save(job);
      this.pump();
    } else if (job.status === 'running') {
      job.cancelRequested = true;
      job.status = 'cancel_requested';
      job.stage = '正在取消';
      await this.save(job);
    } else if (job.status === 'cancel_requested') {
      // 幂等
    } else {
      throw new JobError(409, 'job_finished', '任务已经结束，不能取消');
    }
    return this.publicJob(job);
  }

  async remove(id) {
    const job = this.jobs.get(id);
    if (!job) throw new JobError(404, 'not_found', '任务不存在');
    if (['queued', 'running', 'cancel_requested'].includes(job.status)) {
      throw new JobError(409, 'job_active', '任务还在进行中，先取消再删除');
    }
    await fs.rm(job._dir || path.join(this.jobsDir, id), { recursive: true, force: true });
    this.jobs.delete(id);
  }

  async save(job) {
    const dir = job._dir || path.join(this.jobsDir, job.id);
    const file = path.join(dir, 'job.json');
    const { _plan, _dir, cancelRequested, ...persisted } = job;
    const tmp = `${file}.tmp`;
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(tmp, JSON.stringify(persisted, null, 2));
    await fs.rename(tmp, file);
  }

  async cleanup() {
    const cutoff = now() - this.keepDays * 24 * 3600 * 1000;
    const finished = [...this.jobs.values()]
      .filter((job) => !['queued', 'running', 'cancel_requested'].includes(job.status))
      .sort((a, b) => (a.finished_at || a.created_at) - (b.finished_at || b.created_at));
    for (const job of finished) {
      const age = job.finished_at || job.created_at;
      const overCount = this.jobs.size > this.maxJobs;
      if (age < cutoff || overCount) {
        await fs.rm(job._dir || path.join(this.jobsDir, job.id), { recursive: true, force: true });
        this.jobs.delete(job.id);
      }
    }
  }

  pump() {
    if (this.stopping) return;
    while (this.running < this.concurrency) {
      const next = this.queued()[0];
      if (!next) return;
      this.running += 1;
      this.runJob(next).finally(() => {
        this.running -= 1;
        this.pump();
      });
    }
  }

  async runJob(job) {
    job.status = 'running';
    job.started_at = now();
    job.stage = '准备';
    job.cancelRequested = false;
    await this.save(job);

    const dir = job._dir || path.join(this.jobsDir, job.id);
    const outPath = path.join(dir, 'out.mp4');
    const posterPath = path.join(dir, 'poster.png');
    let lastSave = 0;

    try {
      const result = await renderVideo(job._plan, {
        outPath,
        posterPath,
        isCanceled: () => job.cancelRequested,
        onProgress: (progress) => {
          job.stage = progress.stage;
          job.progress = progress.progress;
          job.frames_done = progress.frames_done;
          job.frames_total = progress.frames_total;
          if (now() - lastSave > 900) {
            lastSave = now();
            this.save(job).catch(() => {});
          }
        },
      });

      job.status = 'succeeded';
      job.stage = '已完成';
      job.progress = 1;
      job.finished_at = now();
      job.elapsed_ms = job.finished_at - job.started_at;
      job.duration_ms = result.duration_ms;
      job.width = result.width;
      job.height = result.height;
      job.fps = result.fps;
      job.bytes = result.bytes;
      job.frames_total = result.frames;
      job.frames_done = result.frames;
      job.checks = result.checks;
      this.log(`任务完成 ${job.id}：${result.frames} 帧 / ${(result.bytes / 1048576).toFixed(1)} MB / ${(job.elapsed_ms / 1000).toFixed(1)}s`);
    } catch (error) {
      if (error instanceof RenderCanceled) {
        job.status = 'canceled';
        job.stage = '已取消';
        job.finished_at = now();
        job.elapsed_ms = job.finished_at - job.started_at;
        this.log(`任务取消 ${job.id}`);
      } else {
        job.status = 'failed';
        job.stage = '失败';
        job.finished_at = now();
        job.elapsed_ms = job.finished_at - job.started_at;
        job.error = {
          code: error.code || 'render_failed',
          message: String(error.message || error).slice(0, 400),
        };
        this.log(`任务失败 ${job.id}：${job.error.message}`);
      }
    } finally {
      job._plan = null;
      await this.save(job);
    }
  }

  async shutdown() {
    this.stopping = true;
    if (this.cleanupTimer) clearInterval(this.cleanupTimer);
    for (const job of this.jobs.values()) {
      if (job.status === 'running') job.cancelRequested = true;
    }
    const deadline = now() + 6000;
    while (this.running > 0 && now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
  }
}
