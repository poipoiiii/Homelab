"""电源面板：列出所有容器，可按容器或按组一键 stop/start。

只做两件事：查状态（读代理）、start/stop（写代理）。不接 EXEC，不碰数据卷。
"""

import os

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

# 宿主机 systemd 服务单独成组，启动顺序：daemon 先、web 后
HOST_GROUP = "宿主机服务"
UNIT_ORDER = {"mcsm-daemon.service": 10, "mcsm-web.service": 20, "1panel.service": 30}
UNIT_STATE = {"active": "running", "activating": "restarting", "failed": "dead", "inactive": "exited"}

app = FastAPI(title="power", docs_url=None, redoc_url=None)
BRANDING_DIR = os.getenv("BRANDING_DIR", "/branding")
if os.path.isdir(BRANDING_DIR):
    app.mount("/branding", StaticFiles(directory=BRANDING_DIR), name="branding")


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
        result.append({
            "name": name,
            "state": item.get("State", "unknown"),
            "group": labels.get("dev.dozzle.group") or GROUP_FALLBACK.get(name) or "未分组",
            "kind": "container",
        })

    result.sort(key=lambda c: (START_ORDER.get(c["name"], 500), c["name"]))
    return result


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
        items = _containers()
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
    --bg: #0d0f12;
    --surface: #15181d;
    --surface-hi: #1b1f26;
    --line: #242932;
    --line-hi: #333a45;
    --text: #e7e9ee;
    --muted: #8b93a1;
    --green: #3ecf8e;
    --red: #e4605e;
    --focus: #5aa9ff;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--text); }
  body {
    font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  ::selection { background: #2b4d70; color: #fff; }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-thumb { background: #2a3038; border-radius: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }

  .wrap { max-width: 720px; margin: 0 auto; padding: 22px 16px 28px; }
  header { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; }
  .brand { display: flex; align-items: center; gap: 8px; }
  .brand img { width: 24px; height: 24px; border-radius: 7px; object-fit: cover; display: block; }
  h1 { margin: 0; font-size: 19px; font-weight: 650; letter-spacing: -0.01em; }
  header .hint { color: var(--muted); font-size: 12.5px; }

  .banner {
    margin: 16px 0 0; padding: 10px 13px; border-radius: 9px;
    border: 1px solid #5a2c2c; background: #1e1414; color: #f0b4b3; font-size: 13px;
  }
  .banner[hidden] { display: none; }

  .group { margin-top: 18px; }
  .group-head {
    display: flex; align-items: center; gap: 10px; padding: 0 2px 8px;
  }
  .group-head h2 { margin: 0; font-size: 12.5px; font-weight: 600; letter-spacing: .04em; color: var(--muted); }
  .group-head .count { margin-left: auto; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .group-head .count b { color: var(--text); font-weight: 600; }

  ul { list-style: none; margin: 0; padding: 0; background: var(--surface);
       border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  li { display: flex; align-items: center; gap: 10px; padding: 7px 13px; }
  li + li { border-top: 1px solid var(--line); }
  li:hover { background: var(--surface-hi); }

  .dot { width: 7px; height: 7px; border-radius: 50%; flex: none; background: #4a5260; }
  .dot.on { background: var(--green); box-shadow: 0 0 0 3px rgba(62,207,142,.12); }
  .dot.warn { background: #c9a227; }
  .cname { font-size: 13.5px; font-weight: 500; }
  .state { margin-left: auto; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }

  button {
    appearance: none; cursor: pointer; border-radius: 7px; padding: 4px 11px;
    font: inherit; font-size: 12.5px; font-weight: 600; line-height: 1.4;
    border: 1px solid var(--line-hi); background: transparent; color: var(--text);
    transition: border-color .15s ease, color .15s ease, background .15s ease, transform .08s ease;
  }
  button:hover:not(:disabled) { border-color: var(--red); color: #f2a3a2; }
  button.start:hover:not(:disabled) { border-color: var(--green); color: #9fe6c6; }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  button:disabled { cursor: default; opacity: .45; }
  button[data-busy="1"] { color: transparent; position: relative; }
  button[data-busy="1"]::after {
    content: ""; position: absolute; inset: 0; margin: auto; width: 12px; height: 12px;
    border: 2px solid currentColor; border-top-color: transparent; border-radius: 50%;
    animation: spin .7s linear infinite;
  }
  button.group-act { padding: 3px 10px; font-size: 12px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .empty { color: var(--muted); font-size: 13px; margin-top: 22px; }
  footer { margin-top: 26px; color: #6b7280; font-size: 11.5px; }
  @media (max-width: 520px) {
    .wrap { padding: 20px 12px 32px; }
    header { display: block; }
    header .hint { display: block; margin-top: 4px; }
    .state { display: none; }
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
  <div class="banner" id="banner" hidden></div>
  <div id="body"><p class="empty">加载中…</p></div>
  <footer>只执行 stop / start，不删容器、不碰数据卷；刷新间隔 10 秒。</footer>
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

function dotClass(state) {
  if (state === 'running') return 'dot on';
  if (state === 'restarting' || state === 'paused') return 'dot warn';
  return 'dot';
}

function render(groups) {
  body.innerHTML = '';
  if (!groups.length) {
    body.innerHTML = '<p class="empty">没有可显示的容器</p>';
    return;
  }

  for (const g of groups) {
    const section = document.createElement('section');
    section.className = 'group';

    const head = document.createElement('div');
    head.className = 'group-head';
    const h2 = document.createElement('h2');
    h2.textContent = g.name;
    const count = document.createElement('span');
    count.className = 'count';
    count.innerHTML = '<b>' + g.running + '</b> / ' + g.total + ' 运行';
    head.append(h2, count);

    const stopMode = g.running > 0;
    const bulk = document.createElement('button');
    bulk.className = 'group-act';
    bulk.textContent = stopMode ? '全部关闭' : '全部启动';
    bulk.onclick = () => act('group', g.name, stopMode, bulk);
    head.appendChild(bulk);

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
      li.append(dot, name, state);

      const btn = document.createElement('button');
      const stopMode = c.state === 'running';
      btn.className = stopMode ? '' : 'start';
      btn.textContent = stopMode ? '关闭' : '启动';
      const scope = c.kind === 'unit' ? 'host' : 'container';
      btn.onclick = () => act(scope, c.name, stopMode, btn);

      li.appendChild(btn);
      list.appendChild(li);
    }

    section.append(head, list);
    body.appendChild(section);
  }
}

async function load() {
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    render(data.groups);
  } catch (err) {
    body.innerHTML = '<p class="empty">读不到容器状态</p>';
    showBanner('无法连接本机 Docker：' + err.message);
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
    await load();
  }
}

load();
setInterval(() => { if (!document.hidden) load(); }, 10000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
