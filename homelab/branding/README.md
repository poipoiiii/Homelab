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
