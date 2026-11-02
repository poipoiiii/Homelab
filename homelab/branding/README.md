# 更换头像 / 站点图标

全站图标由 `~/homelab/branding/apply-avatar.py` 统一生成，源图默认是 `d:\ubuntu_\homelab\favicon.jpeg`。换图只需一条命令，不需要重建镜像。

## 一键更换

在 UbuntuD 内执行（需要 root，脚本会写 `/home/ubuntu/branding` 并操作 Homarr 的 SQLite）：

```bash
# 默认使用 /mnt/d/ubuntu_/homelab/favicon.jpeg
sudo python3 ~/homelab/branding/apply-avatar.py

# 或指定任意图片
sudo python3 ~/homelab/branding/apply-avatar.py /path/to/新头像.png
```

执行完浏览器按 `Ctrl+F5` 强制刷新，避免 favicon 缓存。

如果图片本身已经换过，直接把新图覆盖 `homelab/favicon.jpeg`，再跑第一条命令即可。

## Homarr 看板主题（砂糖 · 暗夜樱糖）

`apply-sugar-theme.py` 只改 Homarr 的外观，不动应用卡片和布局：

- 背景：`docs/砂糖/8.png` → 1920×1080，压暗 + 轻模糊 + 暗角，写到 `/branding/sugar/bg.jpg`（仅在缺动图时使用）；
- 动态背景（生成的 GIF，脚本不制作，存在即优先）：
  - `/branding/sugar/bg-anim.gif` 横屏 960×540，10fps，5.6 MB；
  - `/branding/sugar/bg-anim-portrait.gif` 竖屏 540×960，10fps，4.7 MB，手机竖屏由 `sugar-theme.css` 的 media query 切换；
- logo / 头像 / favicon：`docs/砂糖/6.jpg` 裁正方形、切圆角，写到 `/branding/sugar/`；
- 看板主色 `#d6336c`、副色 `#f783ac`，以及 `sugar-theme.css` 里的糖霜白毛玻璃卡片；
- 纯享模式：生成 `/branding/sugar/pure.html` + `pure.jpg`，并在看板右下角补一张「纯享模式」卡片。页面按横竖屏自动加载对应的 GIF（缺图退回 `pure.jpg`），点击画面进入浏览器全屏、Esc 退出。
- 全屏 PWA 外壳：`/branding/sugar/board.html` + `board.json` + `sw.js`。manifest 里 `display: "fullscreen"`，手机用这个地址「添加到主屏幕」后，点图标启动没有状态栏、没有地址栏。

  启动顺序：`poster-land.jpg` / `poster-port.jpg`（从两张 GIF 的首帧导出，60 KB 级）先铺满屏 → 看板 iframe 加载完、动态背景就绪 → 封面淡出（600ms）→ 顶栏与卡片依次浮现（`sugar-theme.css` 里的 `.launch-reveal`）。封面找不到时退化为纯色底，不影响使用。

  手机端（宽度 ≤ 768）底部还有一条可横滑的气泡栏，整条装在一个圆角玻璃外框里（只做一层 `backdrop-filter`，气泡本身不模糊，避免手机上叠 9 层导致卡顿）：外壳从看板 DOM 里读取 `[data-kind="app"]` 卡片的图标（`img[alt]` 就是应用名）和链接动态生成，第一项是「看板」回到首页；只有在首页（`/`、`/boards`、`/boards/<名字>`）才显示，进入设置等二级页面会自动收起。应用点开走**新标签页**（`target="_blank"`），因为 LibreChat 等会发 `X-Frame-Options: SAMEORIGIN`，塞进 iframe 会被浏览器拦掉。同时给看板的 `<html>` 挂 `has-dock`，主题 CSS 据此隐藏原来的 app 卡片并给主区域留出 96px 底部空间。应用增删在 Homarr 里改即可，气泡栏每次启动自动同步。卡片右下角的在线状态点会同步到气泡上（每 4 秒回读一次，颜色直接取原卡片的计算样式；没有 ping 的应用如纯享模式不显示点）。

  **新增应用**：Homarr 右上角铅笔进编辑模式 → 添加应用 → 填名称、地址、图标 → 拖进网格保存。注意两点：① 桌面和**手机两套布局都要放**（气泡栏读的是手机布局渲染出来的 DOM，只放桌面布局手机上读不到）；② 保存后把手机上的 PWA 杀掉重开，气泡栏才会重新生成。气泡顺序跟网格里卡片的顺序一致；不想出现在气泡栏的应用，别放进手机布局即可。状态点需要在该应用的设置里配了 ping 地址，没配就只显示图标。

  ```text
  手机浏览器打开  https://<你的地址>/branding/sugar/board.html
  菜单 → 安装应用 / 添加到主屏幕 → 从新图标启动
  ```

  外壳只是用 iframe 套住 `/`，看板本身的行为不变；原来的 Homarr 图标可以保留（它仍带状态栏）或删掉。注意：往 `branding/` 里**新增**静态文件后必须 `docker restart homarr`，Next 只在启动时扫描 public 目录，否则会 404。

```bash
sudo python3 ~/homelab/branding/apply-sugar-theme.py            # 默认素材目录 /mnt/d/ubuntu_/docs/砂糖
sudo python3 ~/homelab/branding/apply-sugar-theme.py <素材目录>  # 换一套图
```

