# motion-studio API

基础地址：`http://127.0.0.1:8095`（手机端用 tailnet 地址或 SSH 隧道）。

> 2.0 起渲染引擎换成 HyperFrames，**接口、字段和任务状态保持不变**，客户端无需改动；`/healthz` 和 `/api/v1/meta` 额外返回 `renderer: "hyperframes"`，可忽略。

所有接口返回 JSON（视频/封面除外）。错误统一为：

```json
{ "error": { "code": "bad_field", "message": "标题最多 60 个字（当前 72）" } }
```

## 鉴权

- 服务端设置了 `MOTION_TOKEN` 时，`/api/v1/*` 与视频/封面都要求 Token。
- 三种传法任选：`Authorization: Bearer <token>`、`X-Api-Token: <token>`、`?token=<token>`。
- 视频/封面建议用 `?token=`，因为系统播放器 / Coil 加不上自定义请求头。
- `/healthz` 不鉴权。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 存活、ffmpeg、字体、队列状态 |
| GET | `/api/v1/meta` | 模板、主题、分辨率、限制 |
| POST | `/api/v1/jobs` | 提交渲染任务，返回 202 |
| GET | `/api/v1/jobs?status=all&limit=20&before=<ts>` | 任务列表（新的在前） |
| GET | `/api/v1/jobs/{id}` | 单个任务状态与进度 |
| POST | `/api/v1/jobs/{id}/cancel` | 取消排队/运行中的任务 |
| DELETE | `/api/v1/jobs/{id}` | 删除已结束的任务与文件 |
| GET | `/api/v1/jobs/{id}/video` | 成片 MP4，支持 Range |
| GET | `/api/v1/jobs/{id}/poster` | 封面 PNG |

## 任务对象

```json
{
  "id": "ms_m3k9x2a1f",
  "status": "running",
  "stage": "渲染中",
  "progress": 0.42,
  "frames_done": 302,
  "frames_total": 720,
  "queue_position": 0,
  "created_at": 1793588127000,
  "started_at": 1793588129000,
  "finished_at": null,
  "elapsed_ms": 0,
  "template": "ledger",
  "theme": "ink",
  "title": "24 条记录的完整还原",
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "duration_ms": 48000,
  "bytes": 0,
  "stats": { "sections": 4, "items": 24, "pages": 6 },
  "video_url": null,
  "poster_url": null,
  "checks": null,
  "error": null
}
```

- `status`：`queued` / `running` / `cancel_requested` / `succeeded` / `failed` / `canceled`
- 轮询建议 1~2 秒；页面关闭不影响服务端渲染。
- `video_url` / `poster_url` 是相对路径，客户端自行拼基础地址并附加 `?token=`。
- `checks` 是数值核验结果：`passed` + `warnings`（文本溢出、画面过空等），不影响任务成功状态。

## 声音

- 默认生成音轨：120 BPM 的合成配乐（底鼓/军鼓/踩镲/低频/铺底和弦）+ 音效（转场 whoosh、人像 impact、条目 tick、结尾 riser）。
- 场景切点与默认时长都对齐 **0.5 秒拍点**；自定义 `duration` 会被四舍五入到 0.5 的倍数。
- 不需要声音时传 `"audio": false`，成片为纯视频。

## 提交任务：台账模板

适合"章节 + 条目列表"的数据播报。服务端自动分页（每页 5 条）。

