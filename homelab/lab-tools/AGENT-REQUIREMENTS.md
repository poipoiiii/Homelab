# Agent 能力需求清单（v2：可写 + 下载）

> 状态：P0/P1 下载闭环已实现（MeTube 下载 + 容器启停/重启 + 队列查询/取消 + 余量预检）；下载完成通知支持企业微信自建应用（发给个人）和群机器人两种通道；Pinchflat 只读待做。
> 目标：在只读工具（lab-tools）基础上，增加“启停容器”和“按 URL 下载视频”两类动作，并接入 LibreChat。

## 1. 当前容器盘点

| 容器 | 镜像 | 端口 | Dozzle 分组 | 状态 | Agent 相关 |
| --- | --- | --- | --- | --- | --- |
| `librechat` | librechat-dev | 3080 | AI 助手 | running | 聊天入口，不建议由 Agent 停 |
| `librechat-mongo` | mongo:7 | 27017 | AI 助手 | running | 存聊天记录，保护 |
| `lab-tools` | 自建 | 8765 | AI 助手 | running | Agent 本体，保护 |
| `lab-tools-docker-proxy` | docker-socket-proxy | 2375 | AI 助手 | running | 权限边界，保护 |
| `homarr` | homarr | 7575 | 入口与运维 | running | 面板，保护 |
| `dozzle` | dozzle | 8888 | 入口与运维 | running | 日志面板，保护 |
| `jellyfin` | jellyfin | 8096 | 影音 | exited | 可启停 |
| `pinchflat` | pinchflat | 8945 | 影音 | running | YouTube 订阅下载，只读查询 |
| `traccar` | traccar | 5055/8085 | 家庭服务 | running | 可启停 |
| `rong-ledger` | bill-ai | 8091 | 家庭服务 | running | 记账，可重启但不要随便停 |
| `cloudreve` | cloudreve | 8080 | 家庭服务 | exited | 可启停 |
| `frpc` | frpc | — | 入口与运维 | exited | 公网入口，禁止 stop |

另有非容器服务：1Panel（25081）、MCSManager（23333）、Tailscale（节点 `home`）。Agent 不直接操作这些。

## 2. 能力需求

### P0：容器启停

- `stop_service(name)` / `start_service(name)` / `restart_service(name)`
- 名称必须命中真实容器，支持模糊匹配但歧义时必须反问
- 两段式确认：
  1. 第一次调用只返回 `{action, service, command, confirm_token}`，不执行
  2. 用户确认后带 `confirm_token` 再调用，token 2 分钟过期、一次性
- 保护名单（禁止 stop，允许 restart 但需二次确认）：
  `lab-tools`、`lab-tools-docker-proxy`、`librechat`、`librechat-mongo`、`homarr`、`dozzle`、`frpc`
- 每次执行写审计日志：时间、动作、目标、结果、确认 token

### P0：按 URL 下载

示例意图：

> 帮我下载 `https://www.bilibili.com/bangumi/play/ss28544` 到 D:\game_video_

- 工具：`download_media(url, target, quality="best")`
- `target` 只接受枚举，不允许任意路径：
  - `game_video` → `/mnt/d/game_video_`
  - `yt_video` → `/mnt/d/yt_video_`
  - `movies` → `/mnt/d/mv__`
- 实际执行交给 **MeTube**（yt-dlp 的 Web UI，支持 B 站等站点）：
  - `POST http://metube:8081/add`，body `{"url": "...", "folder": "game_video"}`
  - MeTube 挂载多个目录到 `/downloads/<target>`
- 返回 `{queued: true, target, url, hint}`，不阻塞等待下载完成
- 提交后由 `labtools/watcher.py` 轮询 MeTube `/history`，完成或失败时推送企业微信消息
  - 通用发送组件在 `labtools/wecom.py`，被 `labtools/notify.py` 按环境变量装配
  - 首选自建应用：`WECOM_CORP_ID` + `WECOM_SECRET` + `WECOM_AGENT_ID`，默认 `WECOM_TOUSER=@all`（应用可见范围内全部成员）
  - 备选群机器人：`WECOM_WEBHOOK`；两者都配时优先自建应用；都未配置时只写日志
  - 番剧/播放列表会被 MeTube 拆成每集一个 URL，watcher 按「落盘目录 + 提交时间」关联；最后一条 done 静置 `DOWNLOAD_SETTLE_SECONDS`（默认 60 秒）后汇总成一条通知
  - 企业微信后台「接收消息」的 Token / EncodingAESKey / 回调 URL 与发消息无关，发消息只需要 CorpID、应用 Secret、AgentId
  - 任务状态落在 `/audit/downloads.json`，重启不丢；已完成记录保留 7 天

### P1：下载状态与取消（已实现）

- `list_downloads(limit)`：本地 watcher 快照 + MeTube `/history` 队列，返回进行中、完成和失败原因
- `cancel_download(url | job_id)`：走 MeTube `POST /delete`（`where=queue`、`delete_files=false`），只移除队列项，不删已落盘文件；成功后本地任务标记为 `cancelled`
- 提交前用 `statvfs` 检查目标媒体目录余量（`MEDIA_MIN_FREE_GB`，默认 20 GB），低于阈值直接拒绝；同一链接已在队列时返回 `duplicate`，不重复提交
- MeTube 接口不可用时 `list_downloads` 返回 `metube: unreachable`，本地任务仍然可查，不影响提交下载

