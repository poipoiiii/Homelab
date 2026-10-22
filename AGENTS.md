# AGENTS.md

面向 AI 编码代理的项目说明。开始改动前请先读完本文；这里的约束多为**踩坑总结**，违反后容易损坏 WSL 发行版或让容器挂载失效。

## 1. 项目定位

在 Windows 上用 WSL2 自建的一台 Ubuntu 24.04（Noble）"homelab"主机：导入官方 rootfs 作为发行版 `UbuntuD`，在其中安装 Docker Engine，并通过 Docker Compose 运行若干自托管服务（Dockge、Jellyfin、Minecraft、Palworld）。

不是应用代码仓库，**没有构建/测试流程**。改动对象只有：PowerShell 安装脚本、Linux 安装脚本、Compose 文件、说明文档。所有脚本都要求人工在 Windows 管理员 / Ubuntu sudo 环境下执行，代理不应擅自运行会改动系统状态的命令。

## 0. 执行前强制检查：是否会写入 C 盘

**任何**可能产生文件的操作（下载、安装、拉镜像、解压、构建、导出、备份、写日志、缓存）执行前，必须先判定落盘位置，再决定是否执行。这是本项目的最高优先级规则。

检查清单：

1. 明确该操作会把文件写到哪里：下载目录、当前工作目录（cwd）、临时目录、日志/导出路径、包缓存、构建上下文、数据卷挂载点。
2. 判定这些路径是否落在 C 盘：`C:\...`、`%USERPROFILE%`（`C:\Users\<user>`）、`%LOCALAPPDATA%`、`%APPDATA%`、`%TEMP%`、`/mnt/c/...`、Docker Desktop 的 `...\AppData\Local\Docker`、WSL 默认安装/交换文件位置。
3. 任一命中 C 盘 → **立即停止，不得执行**，先与用户协商：说明要下载什么、预计体积、默认去向，并给出 D 盘替代方案（如 `-OutFile D:\...`、先 `cd D:\...`、改用 `wsl --import` 到 `D:\ubuntu_\...`、换下载目录）。
4. 只有用户明确同意后才能继续；未获同意时默认选择 D 盘方案，或放弃该操作。
5. 无法确定落盘位置时，视为"会写 C 盘"，先询问用户，不要试跑。
6. 操作后必须复核实际落点（`Get-Item`、`du -sh`、`Test-Path`）；若发现文件落到 C 盘，立即停止后续步骤，报告用户并移动到 D 盘、清理 C 盘残留。
7. 系统级例外仅限第 5.2 节列出的项（`wsl --update` 程序本体、Windows 功能组件、系统页面文件/更新缓存）；即便如此也要先告知用户。

常用手段：下载前先切换到 D 盘或显式指定 `D:\` 输出路径；Linux 侧所有下载/构建/缓存留在 ext4（`~/...`、`/tmp`）；禁止把 `TMPDIR`、npm/pip 缓存、git clone 目录指向 `/mnt/c`。详见第 5 节。

## 2. 目录结构

```text
d:\ubuntu_\                          Windows 侧工作目录（本仓库）
├─ start.md                          进入 UbuntuD 的命令备忘
├─ install_wsl2.ps1                  Windows: 启用 WSL2 + 导入发行版（需管理员）
├─ install_docker.sh                 Ubuntu: 安装 Docker Engine + compose 插件（需 sudo）
├─ SHA256SUMS                        官方 rootfs 校验和
├─ ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz   导入用的 rootfs（体积大，勿改）
├─ UbuntuD\ext4.vhdx                 WSL 发行版虚拟磁盘（真正的 Linux 根文件系统）
├─ homelab\                          Compose 堆栈源文件
│  ├─ docker-compose.yml             Dockge 控制面（端口 5001）
│  ├─ jellyfin\docker-compose.yml    Jellyfin（端口 8096）
│  ├─ mc\docker-compose.yml          Minecraft Forge 服务器（端口 25565）
│  ├─ firefly\                       已下线（Firefly III 堆栈，容器已移除，数据卷与账单原件保留）
│  ├─ bill-ai\                       本地账本 + 账单识别（端口 8091，SQLite）
│  │  ├─ docker-compose.yml
│  │  ├─ Dockerfile
│  │  ├─ app\                        FastAPI + 静态页面
│  │  └─ DESIGN.md                   页面设计系统（不参与运行）
│  └─ palworld\docker-compose.yml    Palworld 服务器（端口 8211）
└─ .cache\                           所有非源码产物（下载/导出/日志/临时，规则见 5.4）
   ├─ downloads\                     下载的 rootfs、整合包、镜像 tar
   ├─ exports\                       wsl --export、docker save、数据库备份
   ├─ logs\                          采集/导出的日志
   ├─ tmp\                           一次性临时文件、解压中间产物
   └─ <task>\                        单次任务的独立产物目录，按任务名再分层
