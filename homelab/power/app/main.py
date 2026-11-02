"""电源面板：列出所有容器，可按容器或按组一键 stop/start。

只做两件事：查状态（读代理）、start/stop（写代理）。不接 EXEC，不碰数据卷。
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

READ = os.getenv("DOCKER_PROXY_READ", "http://power-proxy-read:2375").rstrip("/")
WRITE = os.getenv("DOCKER_PROXY_WRITE", "http://power-proxy-write:2375").rstrip("/")
HOST_AGENT = os.getenv("HOST_AGENT_URL", "http://host.docker.internal:8093").rstrip("/")

# 面板自己不显示：把自己关掉就失联了；homarr 按用户要求也不显示
HIDDEN = {"power", "power-proxy-read", "power-proxy-write", "homarr"}

# 组内启动先后的参考顺序（停的时候反着来）；没列到的按名字排
START_ORDER = {
    "librechat-mongo": 10,
    "librechat": 20,
    "lab-tools-docker-proxy": 30,
    "lab-tools-docker-proxy-write": 31,
    "lab-tools": 40,
    "metube": 50,
    "pinchflat": 51,
    "jellyfin": 60,
    "cloudreve": 70,
    "rong-ledger": 80,
    "traccar": 90,
    "frpc": 95,
    "dozzle": 96,
}

GROUP_ORDER = ["AI 助手", "影音", "家庭服务", "入口与运维", "宿主机服务", "未分组"]

# 没打 dev.dozzle.group 标签的老容器，在这里归组
GROUP_FALLBACK = {"cloudreve": "家庭服务", "frpc": "入口与运维"}

# 宿主机 systemd 服务单独成组，启动顺序：daemon 先、web 后；ComfyUI 最后（闲置可停，释放显存）
HOST_GROUP = "宿主机服务"
UNIT_ORDER = {
    "mcsm-daemon.service": 10,
    "mcsm-web.service": 20,
    "1panel.service": 30,
    "comfyui.service": 40,
}
UNIT_STATE = {"active": "running", "activating": "restarting", "failed": "dead", "inactive": "exited"}

app = FastAPI(title="power", docs_url=None, redoc_url=None)
BRANDING_DIR = os.getenv("BRANDING_DIR", "/branding")
if os.path.isdir(BRANDING_DIR):
    app.mount("/branding", StaticFiles(directory=BRANDING_DIR), name="branding")

# 面板自带静态资源（背景图等），随镜像一起发布
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _containers() -> list[dict]:
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{READ}/containers/json", params={"all": 1})
        response.raise_for_status()

    result = []
    for item in response.json():
        name = (item.get("Names") or [""])[0].lstrip("/")
        if not name or name in HIDDEN:
            continue
        labels = item.get("Labels") or {}
        # 优先取映射到宿主机的端口；没有映射才退回镜像自身暴露的端口
        published = sorted({p["PublicPort"] for p in item.get("Ports") or [] if p.get("PublicPort")})
        if published:
            ports = published
        else:
            ports = sorted({p["PrivatePort"] for p in item.get("Ports") or [] if p.get("PrivatePort")})[:2]
        result.append({
            "name": name,
            "state": item.get("State", "unknown"),
            "group": labels.get("dev.dozzle.group") or GROUP_FALLBACK.get(name) or "未分组",
            "kind": "container",
            "ports": ports,
        })

    result.sort(key=lambda c: (START_ORDER.get(c["name"], 500), c["name"]))
    return result


# Docker stats 单次采样有延迟，缓存几秒，避免每次页面刷新都重扫一遍
STATS_TTL = 5
_stats_cache: tuple[float, tuple[str, ...], dict[str, dict]] = (0.0, (), {})


def _memory(name: str) -> dict | None:
    try:
        with httpx.Client(timeout=6) as client:
            response = client.get(f"{READ}/containers/{name}/stats", params={"stream": "false"})
            response.raise_for_status()
            stats = response.json().get("memory_stats") or {}
    except Exception:
        return None

    usage = int(stats.get("usage") or 0)
    limit = int(stats.get("limit") or 0)
    detail = stats.get("stats") or {}
    # cgroup v2 用 inactive_file，v1 用 cache；两者都要扣掉才是真实占用
    cache = int(detail.get("inactive_file") or detail.get("cache") or 0)
    used = max(0, usage - cache)
    if used <= 0:
        return None
    return {"used": used, "limit": limit}


def _memories(names: list[str]) -> dict[str, dict]:
    global _stats_cache
    if not names:
        return {}
    stamp, cached_names, cached = _stats_cache
    if tuple(names) == cached_names and time.time() - stamp < STATS_TTL:
        return cached

    result: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(names))) as pool:
        for name, value in zip(names, pool.map(_memory, names)):
            if value:
                result[name] = value

    _stats_cache = (time.time(), tuple(names), result)
    return result


def _with_memory(items: list[dict]) -> list[dict]:
    names = [c["name"] for c in items if c["state"] == "running"]
    memories = _memories(names)
    for item in items:
        item["mem"] = memories.get(item["name"])
    return items


def _units() -> list[dict]:
    """宿主机 systemd 服务；代理不可达时返回空列表，不影响容器部分。"""
    try:
        with httpx.Client(timeout=6) as client:
            response = client.get(f"{HOST_AGENT}/units")
            response.raise_for_status()
            raw = response.json().get("units", [])
    except Exception:
        return []

    units = [{
        "name": u["name"],
        "state": UNIT_STATE.get(u.get("state", ""), u.get("state") or "unknown"),
        "group": HOST_GROUP,
        "kind": "unit",
    } for u in raw]
    units.sort(key=lambda u: (UNIT_ORDER.get(u["name"], 500), u["name"]))
    return units


def _groups(items: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for item in items:
        buckets.setdefault(item["group"], []).append(item)

    def rank(name: str) -> int:
        return GROUP_ORDER.index(name) if name in GROUP_ORDER else len(GROUP_ORDER)

    groups = []
    for name in sorted(buckets, key=rank):
        members = buckets[name]
        groups.append({
            "name": name,
            "containers": members,
            "running": sum(1 for m in members if m["state"] == "running"),
            "total": len(members),
            "mem_used": sum(((m.get("mem") or {}).get("used") or 0) for m in members),
        })
    return groups


def _action(name: str, action: str) -> bool:
    params = {"t": 10} if action == "stop" else None
    with httpx.Client(timeout=40) as client:
        response = client.post(f"{WRITE}/containers/{name}/{action}", params=params)
    # 304 = 已经是目标状态，视为成功
    return response.status_code in (204, 304)


def _unit_action(name: str, action: str) -> bool:
    with httpx.Client(timeout=95) as client:
        response = client.post(f"{HOST_AGENT}/units/{name}/{action}")
    return response.status_code == 200


@app.get("/api/state")
def state():
    try:
        items = _with_memory(_containers())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"读代理不可达：{exc}") from exc
    return JSONResponse({"groups": _groups(items + _units())})


@app.post("/api/action")
def action(scope: str, name: str, action: str):
    if action not in ("start", "stop"):
        raise HTTPException(status_code=400, detail="action 只能是 start 或 stop")
    if scope not in ("container", "group", "host"):
        raise HTTPException(status_code=400, detail="scope 只能是 container、group 或 host")

    try:
        items = _containers()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"读代理不可达：{exc}") from exc

    if scope == "host":
        targets = [u for u in _units() if u["name"] == name]
    elif scope == "container":
        targets = [c for c in items if c["name"] == name]
    else:
        targets = [i for i in items + _units() if i["group"] == name]

    if not targets:
        raise HTTPException(status_code=404, detail="找不到要操作的容器或服务")
    if action == "stop":
        targets = list(reversed(targets))

    done, failed = [], []
    for target in targets:
        try:
            ok = _unit_action(target["name"], action) if target["kind"] == "unit" else _action(target["name"], action)
            (done if ok else failed).append(target["name"])
        except Exception as exc:
            failed.append(f"{target['name']}: {exc}")

    if failed:
        return JSONResponse(
            {"ok": False, "action": action, "done": done, "failed": failed},
            status_code=207,
        )
    return {"ok": True, "action": action, "done": done}


@app.get("/healthz")
def healthz():
    return {"ok": True}


PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>电源面板</title>
<link rel="icon" href="/branding/favicon.ico" sizes="any">
<link rel="icon" type="image/png" href="/branding/favicon-32.png" sizes="32x32">
<style>
  :root {
    --bg: #08111c;
    --surface: rgba(13, 22, 35, .40);
    --surface-hi: rgba(26, 40, 58, .56);
    --line: rgba(255, 255, 255, .12);
    --line-hi: rgba(255, 255, 255, .20);
    --text: #eef3fa;
    --muted: #a9b7ca;
    --green: #4be3a1;
    --red: #f0716e;
    --focus: #6fb6ff;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--text); }
  body {
    min-height: 100vh;
    font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  /* 固定背景层：竖图在手机上也不会随页面滚动露出空白 */
  body::before {
    content: ""; position: fixed; inset: 0; z-index: 0;
    background: url("/static/power-bg.jpg") center 30% / cover no-repeat;
  }
  body::after {
    content: ""; position: fixed; inset: 0; z-index: 0;
    background:
      radial-gradient(120% 80% at 50% 0%, rgba(6, 16, 30, .18), transparent 60%),
      linear-gradient(180deg, rgba(4, 10, 18, .30), rgba(4, 10, 18, .52));
  }
  ::selection { background: #2b4d70; color: #fff; }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #2a3038; border-radius: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }

  .wrap { position: relative; z-index: 1; max-width: 720px; margin: 0 auto; padding: 22px 16px 28px; }
  header { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; }
  .brand { display: flex; align-items: center; gap: 8px; }
  .brand img { width: 24px; height: 24px; border-radius: 7px; object-fit: cover; display: block; }
  h1 { margin: 0; font-size: 19px; font-weight: 650; letter-spacing: -0.01em; text-shadow: 0 1px 16px rgba(0, 0, 0, .72); }
  header .hint { color: #c2cedd; font-size: 12.5px; text-shadow: 0 1px 12px rgba(0, 0, 0, .78); }

  .banner {
    position: fixed; z-index: 20; left: 50%; top: 14px; transform: translateX(-50%);
    width: max-content; max-width: calc(100vw - 24px);
    margin: 0; padding: 10px 14px; border-radius: 9px;
    border: 1px solid #5a2c2c; background: rgba(42, 15, 18, .86); color: #f6c0bf; font-size: 13px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, .45);
    backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  }
  .banner[hidden] { display: none; }

  .group { margin-top: 14px; }
  .group-head {
    display: flex; align-items: center; gap: 10px; row-gap: 6px;
    padding: 0 2px 8px; flex-wrap: wrap;
  }

  /* 分组头左侧的折叠热区（右侧按钮不参与折叠，避免误触） */
  .group-toggle {
    display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0;
    cursor: pointer; user-select: none; -webkit-tap-highlight-color: transparent;
  }
  .group-toggle:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; border-radius: 6px; }

  /* 折叠箭头 */
  .chev {
    flex: none; width: 8px; height: 8px; margin-left: 2px;
    border-right: 1.6px solid #9fb2c8; border-bottom: 1.6px solid #9fb2c8;
    transform: rotate(45deg); transition: transform .18s ease; opacity: .85;
  }
  .group[data-open="1"] .chev { transform: rotate(-135deg); }

  /* 折叠时只留分组头；展开时把「已停」提示收起来 */
  .group[data-open="0"] ul { display: none; }
  .group[data-open="1"] .issues { display: none; }
  .issues {
    margin: -2px 2px 8px; font-size: 12px; color: #f0a6a4; line-height: 1.5;
    text-shadow: 0 1px 6px rgba(0, 0, 0, .6);
  }
  .issues[hidden] { display: none; }
  .group-head h2 { margin: 0; font-size: 12.5px; font-weight: 600; letter-spacing: .04em; color: #d2ddeb; text-shadow: 0 1px 10px rgba(0, 0, 0, .85); }
  .group-head .count { margin-left: auto; font-size: 12px; color: #b8c6d8; font-variant-numeric: tabular-nums; text-shadow: 0 1px 10px rgba(0, 0, 0, .85); }
  .group-head .count b { color: var(--text); font-weight: 600; }

  ul { list-style: none; margin: 0; padding: 0; background: var(--surface);
       border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
       backdrop-filter: blur(16px) saturate(130%); -webkit-backdrop-filter: blur(16px) saturate(130%);
       box-shadow: 0 14px 34px rgba(0, 0, 0, .26); }
  li { display: flex; align-items: center; gap: 10px; padding: 7px 12px; }
  li + li { border-top: 1px solid var(--line); }
  li:hover { background: var(--surface-hi); }

  .dot { width: 7px; height: 7px; border-radius: 50%; flex: none; background: #4a5260; }
  .dot.on { background: var(--green); box-shadow: 0 0 0 3px rgba(62,207,142,.12); }
  .dot.warn { background: #c9a227; }
  .cname { font-size: 13.5px; font-weight: 500; text-shadow: 0 1px 6px rgba(0, 0, 0, .55); }
  /* 容器占用的宿主机端口 */
  .port {
    flex: none; font: 11px/1.35 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    color: #93abc6; padding: 2px 5px; border-radius: 5px;
    background: rgba(255, 255, 255, .06); border: 1px solid rgba(255, 255, 255, .10);
  }
  .state { margin-left: auto; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; text-shadow: 0 1px 6px rgba(0, 0, 0, .55); }
  .mem { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; text-shadow: 0 1px 6px rgba(0, 0, 0, .55); }
  .mem-bar { width: 34px; height: 3px; border-radius: 2px; background: #262c35; overflow: hidden; }
  .mem-bar i { display: block; height: 100%; background: var(--focus); opacity: .7; }

  button {
    appearance: none; cursor: pointer; border-radius: 7px; padding: 6px 12px;
    min-height: 32px; touch-action: manipulation;
    font: inherit; font-size: 12.5px; font-weight: 600; line-height: 1.4;
    border: 1px solid var(--line-hi); background: rgba(9, 17, 28, .36); color: var(--text);
    backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    transition: border-color .15s ease, color .15s ease, background .15s ease, transform .08s ease;
  }
  button:hover:not(:disabled) { border-color: var(--red); color: #ffb3b1; background: rgba(22, 32, 46, .72); }
  button.start:hover:not(:disabled) { border-color: var(--green); color: #9ff0cd; }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  button:disabled { cursor: default; opacity: .45; }
  button[data-confirm="1"] {
    border-color: var(--red); background: rgba(228, 96, 94, .14); color: #f2a3a2;
  }
  button[data-confirm="1"]:hover:not(:disabled) { background: rgba(228, 96, 94, .22); }
  button[data-busy="1"] { color: transparent; position: relative; }
  button[data-busy="1"]::after {
    content: ""; position: absolute; inset: 0; margin: auto; width: 12px; height: 12px;
    border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%;
    animation: spin .7s linear infinite;
  }
  button.group-act { padding: 5px 11px; min-height: 30px; font-size: 12px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .empty { color: var(--muted); font-size: 13px; margin-top: 22px; }
  footer { margin-top: 26px; color: #a7b7ca; font-size: 11.5px; text-shadow: 0 1px 12px rgba(0, 0, 0, .85); }
  @media (max-width: 520px) {
    .wrap { padding: 12px 12px 16px; }
    header { display: block; }
    /* 手机上省掉副标题和脚注，把高度留给列表 */
    header .hint { display: none; }
    footer { display: none; }
    .state { display: none; }
    .mem { margin-left: auto; }
    .mem-bar { display: none; }
    .group { margin-top: 12px; }
    .group-head { gap: 8px; }
    .group-head .count { font-size: 11.5px; }
    li { padding: 8px 11px; }
    button { min-height: 40px; padding: 8px 14px; font-size: 13px; }
    button.group-act { min-height: 32px; padding: 5px 10px; font-size: 12px; }
    .port { font-size: 10.5px; padding: 2px 4px; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <img src="/branding/logo192.png" alt="">
      <h1>电源面板</h1>
    </div>
    <span class="hint">容器与宿主机服务都在这里</span>
  </header>
  <div class="banner" id="banner" role="status" aria-live="polite" hidden></div>
  <div id="body"><p class="empty">加载中…</p></div>
  <footer>单容器停止、整组启停需连点两次确认（4 秒后自动取消）；刷新间隔 10 秒，内存为 Docker 即时统计。</footer>
</div>
<script>
const body = document.getElementById('body');
const banner = document.getElementById('banner');

const LABELS = {
  running: '运行中', exited: '已停止', created: '未启动', paused: '已暂停',
  restarting: '重启中', dead: '异常', removed: '已移除', unknown: '未知'
};

function showBanner(text) {
  banner.textContent = text;
  banner.hidden = !text;
}

// 防误触：停止类操作要点两次；确认期间暂停自动刷新，避免按钮被重绘
let armed = null;
let loading = false;
let touching = false;

function disarm() {
  if (!armed) return;
  clearTimeout(armed.timer);
  delete armed.btn.dataset.confirm;
  armed.btn.textContent = armed.label;
  armed = null;
  showBanner('');
}

function requestConfirm(btn, text, run) {
  if (armed && armed.btn === btn) {
    disarm();
    run();
    return;
  }
  disarm();
  const label = btn.textContent;
  btn.dataset.confirm = '1';
  btn.textContent = text;
  showBanner('再点一次「' + text + '」才会执行，4 秒后自动取消');
  const timer = setTimeout(() => {
    if (armed && armed.btn === btn) disarm();
  }, 4000);
  armed = { btn, label, timer };
}

function dotClass(state) {
  if (state === 'running') return 'dot on';
  if (state === 'restarting' || state === 'paused') return 'dot warn';
  return 'dot';
}

function fmtBytes(bytes) {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return value.toFixed(index < 2 || value >= 100 ? 0 : 1) + ' ' + units[index];
}

function memoryNode(item, peak) {
  const wrap = document.createElement('span');
  wrap.className = 'mem';
  if (!item.mem || !item.mem.used) return wrap;

  const text = document.createElement('span');
  text.textContent = fmtBytes(item.mem.used);
  const bar = document.createElement('span');
  bar.className = 'mem-bar';
  bar.setAttribute('aria-hidden', 'true');
  const fill = document.createElement('i');
  fill.style.width = Math.max(4, Math.round((item.mem.used / peak) * 100)) + '%';
  bar.appendChild(fill);

  wrap.title = '内存占用 ' + fmtBytes(item.mem.used) +
               (item.mem.limit ? '（limit ' + fmtBytes(item.mem.limit) + '）' : '');
  wrap.append(text, bar);
  return wrap;
}

// 分组折叠状态记在 localStorage：默认全部收起，只留分组头和「已停」提示
const OPEN_KEY = 'power-open-groups';

function openGroups() {
  try {
    const raw = localStorage.getItem(OPEN_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch (err) {
    return new Set();
  }
}

function saveOpenGroups(set) {
  try {
    localStorage.setItem(OPEN_KEY, JSON.stringify([...set]));
  } catch (err) {}
}

function toggleGroup(section, name) {
  const next = section.dataset.open !== '1';
  section.dataset.open = next ? '1' : '0';
  const head = section.querySelector('.group-toggle');
  if (head) head.setAttribute('aria-expanded', next ? 'true' : 'false');
  const set = openGroups();
  if (next) set.add(name); else set.delete(name);
  saveOpenGroups(set);
}

function portNode(c) {
  if (!c.ports || !c.ports.length) return null;
  const span = document.createElement('span');
  span.className = 'port';
  const shown = c.ports.slice(0, 3).map((p) => ':' + p).join(' ');
  span.textContent = shown + (c.ports.length > 3 ? ' +' + (c.ports.length - 3) : '');
  span.title = '宿主机端口 ' + c.ports.join(' / ');
  return span;
}

function render(groups) {
  body.innerHTML = '';
  if (!groups.length) {
    body.innerHTML = '<p class="empty">没有可显示的容器</p>';
    return;
  }

  const open = openGroups();

  for (const g of groups) {
    const section = document.createElement('section');
    section.className = 'group';
    section.dataset.open = open.has(g.name) ? '1' : '0';
    const peak = Math.max(1, ...g.containers.map((c) => (c.mem && c.mem.used) || 0));

    const stopped = g.containers
      .filter((c) => c.state !== 'running')
      .map((c) => c.name.replace(/\.service$/, ''));

    const head = document.createElement('div');
    head.className = 'group-head';

    const toggle = document.createElement('div');
    toggle.className = 'group-toggle';
    toggle.setAttribute('role', 'button');
    toggle.setAttribute('tabindex', '0');
    toggle.setAttribute('aria-expanded', open.has(g.name) ? 'true' : 'false');

    const h2 = document.createElement('h2');
    h2.textContent = g.name;
    const count = document.createElement('span');
    count.className = 'count';
    count.innerHTML = '<b>' + g.running + '</b> / ' + g.total + ' 运行' +
      (g.mem_used ? ' · ' + fmtBytes(g.mem_used) : '');

    const stopMode = g.running > 0;
    const bulk = document.createElement('button');
    bulk.className = 'group-act';
    bulk.textContent = stopMode ? '全部关闭' : '全部启动';
    bulk.onclick = () => {
      const run = () => act('group', g.name, stopMode, bulk);
      // 整组操作影响多个容器，启停都要求二次确认
      requestConfirm(bulk, stopMode ? '确认全关' : '确认全启', run);
    };

    const chev = document.createElement('span');
    chev.className = 'chev';
    chev.setAttribute('aria-hidden', 'true');
    toggle.append(h2, count, chev);

    toggle.addEventListener('click', () => toggleGroup(section, g.name));
    toggle.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleGroup(section, g.name);
      }
    });

    head.append(toggle, bulk);

    // 折叠状态下直接列出没在跑的，不用展开也能看到异常
    const issues = document.createElement('p');
    issues.className = 'issues';
    if (stopped.length) {
      issues.textContent = '已停：' + stopped.slice(0, 5).join('、') +
        (stopped.length > 5 ? ' 等 ' + stopped.length + ' 个' : '');
    } else {
      issues.hidden = true;
    }

    const list = document.createElement('ul');
    for (const c of g.containers) {
      const li = document.createElement('li');
      const dot = document.createElement('span');
      dot.className = dotClass(c.state);
      const name = document.createElement('span');
      name.className = 'cname';
      name.textContent = c.name.replace(/\.service$/, '');
      const state = document.createElement('span');
      state.className = 'state';
      state.textContent = LABELS[c.state] || c.state;

      li.append(dot, name);
      const port = portNode(c);
      if (port) li.appendChild(port);
      li.append(state, memoryNode(c, peak));

      const btn = document.createElement('button');
      const stopMode = c.state === 'running';
      btn.className = stopMode ? '' : 'start';
      btn.textContent = stopMode ? '关闭' : '启动';
      const scope = c.kind === 'unit' ? 'host' : 'container';
      btn.onclick = () => {
        const run = () => act(scope, c.name, stopMode, btn);
        if (stopMode) requestConfirm(btn, '确认关闭', run); else run();
      };

      li.appendChild(btn);
      list.appendChild(li);
    }

    section.append(head, issues, list);
    body.appendChild(section);
  }
}

async function load(force = false) {
  if (armed || (!force && (loading || touching))) return;
  loading = true;
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    render(data.groups);
  } catch (err) {
    body.innerHTML = '<p class="empty">读不到容器状态</p>';
    showBanner('无法连接本机 Docker：' + err.message);
  } finally {
    loading = false;
  }
}

async function act(scope, name, stopMode, btn) {
  if (btn) { btn.dataset.busy = '1'; btn.disabled = true; }
  showBanner('');
  const action = stopMode ? 'stop' : 'start';
  try {
    const url = '/api/action?scope=' + encodeURIComponent(scope) +
                '&name=' + encodeURIComponent(name) + '&action=' + action;
    const res = await fetch(url, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok && res.status !== 207) throw new Error(data.detail || ('HTTP ' + res.status));
    if (data.failed && data.failed.length) {
      showBanner((stopMode ? '关闭' : '启动') + '有 ' + data.failed.length + ' 个没成功：' + data.failed.join('、'));
    }
  } catch (err) {
    showBanner('操作失败：' + err.message);
  } finally {
    await load(true);
  }
}

// 手指按下时不重绘列表，避免按钮在指尖下被替换
let touchTimer = null;
document.addEventListener('pointerdown', () => {
  touching = true;
  clearTimeout(touchTimer);
  touchTimer = setTimeout(() => { touching = false; }, 1500);
}, true);
document.addEventListener('pointerup', () => {
  touching = false;
  clearTimeout(touchTimer);
}, true);
document.addEventListener('pointercancel', () => {
  touching = false;
  clearTimeout(touchTimer);
}, true);

load();
setInterval(() => { if (!document.hidden) load(); }, 10000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