回滚：重跑 `apply-avatar.py` 即可恢复原来的 logo / favicon / 头像；看板背景与自定义 CSS 可从 `D:\ubuntu_\.cache\exports\homarr\` 的数据库备份找回。

## 图片要求

- 常见格式（JPEG / PNG / WebP）；有透明通道会保留。
- 非正方形会**居中裁成正方形**，不拉伸；主体尽量放画面中央。
- 建议原图不小于 512×512，否则大尺寸 logo 会糊。
- 16×16 的 favicon 看不清细节，挑对比度高一点的图更合适。

## 会改哪些地方

| 位置 | 用的文件 | 生效方式 |
| --- | --- | --- |
| Homarr 看板 logo | `/branding/logo192.png` | 脚本更新数据库后重启 homarr |
| Homarr 浏览器标签图标 | `/branding/favicon-32.png` | 同上 |
| Homarr 登录用户头像 | `/branding/logo192.png` | 同上 |
| Jellyfin favicon / iOS touch icon | `favicon.ico`、`apple-touch-icon.png` | 单文件挂载，原地写入即时生效 |
| Jellyfin 未设置头像用户的默认头像 | `avatar.png` | 单文件挂载，即时生效 |
| LibreChat 登录页 logo | `librechat-logo.svg` | 单文件挂载，即时生效 |
| LibreChat favicon | `favicon-32.png`、`favicon-16.png` | 单文件挂载，即时生效 |
| Rong的账单 页头头像 / favicon | `/branding/*` | 目录挂载 `/home/ubuntu/branding:/branding:ro` |
| 电源面板 页头头像 / favicon | `/branding/*` | 同上 |
| Cloudreve 站点 logo / PWA 图标 | `/branding/logo.png` 等 | 站点设置里存的是 URL，启动后自动读取 |

**不会改**：

- Homarr 看板上的**应用卡片图标**——每张卡片保留自己的 `icon_url`（Jellyfin、LibreChat、Traccar 等各自的官方图标）。要单独改某张卡片，在 Homarr 页面里编辑该应用换图标。
- Dozzle、Dockge、MeTube、Pinchflat、Traccar 等没有官方自定义 logo 入口的服务。
- Docker 镜像内的静态资源（除上面通过挂载覆盖的文件外）。

## 生成的文件

写入 `/home/ubuntu/branding/`：

| 文件 | 尺寸 / 用途 |
| --- | --- |
| `logo.png` | 512×512，Cloudreve 站点 logo、PWA 大图标 |
| `logo192.png` | 192×192，Homarr 看板 / 应用内头像、页头头像 |
| `avatar.png` | 512×512，Jellyfin 默认头像 |
| `apple-touch-icon.png` | 180×180，iOS 添加到主屏幕 |
| `favicon-32.png` / `favicon-16.png` | 浏览器标签 |
| `favicon.ico` | 多尺寸 16–256，兼容旧浏览器 |
| `librechat-logo.svg` | 内嵌 `logo192.png` 的 SVG，供 LibreChat 使用 |

所有 PNG 都是原地写入（保留 inode），这样 Jellyfin / LibreChat 的单文件 bind mount 才能立刻看到新内容。**不要用 `rm` 后重新创建的方式替换这些文件**，否则容器里仍是旧图，需要重建容器才能恢复。

## 备份与回滚

每次执行前会自动备份：

- 旧图标：`D:\ubuntu_\.cache\branding-backup\<时间戳>\`
- Homarr 数据库：`D:\ubuntu_\.cache\exports\homarr\db-<时间戳>.sqlite`

回滚某一版图标：

```bash
sudo cp /mnt/d/ubuntu_/.cache/branding-backup/20261023-084048/* /home/ubuntu/branding/
```

Homarr 的数据库一般不用回滚——脚本只改 `board` 的 logo/favicon 和 `user.image` 三处；确实要回滚时先 `docker stop homarr`，覆盖 `db.sqlite` 后再启动。

## 常见问题

**执行时报“没有写权限”**
用 `sudo` 运行；`/home/ubuntu/branding` 属 root。

**Homarr 打不开或图标没变**
脚本会短暂停掉 homarr（约 10 秒）再启动。确认 `docker ps` 里 homarr 是 Up；日志看 `docker logs --tail 30 homarr`。

**改完还是旧图**
浏览器 favicon 缓存很顽固，`Ctrl+F5`；手机端把网页加到主屏幕的需要删掉重新添加。

**Windows 侧和 WSL 里的脚本不一致**
`d:\ubuntu_\homelab\branding\apply-avatar.py` 是源文件，实际执行的是 `~/homelab/branding/apply-avatar.py`，两者不会自动同步。改完源文件后执行：

```bash
cp /mnt/d/ubuntu_/homelab/branding/apply-avatar.py ~/homelab/branding/apply-avatar.py
```

## 给新服务接入

新容器想用同一套图标，按下面两种方式之一接：

1. **目录挂载**（推荐，之后换图无需重启）：在 compose 里加
   ```yaml
   volumes:
     - /home/ubuntu/branding:/branding:ro
   ```
   页面里直接引用 `/branding/logo192.png`、`/branding/favicon.ico`。

2. **单文件挂载**（只能覆盖镜像自带的固定路径）：把 `branding` 里的对应文件挂到容器内的目标路径，注意替换时保留原文件 inode。

接入后记得在上面的“会改哪些地方”表格里补一行。