```

关键事实：

- WSL 发行版名 **`UbuntuD`**，导入目录 `D:\ubuntu_\UbuntuD`，磁盘格式 ext4（vhdx），WSL 版本 2。
- 实际 Linux 用户为 **`ubuntu`**（UID 1000，home `/home/ubuntu`，已在 `sudo`、`docker` 组）；WSL 当前默认登录身份是 **`root`**（`/etc/wsl.conf` 只有 `[boot] systemd=true`，无 `[user]` 段）。
- Windows 桌面 shell 文件夹已重定向到 **`D:\Table__`**（注册表 `HKCU\...\Explorer\User Shell Folders\Desktop`，原 `C:\Users\USER\Desktop` 不再使用）；放在桌面的文件实际落 D 盘。但桌面**不是**项目产物落点，产物仍统一进 `.cache`（见 5.4）。`Downloads` 仍在 C 盘，下载前必须改目标目录。
- Linux 侧运行位置是 `~/homelab`（以 `ubuntu` 登录即 `/home/ubuntu/homelab`），Dockge 挂载的是 `~/homelab/stacks`。**Windows 侧的 `d:\ubuntu_\homelab` 只是源文件，不会自动同步进 WSL。**
- 磁盘 IO 规则：`/mnt/d/...` 走 9P，性能差且不支持部分 Unix 语义。**容器数据、Compose 文件、数据库一律放 ext4（命名卷或 `~/...`），只有大体积只读媒体可以挂 `/mnt/d/media`。**

## 3. 常用操作

进入发行版（`start.md` 的做法，先切到系统目录可避免 "UNC 路径不支持" 警告）：

```powershell
cd C:\WINDOWS\system32 ; wsl -d UbuntuD
```

资源参数（内存 / CPU / swap / 空闲关停）统一写在 `%USERPROFILE%\.wslconfig`（内容见 5.1 第 3 条），WSL 在 VM 启动时自动读取，**没有对应的启动命令行参数**；改过配置必须先 `wsl --shutdown` 再启动：

首次安装（Windows 管理员 PowerShell）：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& "D:\ubuntu_\install_wsl2.ps1"
```

安装 Docker（Ubuntu 内普通用户，脚本内部自带 sudo）：

```bash
sudo bash /mnt/d/ubuntu_/install_docker.sh
```

部署/更新某个堆栈（Ubuntu 内）：

```bash
cd ~/homelab            # 或 ~/homelab/<service>
docker compose up -d
docker compose logs -f  # 排错
```

查看状态：

```powershell
wsl -l -v
```

```bash
docker ps
wsl.exe --version
```

## 4. 服务与端口

