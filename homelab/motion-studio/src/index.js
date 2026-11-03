// HTTP 服务：任务提交/查询/取消/删除 + 视频与封面下载（支持 Range，方便手机播放器拖动）。
import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { JobStore } from './jobs.js';
import { LIMITS } from './validate.js';
import { RESOLUTIONS, MAX_TOTAL_SECONDS } from './plan.js';
import { THEMES } from './theme.js';

const VERSION = '2.0.0';
const PORT = Number(process.env.PORT || 8095);
const DATA_DIR = process.env.DATA_DIR || path.resolve('data');
const TOKEN = (process.env.MOTION_TOKEN || '').trim();
const CONCURRENCY = Math.max(1, Number(process.env.RENDER_CONCURRENCY || 1));
const MAX_JOBS = Math.max(10, Number(process.env.MAX_JOBS || 200));
const MAX_QUEUE = Math.max(1, Number(process.env.MAX_QUEUE || 8));
const KEEP_DAYS = Math.max(1, Number(process.env.KEEP_DAYS || 14));
const BODY_LIMIT = 512 * 1024;

function log(message) {
  console.log(`[${new Date().toISOString()}] ${message}`);
}

const ffmpeg = spawnSync('ffmpeg', ['-version'], { encoding: 'utf8' });
const FFMPEG_OK = ffmpeg.status === 0;
const FFMPEG_VERSION = FFMPEG_OK ? (ffmpeg.stdout || '').split('\n')[0] : '';

function cjkFontsReady() {
  try {
    const result = spawnSync('fc-list', [':lang=zh', 'family'], { encoding: 'utf8' });
    return result.status === 0 && /CJK|Source Han|Noto (Sans|Serif)/i.test(result.stdout || '');
  } catch {
    return false;
  }
}

const store = new JobStore({
  dataDir: DATA_DIR,
  concurrency: CONCURRENCY,
  maxJobs: MAX_JOBS,
  maxQueue: MAX_QUEUE,
  keepDays: KEEP_DAYS,
  log,
});

function json(res, status, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': body.length,
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

function fail(res, status, code, message) {
  json(res, status, { error: { code, message } });
}

function allowed(req, url) {
  if (!TOKEN) return true;
  const header = String(req.headers.authorization || '');
  const bearer = header.startsWith('Bearer ') ? header.slice(7).trim() : '';
  const headerToken = String(req.headers['x-api-token'] || '').trim();
  const queryToken = String(url.searchParams.get('token') || '').trim();
  const candidate = bearer || headerToken || queryToken;
  if (!candidate) return false;
  const a = Buffer.from(candidate);
  const b = Buffer.from(TOKEN);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

async function readJson(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > BODY_LIMIT) {
      const error = new Error(`请求体超过 ${Math.round(BODY_LIMIT / 1024)} KB`);
      error.status = 413;
      error.code = 'payload_too_large';
      throw error;
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    const error = new Error('请求体不是合法 JSON');
    error.status = 400;
    error.code = 'bad_json';
    throw error;
  }
}

async function serveFile(req, res, filePath, contentType, filename) {
  let stat;
  try {
    stat = await fsp.stat(filePath);
  } catch {
    fail(res, 404, 'not_found', '文件不存在或已被清理');
    return;
  }
  res.setHeader('Content-Type', contentType);
  res.setHeader('Accept-Ranges', 'bytes');
  res.setHeader('Cache-Control', 'private, max-age=3600');
  res.setHeader('Content-Disposition', `inline; filename="${filename}"`);

  const range = req.headers.range;
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(String(range).trim());
    if (!match) {
      fail(res, 416, 'bad_range', 'Range 格式不正确');
      return;
    }
    const start = match[1] === '' ? 0 : Number(match[1]);
    const end = match[2] === '' ? stat.size - 1 : Number(match[2]);
    if (start >= stat.size || end < start) {
      res.setHeader('Content-Range', `bytes */${stat.size}`);
      fail(res, 416, 'bad_range', '请求范围超出文件大小');
      return;
    }
    const finalEnd = Math.min(end, stat.size - 1);
    res.writeHead(206, {
      'Content-Range': `bytes ${start}-${finalEnd}/${stat.size}`,
      'Content-Length': finalEnd - start + 1,
    });
    if (req.method === 'HEAD') {
      res.end();
      return;
    }
    fs.createReadStream(filePath, { start, end: finalEnd }).pipe(res);
    return;
  }

  res.writeHead(200, { 'Content-Length': stat.size });
  if (req.method === 'HEAD') {
    res.end();
    return;
  }
  fs.createReadStream(filePath).pipe(res);
}