### P1：Pinchflat 只读

- `list_pinchflat_sources()`：列出订阅源和最近下载
- Pinchflat 定位是 YouTube 频道/播放列表订阅，**不适合单条任意 URL**
- 保留它做订阅归档，写入 `/mnt/d/yt_video_`；一次性下载走 MeTube

## 3. 为什么不是 Pinchflat 直接下载

- Pinchflat 的模型是“订阅源 + 定时检查”，不是“贴一个链接下一次”
- 官方定位是 YouTube 内容归档，虽然底层是 yt-dlp，但 UI/数据模型围绕频道和播放列表
- 已实测：Pinchflat 容器内的 yt-dlp 能解析你给的 B 站番剧链接，列出 12 集、每集约 23 分钟。所以底层能力有，但缺少“单次任务”的入口
- 结论：**Pinchflat 管订阅，MeTube 管一次性下载**，两者都写文件，Jellyfin 负责播放

## 4. 权限与安全改造

### 4.1 Docker 代理

实现采用**两个代理**，避免“为了启停而放开 `/containers` 全部 POST”：

**读代理 `lab-tools-docker-proxy`**

```yaml
environment:
  - CONTAINERS=1
  - IMAGES=1
  - INFO=1
  - VERSION=1
  - SYSTEM=1
  - POST=0
  - EXEC=0
  - VOLUMES=0
  - NETWORKS=0
```

**写代理 `lab-tools-docker-proxy-write`**

```yaml
environment:
  - CONTAINERS=0
  - ALLOW_START=1
  - ALLOW_STOP=1
  - POST=1
  - EXEC=0
  - VOLUMES=0
  - NETWORKS=0
```

- 写代理必须 `POST=1`，否则代理的 `deny unless METH_GET || POST` 会先拒绝所有 POST
- `CONTAINERS=0` 保证写代理不能查询、创建容器；只剩 `/containers/{id}/start|stop` 两条路径
- 不启用 `ALLOW_RESTARTS`，避免 `kill` 也被放行；重启由 stop + start 组合实现
- 已实测：读代理 `POST .../stop` → 403；写代理 `GET /containers/json` → 403、`POST /containers/create` → 403、`POST .../kill` → 403、`POST .../start` → 放行

### 4.2 路径白名单

下载目标不能由模型自由拼路径，只接受三个枚举值；容器内映射固定：

```
/downloads/game_video -> /mnt/d/game_video_
/downloads/yt_video   -> /mnt/d/yt_video_
/downloads/movies     -> /mnt/d/mv__
```

### 4.3 审计

新增命名卷 `lab_tools_audit`，挂到 `/audit`，每次动作追加一行 JSON：

```json
{"ts":"2026-10-22T11:00:00+08:00","action":"stop","target":"jellyfin","result":"ok","confirm":"a1b2c3"}
```

## 5. 新增服务：MeTube

```yaml
services:
  metube:
    image: ghcr.io/alexta69/metube
    container_name: metube
    restart: unless-stopped
    ports:
      - "127.0.0.1:8081:8081"
    environment:
      - TZ=Asia/Shanghai
      - PUID=1000
      - PGID=1000
      - CUSTOM_DIRS=true
      - OUTPUT_TEMPLATE=%(title)s [%(id)s].%(ext)s
    volumes:
      - /mnt/d/game_video_:/downloads/game_video
      - /mnt/d/yt_video_:/downloads/yt_video
      - /mnt/d/mv__:/downloads/movies
      - metube_state:/downloads/.metube

volumes:
  metube_state:
```

- 端口 8081 原 IT-Tools 已下线，当前空闲
- B 站番剧可能需要登录/大会员：后续挂载 `cookies.txt` 或设置 `YTDL_OPTIONS`
- 磁盘：`D:` 剩余约 898 GB，够用

## 6. 验收标准

1. 说“关闭 Jellyfin”，Agent 回复将要执行 `docker stop jellyfin` 并给确认 token；确认后才停，Dozzle 里状态变化，审计日志有记录。
2. 说“关闭 frpc”，Agent 拒绝，并说明它是公网入口保护服务。
3. 说“下载 <B 站链接> 到 game_video”，MeTube 队列出现任务，完成后文件落在 `D:\game_video_`，Jellyfin 能扫描到。
4. 说“下载到 D:\windows\system32”，Agent 拒绝，因为不在白名单。
5. 所有动作都能在 Dozzle 的 `AI 助手` 分组里看到对应日志。

## 7. 风险

- 模型把“关闭”选成“重启”：靠确认 token 和动作二次展示兜底
- 提示注入：URL、日志、文件名都当数据，不当指令
- B 站反爬/风控：yt-dlp 需要持续更新，可能需要 cookies
- 下载占满磁盘：提交前检查目标目录剩余空间，低于阈值拒绝
- 大文件转码/合并：MeTube 容器需要足够临时空间，建议 `TEMP_DIR` 指到同一磁盘