| 服务 | 镜像 | 端口 | 数据位置 |
| --- | --- | --- | --- |
| Dockge | `louislam/dockge:1` | 5001/tcp | 命名卷 `dockge_data` + `~/homelab/stacks` |
| Jellyfin | `jellyfin/jellyfin:latest` | 8096/tcp | 命名卷 config/cache；媒体 `/mnt/d/media` 只读 |
| Minecraft | `itzg/minecraft-server:latest` | 25565/tcp | 命名卷 `mc_data` |
| Palworld | `thijsvanloef/palworld-server-docker:latest` | 8211 udp + tcp | 命名卷 `palworld_data` |
| Dozzle | `amir20/dozzle:latest` | 8888/tcp | 无卷，**可写**挂 docker.sock（用于启停容器） |
| IT-Tools（已下线） | `corentinth/it-tools:latest` | ~~8081~~ | 容器、镜像与 compose 已删除 |
| Beszel | `henrygd/beszel` + `beszel-agent` | 8090/tcp | 命名卷 `beszel_data` / `beszel_agent_data` |
| Vaultwarden | `vaultwarden/server:latest` | 8082/tcp | 命名卷 `vaultwarden_data` |
| lab-tools | 自建镜像（`homelab/lab-tools`） | 127.0.0.1:8765 | 命名卷 `lab_tools_audit`；读代理只读，写代理仅 start/stop（`EXEC`/`VOLUMES`/`CONTAINERS` 关闭） |
| MeTube | `alexta69/metube:2026.10.22` | 127.0.0.1:8081 | 下载目录 `/mnt/d/game_video_`、`/mnt/d/yt_video_`、`/mnt/d/mv__`；命名卷 `metube_state`；B 站登录态在 `~/homelab/metube/cookies.txt`（600，勿提交） |
| Firefly III（已下线） | `fireflyiii/core:latest` | ~~8083~~ | 容器已移除；命名卷 `firefly_db` / `firefly_upload` 保留，备份在 `.cache/exports/firefly` |
| Rong的账单 | 本地构建（`homelab/bill-ai`） | 8091/tcp（127.0.0.1） | 命名卷 `bill_ai_data`（SQLite `/data/bill.db`）；tailnet `8451` |

Rong的账单 同时承担记账与账本：`/` 记一笔、`/dashboard` 总览、`/transactions` 流水、`/settings` 账户与分类。数据全部在 SQLite，不再依赖 Firefly 或 PostgreSQL。

新增的管理类服务只绑定 `127.0.0.1`，**不要加进 frp**；需要远程访问时走 SSH 隧道，或另行评估隧道方案。

Minecraft 环境变量需与整合包匹配：`TYPE=FORGE`（NeoForge 改 `NEOFORGE`）、`VERSION=1.21.1`、`MEMORY=6G`、`ONLINE_MODE=true`（离线服改 `false`）。

## 5. 存储位置与 C 盘禁令

原则：本项目的**全部数据面**（镜像、容器层、数据卷、构建缓存、WSL 交换文件、rootfs、导出备份）必须落在 D 盘。C 盘只允许 Windows/WSL 程序本体这类系统级、小体积安装。

### 5.1 会写入 C 盘的禁止操作

1. **用 `wsl --install -d Ubuntu*` 或 Microsoft Store 安装发行版**：默认落在 `C:\Users\<user>\AppData\Local\Packages\...`。本项目只允许 `wsl --import UbuntuD D:\ubuntu_\UbuntuD <rootfs.tar.gz> --version 2`。
2. **安装 Docker Desktop**：镜像与数据在 `C:\Users\<user>\AppData\Local\Docker\wsl`。本项目只用 WSL 内原生 Docker Engine。
3. **保留默认交换文件**：WSL2 默认把 `swap.vhdx` 放在 `%LOCALAPPDATA%\Temp\swap.vhdx`（C 盘）。已在 `%USERPROFILE%\.wslconfig` 中指定到 D 盘（该文件是 WSL 唯一读取的配置位置，体积为字节级，属于允许的系统级例外；`D:\wsl` 目录必须先存在）：

   ```ini
   [wsl2]
   # 内存上限锁死，防止 WSL 吃满主机（本机 32GB）
   memory=16GB
   # 本机 16 逻辑线程，给 Windows 留 8 线程
   processors=8
   # swap 总量 4GB
   swap=4GB
   # swap 文件放 D 盘，不占 C 盘
   swapFile=D:\\wsl\\wsl-swap.vhdx
   # 空闲 30 分钟自动关停 VM，内存归还 Windows（单位：毫秒）
   vmIdleTimeout=1800000
   localhostForwarding=true
   ```

   注意：键名是 `swap`（容量）+ `swapFile`（路径），没有 `swapfile size`；`vmIdleTimeout` 单位是**毫秒**（30 分钟 = `1800000`）；注释必须独占一行，不要写在值后面。改完执行 `wsl --shutdown` 再启动才生效。
