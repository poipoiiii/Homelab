# motion-studio

本地的"数据播报视频"渲染服务：把一组标题 + 章节 + 条目，渲染成带转场、颗粒、印章的 1080p 成片，供 HomelabApp 手动提交任务后轮询、播放、下载。

实现思路沿用 `kiro-motion-studio` 的做法：**不依赖 After Effects**，用 `@napi-rs/canvas` 逐帧绘制，原始 RGBA 帧直接管道给 ffmpeg 编码。整条链路在容器内完成，不外传任何数据。

## 能力

- 两种模板：`ledger`（章节 + 条目自动分页）与 `scenes`（封面/人像/章节/列表/数字/引用/结尾自由组合）
- 人像页：程序化古典胸像 + 罪名符号（王冠/蛇/火焰/时钟/金币/餐具/玫瑰），左右交替排版
- 三套主题：`ink` 墨、`paper` 纸、`signal` 信
- 六种转场：wipe / slide / blinds / zoom / flash / split（随场景轮换，切点落在 120 BPM 拍点）
- 默认音轨：程序合成的鼓组、低频与铺底和弦，加转场 whoosh / impact / tick / riser，可用 `audio:false` 关闭
- 1080p / 720p，30 / 24 fps，H.264 + faststart（手机可边下边播）
- 数值核验：文本溢出、画面过空、抽样墨量，结果写进任务的 `checks`
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

访问 `http://127.0.0.1:8095/healthz`，预期 `"ffmpeg": true`、`"cjk_fonts": true`。

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
| `MAX_QUEUE` | `8` | 排队上限，超出返回 429 |
| `KEEP_DAYS` | `14` | 已结束任务保留天数 |
| `MAX_JOBS` | `200` | 历史任务总数上限 |
| `FONT_SANS` / `FONT_SERIF` / `FONT_MONO` | Noto CJK / DejaVu | 字体族覆盖 |

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

安卓端：抽屉「视频」页提交任务 → 任务卡显示进度 → 播放（系统播放器）/ 下载到相册。

## 性能与限制

- 本机（i5-11500 / WSL 8 线程）1080p30 约 40~50 ms/帧；65 秒片约 85~90 秒，720p 约减半。
- 音轨在渲染前用 Node 合成（65 秒约 1~2 秒），不依赖外部音频素材。
- 单任务时长上限 240 秒；条目总数 120；章节 12；场景 24。
- 渲染并发 1，避免和 Jellyfin / Minecraft 抢 CPU；队列满时返回 `queue_full`。
- 配乐是程序合成的，风格偏暗色电子；需要换风格可以改 `src/audio.js` 里的和弦与鼓组。

## 排错

| 现象 | 原因 / 处理 |
| --- | --- |
| `/healthz` 里 `cjk_fonts: false` | 镜像没装 `fonts-noto-cjk`，中文会变方块，重 build |
| `ffmpeg: false` 或启动即退出 | 镜像缺 ffmpeg，检查 Dockerfile 的 apt 层 |
| 任务卡在"排队中" | 前面有任务在渲染；`docker compose logs -f` 看进度 |
| 任务失败 `encode_failed` | 磁盘满或 ffmpeg 被杀；检查 `docker system df` |
| 画面中文字体不对 | 确认 `FONT_SANS` 指向容器内存在的字体（`fc-list :lang=zh`） |
| 请求 401 | `.env` 里配了 Token，请求没带或带错 |
| 回放无法拖动 | 服务端已支持 Range；确认中间没有反向代理剥离 `Range` |

## 目录

```text
motion-studio/
├─ docker-compose.yml
├─ Dockerfile
├─ .env.example
├─ API.md                 接口与请求规格
├─ package.json
├─ src/
│  ├─ index.js            HTTP 路由、鉴权、Range 下载
│  ├─ jobs.js             内存队列 + job.json 持久化
│  ├─ render.js           canvas 逐帧 → ffmpeg 管道
│  ├─ plan.js             场景时间线与自动分页
│  ├─ scenes.js           封面/章节/列表/数字/引用/结尾
│  ├─ gfx.js              主题、文本排版、背景、颗粒、转场
│  └─ validate.js         请求校验与限制
└─ scripts/smoke.js       容器内冒烟渲染
```

改完 compose 后记得在仓库根目录重新生成端口表：

```powershell
pwsh -NoProfile -File tools/gen-port-table.ps1
```
