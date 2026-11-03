# motion-studio

本地的"数据播报视频"渲染服务：把一组标题 + 章节 + 条目，渲染成带配乐、颗粒、版式变化的 1080p 成片，供 HomelabApp 手动提交任务后轮询、播放、下载。

渲染引擎换成 [HyperFrames](https://github.com/heygen-com/hyperframes) 0.9：服务端把场景数据生成一份 HTML + GSAP 合成，交给无头 Chrome 逐帧抓取，再由 ffmpeg 编码。**HTTP 接口、任务状态和客户端协议保持不变**，安卓端不需要改。

## 能力

- 两种模板：`ledger`（章节 + 条目自动分页）与 `scenes`（封面/人像/章节/列表/数字/引用/结尾自由组合）
- 人像页：改成排版式概念页（大字 + 圆环 + 关键词），按七宗罪/通用人像切换字与主色，左右交替
- 三套主题：`ink` 墨、`paper` 纸、`signal` 信
- 场景切换：统一用底色闪入遮住硬切，入场动画按场景类型区分；不再有 canvas 时代的六种图形转场
- 默认音轨：程序合成的鼓组、低频与铺底和弦，加转场 whoosh / impact / tick / riser；成片后由 ffmpeg 合入，可用 `audio:false` 关闭
- 1080p / 720p，30 / 24 fps，H.264 + faststart（手机可边下边播）
- 数值核验：成片时长、体积、封面提取结果写进任务的 `checks`
- 异步队列、进度、取消、删除、14 天自动清理

## 部署（WSL 内）

源文件在 Windows 仓库 `D:\ubuntu_\homelab\motion-studio`，WSL 不会自动同步，需要复制进 `~/homelab`：

```bash
wsl -d UbuntuD
cp -r /mnt/d/ubuntu_/homelab/motion-studio ~/homelab/
cd ~/homelab/motion-studio
cp .env.example .env      # 填 MOTION_TOKEN
docker compose up -d --build
docker compose logs -f
```

镜像基于 `node:22-bookworm-slim`，构建时会：

- 把 Debian 源换成阿里云镜像（国内构建更快；海外部署可在 Dockerfile 里删掉这行）
- 安装 `ffmpeg`、`fonts-noto-cjk` 和 Chrome 运行库
- 从 npmmirror 下载 `chrome-headless-shell` 到镜像内的 Puppeteer 缓存
- 把浏览器路径写进 `HYPERFRAMES_BROWSER_PATH`

首次构建需要下载约 120 MB 的 Chrome，时间取决于网络。访问 `http://127.0.0.1:8095/healthz`，预期 `"renderer": "hyperframes"`、`"ffmpeg": true`、`"cjk_fonts": true`。

- 端口：**8095**（8090 Beszel / 8091 账单 / 8092 电源 / 8093 宿主代理 / 8094 修图网关）
- 访问：本机 `http://127.0.0.1:8095`，手机用 tailnet 地址 `http://100.x.x.x:8095`；端口对 tailnet 暴露，**必须设置 `MOTION_TOKEN`**，否则同网段任何人都能提交渲染任务
- 数据：命名卷 `motion_studio_data` → 容器 `/data/jobs/<id>/`（`job.json` / `out.mp4` / `poster.png`）
- 鉴权：`.env` 里的 `MOTION_TOKEN`；留空则不鉴权

## 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `PORT` | `8095` | 容器内监听端口 |
| `DATA_DIR` | `/data` | 任务与成片目录 |
| `MOTION_TOKEN` | 空 | Bearer Token；空 = 不鉴权 |
| `RENDER_CONCURRENCY` | `1` | 同时渲染任务数，不建议超过 1 |
| `HYPERFRAMES_WORKERS` | `3` | 单个任务内部并行抓帧的 Chrome worker 数；0 = 自动 |
| `HYPERFRAMES_QUALITY` | `standard` | 编码质量：`draft` / `standard` / `high` |
| `MAX_QUEUE` | `8` | 排队上限，超出返回 429 |
| `KEEP_DAYS` | `14` | 已结束任务保留天数 |
| `MAX_JOBS` | `200` | 历史任务总数上限 |
| `FONT_SANS` / `FONT_SERIF` / `FONT_MONO` | 未使用 | 字体已改为镜像内 Noto CJK，不再读这三个变量 |

## 验证

容器内直接跑一条 720p 短片（不经过 HTTP）：

```bash
docker compose exec motion-studio node scripts/smoke.js
```

接口全链路：

```bash
curl -s localhost:8095/healthz
curl -s localhost:8095/api/v1/meta
curl -s -X POST localhost:8095/api/v1/jobs \
  -H "Authorization: Bearer $MOTION_TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"测试片","kicker":"DEMO","sections":[{"heading":"第一章","items":[{"label":"条目","value":"1"}]}]}'
curl -s localhost:8095/api/v1/jobs/<id> -H "Authorization: Bearer $MOTION_TOKEN"
```

安卓端：抽屉「视频」页提交任务 → 任务卡显示进度 → 播放（系统播放器）/ 下载到相册。客户端无感，接口与字段不变。

## 性能与限制

- 本机（i5-11500 / WSL 8 线程）实测 30 秒 1080p30、无音轨：HyperFrames 约 29~37 秒（3 个 worker），旧的 canvas 渲染器约 39 秒。
- 720p 约减半；有音轨时音轨合成与封装额外增加 1~3 秒。
- 单任务时长上限 240 秒；条目总数 120；章节 12；场景 24。
- 任务并发 1，但单任务会同时开最多 3 个 Chrome；和 Jellyfin / Minecraft 同时跑时可以把 `HYPERFRAMES_WORKERS` 降到 1~2。
- 配乐仍是程序合成的，风格偏暗色电子；需要换风格可以改 `src/audio.js` 里的和弦与鼓组。

## 排错

| 现象 | 原因 / 处理 |
| --- | --- |
| `/healthz` 里 `cjk_fonts: false` | 镜像没装 `fonts-noto-cjk`，中文会变方块，重 build |
| 任务失败 `chrome_not_found` 或启动即退出 | 镜像里没有 chrome-headless-shell；检查构建日志里的 `npx puppeteer browsers install` |
| Chrome 启动报缺 `.so` | 重新 build，确认 apt 层安装了 `libnss3`、`libgbm1`、`libasound2` 等运行库 |
| 任务卡在"排队中" | 前面有任务在渲染；`docker compose logs -f` 看进度 |
| 任务失败 `encode_failed` | 磁盘满或 ffmpeg 被杀；检查 `docker system df` |
| 画面中文字体不对 | 确认容器内 `fc-list :lang=zh` 有 Noto CJK；不要再把字体族写回 `Noto Sans SC` 之类需要联网拉取的名称 |
| 请求 401 | `.env` 里配了 Token，请求没带或带错 |
| 回放无法拖动 | 服务端已支持 Range；确认中间没有反向代理剥离 `Range` |
| 渲染时内存/CPU 飙高 | 降低 `HYPERFRAMES_WORKERS`，或把 `HYPERFRAMES_QUALITY` 调成 `draft` |

## 目录

```text
motion-studio/
├─ docker-compose.yml
├─ Dockerfile
├─ .env.example
├─ API.md                 接口与请求规格（未变）
├─ package.json
├─ src/
│  ├─ index.js            HTTP 路由、鉴权、Range 下载
│  ├─ jobs.js             内存队列 + job.json 持久化
│  ├─ render.js           HyperFrames 渲染、ffmpeg 合音轨/抽封面
│  ├─ html.js             场景数据 → HTML + GSAP 合成
│  ├─ theme.js            主题、画布尺寸、确定性随机
│  ├─ plan.js             场景时间线与自动分页
│  ├─ validate.js         请求校验与限制
│  └─ audio.js            程序化配乐与音效
└─ scripts/smoke.js       容器内冒烟渲染
```

改完 compose 后记得在仓库根目录重新生成端口表：

```powershell
pwsh -NoProfile -File tools/gen-port-table.ps1
```