const routes = [
  {
    method: 'GET',
    pattern: /^\/healthz$/,
    handler: async (req, res) => {
      json(res, 200, {
        status: 'ok',
        version: VERSION,
        renderer: 'hyperframes',
        ffmpeg: FFMPEG_OK,
        ffmpeg_version: FFMPEG_VERSION,
        cjk_fonts: cjkFontsReady(),
        queue: {
          running: store.running,
          queued: store.queued().length,
          capacity: CONCURRENCY,
          max_queue: MAX_QUEUE,
        },
        uptime_sec: Math.round(process.uptime()),
      });
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/v1\/meta$/,
    handler: async (req, res) => {
      json(res, 200, {
        service: 'motion-studio',
        version: VERSION,
        renderer: 'hyperframes',
        templates: [
          { id: 'ledger', name: '台账', desc: '按章节自动分页，条目逐行入场' },
          { id: 'scenes', name: '自定义场景', desc: '自由组合封面/章节/列表/数字/引用/结尾' },
        ],
        themes: Object.values(THEMES).map((theme) => ({
          id: theme.id,
          name: theme.name,
          desc: theme.desc,
        })),
        resolutions: Object.keys(RESOLUTIONS),
        fps: [24, 30],
        limits: { ...LIMITS, max_seconds: MAX_TOTAL_SECONDS, body_kb: BODY_LIMIT / 1024 },
        queue: { running: store.running, queued: store.queued().length, capacity: CONCURRENCY },
      });
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/v1\/jobs$/,
    handler: async (req, res, url) => {
      const page = store.list({
        status: url.searchParams.get('status') || 'all',
        limit: url.searchParams.get('limit') || 20,
        before: url.searchParams.get('before'),
      });
      json(res, 200, page);
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/v1\/jobs$/,
    handler: async (req, res) => {
      const body = await readJson(req);
      const job = await store.create(body);
      json(res, 202, job);
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/v1\/jobs\/([a-z0-9_]+)$/,
    handler: async (req, res, url, [id]) => {
      const job = store.get(id);
      if (!job) {
        fail(res, 404, 'not_found', '任务不存在');
        return;
      }
      json(res, 200, store.publicJob(job));
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/v1\/jobs\/([a-z0-9_]+)\/cancel$/,
    handler: async (req, res, url, [id]) => {
      json(res, 200, await store.cancel(id));
    },
  },
  {
    method: 'DELETE',
    pattern: /^\/api\/v1\/jobs\/([a-z0-9_]+)$/,
    handler: async (req, res, url, [id]) => {
      await store.remove(id);
      json(res, 200, { deleted: true, id });
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/v1\/jobs\/([a-z0-9_]+)\/video$/,
    handler: async (req, res, url, [id]) => {
      const job = store.get(id);
      if (!job || job.status !== 'succeeded') {
        fail(res, 404, 'not_found', '视频不存在或任务未完成');
        return;
      }
      await serveFile(
        req,
        res,
        path.join(job._dir || path.join(store.jobsDir, id), 'out.mp4'),
        'video/mp4',
        `${id}.mp4`,
      );
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/v1\/jobs\/([a-z0-9_]+)\/poster$/,
    handler: async (req, res, url, [id]) => {
      const job = store.get(id);
      if (!job || job.status !== 'succeeded') {
        fail(res, 404, 'not_found', '封面不存在或任务未完成');
        return;
      }
      await serveFile(
        req,
        res,
        path.join(job._dir || path.join(store.jobsDir, id), 'poster.png'),
        'image/png',
        `${id}.png`,
      );
    },
  },
];

const server = http.createServer(async (req, res) => {
  const started = Date.now();
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  res.setHeader('Access-Control-Allow-Origin', req.headers.origin || '*');
  res.setHeader('Vary', 'Origin');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,DELETE,HEAD,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Authorization,Content-Type,X-Api-Token');
  res.setHeader('Access-Control-Max-Age', '600');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (url.pathname === '/') {
    json(res, 200, {
      service: 'motion-studio',
      version: VERSION,
      docs: 'API.md',
      health: '/healthz',
      api: '/api/v1/meta',
    });
    return;
  }

  if (!url.pathname.startsWith('/api/') && url.pathname !== '/healthz') {
    fail(res, 404, 'not_found', '接口不存在');
    return;
  }

  if (url.pathname !== '/healthz' && !allowed(req, url)) {
    fail(res, 401, 'unauthorized', 'Token 不正确，请检查请求头 Authorization: Bearer <token>');
    return;
  }

  try {
    for (const route of routes) {
      const methodOk = route.method === req.method || (req.method === 'HEAD' && route.method === 'GET');
      if (!methodOk) continue;
      const match = route.pattern.exec(url.pathname);
      if (!match) continue;
      await route.handler(req, res, url, match.slice(1));
      const cost = Date.now() - started;
      if (req.method !== 'GET' || cost > 500) {
        log(`${req.method} ${url.pathname} ${res.statusCode} ${cost}ms`);
      }
      return;
    }
    fail(res, 404, 'not_found', '接口不存在');
  } catch (error) {
    const status = error.status || 500;
    const code = error.code || 'internal_error';
    if (status >= 500) log(`ERROR ${req.method} ${url.pathname}: ${error.stack || error.message}`);
    if (!res.headersSent) fail(res, status, code, error.message || '服务内部错误');
    else res.end();
  }
});

server.requestTimeout = 30_000;
server.headersTimeout = 35_000;

async function main() {
  if (!FFMPEG_OK) {
    log('没有找到 ffmpeg，服务无法渲染。请在镜像里安装 ffmpeg 后重启。');
    process.exit(1);
  }
  if (!cjkFontsReady()) {
    log('警告：未检测到 CJK 字体，中文会渲染成方块。请安装 fonts-noto-cjk。');
  }
  await store.init();
  server.listen(PORT, '0.0.0.0', () => {
    log(`motion-studio ${VERSION} 已启动：http://0.0.0.0:${PORT}`);
    log(`鉴权：${TOKEN ? '已开启' : '未设置 MOTION_TOKEN（仅建议本机使用）'}；渲染并发 ${CONCURRENCY}`);
  });
}

let shuttingDown = false;
async function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  log(`收到 ${signal}，正在停止…`);
  server.close();
  await store.shutdown();
  process.exit(0);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

main().catch((error) => {
  log(`启动失败：${error.stack || error.message}`);
  process.exit(1);
});

export { server, store };