4. **用浏览器/下载工具下载 rootfs、整合包、镜像 tar**：默认存 `C:\Users\<user>\Downloads`。下载前把目标目录改为 D 盘。
5. **把导出/备份/日志写到 C**：`wsl --export`、`docker save`、`docker compose logs > ...`、数据库备份等，输出路径必须显式指向 `D:\...` 或 WSL 内 ext4。
6. **在 Windows 侧（WSL 外）运行 docker 命令或构建**，以及把 Compose 目录/构建上下文复制到 C 盘。
7. **把工作目录、缓存目录指到 `/mnt/c`**：Linux 内 npm/pip/apt 缓存默认在 ext4.vhdx（D 盘），不要为了"方便"改到 `/mnt/c/...`。
8. **在 C 盘解压 rootfs 或存放虚拟磁盘**（`ext4.vhdx`、`swap.vhdx`、导出的 tar）。

### 5.2 不可避免的 C 盘写入（允许）

- `wsl --update` 安装的 WSL 程序本体（`C:\Program Files\WSL`）。
- Windows 可选功能组件（`VirtualMachinePlatform`、`Microsoft-Windows-Subsystem-Linux`）。
- Windows 自身的页面文件、更新缓存、系统日志。

这些属于系统级安装，不要试图迁移；但**不得把任何项目数据、镜像、备份放进这些位置**。

### 5.3 校验方法

```powershell
# 发行版磁盘位置（应在 D 盘）
Get-Item 'D:\ubuntu_\UbuntuD\ext4.vhdx'
# 交换文件是否仍在 C（应不存在，或已通过 .wslconfig 迁走）
Test-Path "$env:LOCALAPPDATA\Temp\swap.vhdx"
# 是否误装 Docker Desktop
Test-Path "$env:LOCALAPPDATA\Docker"
```

注意：vhdx 只增不减，删除镜像/容器后不会自动缩小，需 `wsl --shutdown` 后压缩（`Optimize-VHD` / `diskpart`，或 Win11 上 `wsl --manage UbuntuD --set-sparse true`）。

### 5.4 项目产物落点（`.cache`）与根目录整洁

Windows 侧所有**非源码产物**——下载包、导出/备份、日志、截图、临时解压、分析中间件、脚本生成物——统一写入 `D:\ubuntu_\.cache\`，不得散落在仓库根目录。

```text
D:\ubuntu_\            # 根目录只放必要文件/目录，不堆放产物
└─ .cache\             # 全部产物（约定不入 git）
   ├─ downloads\       # 下载的 rootfs、整合包、镜像 tar
   ├─ exports\         # wsl --export、docker save、数据库备份
   ├─ logs\            # 采集/导出的日志
   ├─ tmp\             # 一次性临时文件、解压中间产物
   └─ <task>\          # 单次任务的独立产物目录，按任务名再分层