```http
POST /api/v1/jobs
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "template": "ledger",
  "theme": "ink",
  "resolution": "1080p",
  "fps": 30,
  "kicker": "开盒网暴台账",
  "title": "24 条记录的完整还原",
  "subtitle": "从采集到核验，48 秒看完",
  "footer": "数据来源：本地采集台账",
  "ending_title": "数据已归档",
  "sections": [
    {
      "heading": "第一章 · 起点",
      "caption": "2026-10-30",
      "items": [
        { "label": "首条记录", "value": "#001", "note": "采集时间 09:12" },
        { "label": "关联账号", "value": "3 个" }
      ]
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `template` | 否 | `ledger`（默认）或 `scenes` |
| `theme` | 否 | `ink`（默认）/ `paper` / `signal` |
| `resolution` | 否 | `1080p`（默认）/ `720p` |
| `fps` | 否 | `30`（默认）/ `24` |
| `title` | 是 | ≤ 60 字 |
| `kicker` | 否 | 眉标，≤ 40 字 |
| `subtitle` | 否 | ≤ 120 字 |
| `footer` | 否 | ≤ 120 字 |
| `ending_title` / `ending_subtitle` | 否 | 结尾页文案 |
| `date` | 否 | 默认当天，如 `2026.11.02` |
| `verify` | 否 | 默认 true，输出数值核验告警 |
| `sections[].heading` | 是 | ≤ 32 字 |
| `sections[].caption` | 否 | ≤ 80 字 |
| `sections[].items[].label` | 是 | ≤ 40 字 |
| `sections[].items[].value` | 否 | ≤ 20 字，右侧强调 |
| `sections[].items[].note` | 否 | ≤ 80 字 |

限制：章节 ≤ 12，单章条目 ≤ 40，条目总数 ≤ 120，整片 ≤ 240 秒。

## 提交任务：自定义场景

`template: "scenes"` 时按 `scenes` 数组顺序播放，类型如下：

```json
{
  "template": "scenes",
  "theme": "signal",
  "resolution": "1080p",
  "fps": 30,
  "scenes": [
    { "type": "cover", "kicker": "周报", "title": "本周数据", "subtitle": "11 月第 1 周" },
    {
      "type": "portrait",
      "variant": "pride",
      "title": "傲慢",
      "subtitle": "自我被放大，世界被缩小",
      "caption": "SUPERBIA · 但丁《神曲》中的第一层",
      "keywords": ["俯视", "自卑", "失明"]
    },
    { "type": "stat", "items": [
      { "value": "128%", "label": "访问量", "note": "环比 +28%" },
      { "value": "3.4 万", "label": "新增用户" }
    ] },
    { "type": "list", "heading": "来源 Top 3", "items": [
      { "label": "直接访问", "value": "42%" },
      { "label": "搜索", "value": "31%" }
    ] },
    { "type": "quote", "text": "数据不会说谎，但需要被读懂。", "author": "本周总结" },
    { "type": "end", "title": "下周见", "subtitle": "周日 22:00 自动汇总" }
  ]
}
```

| 类型 | 必需字段 | 可选字段 |
| --- | --- | --- |
| `cover` | `title` | `kicker` `subtitle` `footer` `duration` |
| `portrait` | `title` | `variant` `subtitle` `caption` `keywords` `side` `accent` `duration` |
| `section` | `heading` | `caption` `count` `duration` |
| `list` | `items`（≥1） | `heading` `footer` `duration`；超过 6 条自动分页 |
| `stat` | `items`（1~3） | `title` `duration` |
| `quote` | `text` | `author` `duration` |
| `end` | `title` | `subtitle` `footer` `duration` |

`duration` 单位秒，1.5~20，自动取整到 0.5；不传则按内容自动计算。场景数 ≤ 24，整片 ≤ 240 秒。

### portrait 人像页

程序化绘制的古典侧脸胸像 + 罪名符号，不依赖外部图片；左右排版会自动交替，用来做章节封面。

| 字段 | 说明 |
| --- | --- |
| `variant` | `pride` / `envy` / `wrath` / `sloth` / `greed` / `gluttony` / `lust` / `figure`，决定符号与主色；通用概念用 `figure` |
| `title` | 罪名，≤ 32 字 |
| `subtitle` | 一句话解释，≤ 120 字 |
| `caption` | 小字出处/注释，≤ 80 字 |
| `keywords` | 最多 4 个，每个 ≤ 16 字，画成底部编号列表 |
| `side` | `left` / `right`，不传按章节序号交替 |
| `accent` | 自定义主色，`#RRGGBB` |

## curl 示例

```bash
# 提交
curl -s -X POST http://127.0.0.1:8095/api/v1/jobs \
  -H "Authorization: Bearer $MOTION_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"测试片","kicker":"DEMO","sections":[{"heading":"第一章","items":[{"label":"条目","value":"1"}]}]}'

# 查询
curl -s http://127.0.0.1:8095/api/v1/jobs/ms_xxx -H "Authorization: Bearer $MOTION_TOKEN"

# 下载成片（播放器/浏览器可直接用）
curl -L -o out.mp4 "http://127.0.0.1:8095/api/v1/jobs/ms_xxx/video?token=$MOTION_TOKEN"
```

## 安卓端接入要点

- 提交与轮询用 `Authorization: Bearer`；播放/缩略图用 `?token=`。
- 轮询间隔 1.5~2 秒，`status` 为 `succeeded` 后取 `video_url`。
- 播放器需要 Range：本服务已支持 `Range` 与 `HEAD`，ExoPlayer 可直接拖动进度。
- 取消：`POST /cancel`；取消后 `status` 先变 `cancel_requested`，渲染线程在下一帧退出后变 `canceled`。
- 删除只对已结束任务开放；运行中的任务返回 409 `job_active`。