```

规则：

1. 新产物先落到 `.cache\<类别>\` 或 `.cache\<任务名>\`，用完可整体删除；不要在根目录新建临时文件。
2. 根目录白名单：`AGENTS.md`、`start.md`、`install_wsl2.ps1`、`install_docker.sh`、`SHA256SUMS`、rootfs tar.gz、`UbuntuD\`、`homelab\`、`.cache\`。新增文件先确认是否必要，否则放进 `.cache`。
3. 长期维护的源码/配置（脚本、compose、文档）仍按原位置保留，不算产物，不要放进 `.cache`。
4. `.cache` 只是 Windows 侧落点：容器可写数据、数据库、构建缓存仍必须在 ext4（命名卷或 `~/...`）；需要被容器挂载或高频读写的文件不要放 `/mnt/d/ubuntu_/.cache`。
5. WSL 内访问同一目录用 `/mnt/d/ubuntu_/.cache`，仅用于读取/传递产物，不作工作目录。

## 6. 硬性约束（务必遵守）

1. **不要删除或"整理" `UbuntuD\ext4.vhdx`**：那是整个 Linux 系统，删掉等于重装。
2. **不要重新执行 `install_wsl2.ps1`**，除非确实要重建发行版：`wsl --import` 要求目标目录为空，脚本会对非空目录直接抛错；`--import` 同名发行版也会冲突。
3. **不要修改 `ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz` / `SHA256SUMS`**，也不要对该 tar.gz 解包到仓库目录。
4. **不要把容器可写数据挂到 `/mnt/d`**（9P 性能与权限问题），用命名卷；新增只读媒体挂载可参照 Jellyfin 的 `:ro` 写法。唯一例外：Cloudreve 的上传目录按用户要求直连 D 盘（`/mnt/d/media/cloudreve` → `/cloudreve/data/uploads`），配置与 SQLite 仍在 ext4；新增此类例外必须先征得用户同意。
5. **Dockge 挂了 `/var/run/docker.sock`，等价于宿主机 root 权限**，不要把它无鉴权暴露到公网；如需远程访问，必须自行加认证或走隧道。
6. **脚本改动保持幂等/可重跑**：`install_docker.sh` 已用 `set -euo pipefail`，并且对 `/etc/wsl.conf`、`/etc/profile.d` 的写入都做了存在性判断，改动时不要破坏这一点。
7. **改完 Compose 后不要自动执行 `up -d`**，除非用户明确要求——这些操作会拉镜像、占端口、写数据卷。
8. `docker` 组变更需要退出并重进 WSL 才生效；`systemd=true` 需要 Windows 侧 `wsl --shutdown` 后重启发行版。修改 WSL 配置后要把这一步写进操作说明。
9. 命令区分位置：`.ps1` 只能在 **Windows 管理员 PowerShell** 跑；`.sh` 与 `docker compose` 只能在 **UbuntuD 内**跑。不要用 PowerShell 语法写 Linux 脚本或反之。
10. 路径混用规则：Windows 侧写 `D:\ubuntu_\...`；WSL 内访问同一位置用 `/mnt/d/ubuntu_/...`（仅脚本/配置读取，勿作数据盘）。
11. **禁止让数据落到 C 盘**：执行任何下载/安装/构建/导出操作前，必须按第 0 节先检测落点；会写 C 盘则先与用户协商，未获同意不得执行。具体清单见第 5 节。
12. **项目产物统一落 `.cache`**：下载、导出、备份、日志、临时文件写入 `D:\ubuntu_\.cache\` 的对应子目录（按类别或任务名分层），根目录只保留白名单内的必要文件/目录，详见第 5.4 节。

## 7. 排错速查

- `wsl --update` 后仍报 `0x800701bc`：WSL2 内核未装好，重跑 `wsl --update` 或安装内核更新包。
- `docker: command not found`：Docker 未安装或当前 shell 未刷新，重开终端；必要时 `sudo service docker start`。
- `permission denied /var/run/docker.sock`：当前用户还没进 `docker` 组，重开终端或 `newgrp docker`。
- Compose 在 `/mnt/d` 下运行缓慢或报文件锁错误：把目录复制到 `~/homelab` 再执行。
- 改了 `[boot] systemd=true` 不生效：`wsl --shutdown` 后再进。

## 8. 文档与提交约定

- 中文注释/说明为主，命令、路径、服务名保持原样。
- 新增服务时：在 `homelab/<service>/docker-compose.yml` 放一份自包含 compose，数据用命名卷，端口冲突要在本文第 4 节表格登记。
- 仓库根目录 `.gitignore` 尚未建立；如初始化 git，必须排除 `UbuntuD/`、`*.vhdx`、`*.tar.gz`、`.cache/`。
