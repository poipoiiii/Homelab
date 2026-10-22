# 自建 DERP / Headscale 方案（暂缓执行）

> 状态：**仅设计，未实施**。
> 目标：保留 tailnet + `tailscale serve` 这套框架，把东京 DERP 中继换成自己的 VPS。
> 当前节点：`home` / `100.64.0.10`，`tailscale ping` 显示 `via DERP(tok)`，150~200ms。

## 1. 先分清两层

Tailscale 由两部分组成：

| 层 | 作用 | 现在的位置 |
| --- | --- | --- |
| 控制面 | 登录、发密钥、下发节点和 ACL | `login.tailscale.com`（官方） |
| 数据面 | 优先 UDP 打洞直连；失败时走 DERP 中继 | 直连未建立，走东京 `tok` |

卡顿来自**中继节点**，不是框架本身。`tailscale serve` 只是在节点上做反向代理，换 DERP 不影响它，`https://home.example-tailnet.ts.net:8443` 这些地址都不用变。

## 2. 方案 A：自建 DERP，保留 Tailscale 控制面

官方支持自定义 DERP（alpha），通过 tailnet 的 ACL 策略文件注入 `derpMap`。

### 2.1 前置条件

- 一个指向 VPS 的域名，例如 `derp.example.com`
- VPS 有**直接公网出口**，不能在这几个端口前再套 NAT 或负载均衡
- 放行 `80/tcp`、`443/tcp`、`3478/udp`，允许 ICMP
- VPS 加入 tailnet（`--verify-clients` 需要本机有已登录的 tailscaled）

### 2.2 端口冲突

现有 VPS 的 80/443 已被 nginx 占用（`example.com` 站点）。三种处理：

1. 用**新 VPS 专做 DERP**，网站继续留在旧机器（最干净，推荐）
2. derper 监听 8443，ACL 里把 `DERPPort` 设为 8443；80 仍需给 derper 做 ACME/跳转
3. 把 nginx 与 derper 合并到一台机器上做端口规划（不推荐，DERP 要求直连、不能走反向代理）

### 2.3 部署 derper

```bash
# 安装 Go 后
go install tailscale.com/cmd/derper@latest
sudo cp ~/go/bin/derper /usr/local/bin/derper

sudo derper --hostname=derp.example.com --verify-clients
```

systemd：

```ini
[Unit]
Description=derper
After=network.target

[Service]
ExecStart=/usr/local/bin/derper --hostname=derp.example.com --verify-clients
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

保存为 `/etc/systemd/system/derper.service`：

```bash
systemctl daemon-reload
systemctl enable --now derper
systemctl status derper
```

### 2.4 在 ACL 里加入 DERP

管理台 → Access Controls → 策略文件，加入（与 `acls`/`grants` 同级）：

```json
"derpMap": {
  "OmitDefaultRegions": true,
  "Regions": {
    "900": {
      "RegionID": 900,
      "RegionCode": "vps",
      "Nodes": [{
        "Name": "1",
        "RegionID": 900,
        "HostName": "derp.example.com",
        "IPv4": "203.0.113.10"
      }]
    }
  }
}
```

- `OmitDefaultRegions: true` = 完全不用官方 DERP（包括东京）
- 先保留默认区域跑一天，确认自建 DERP 正常后再加这一行
- 区域 ID 900~999 是官方保留给自定义的

### 2.5 验证

```bash
tailscale netcheck                    # 看最近 DERP 的延迟
tailscale ping redmi-turbo-4-pro      # 应显示 via DERP(vps)
tailscale serve status                # 映射应保持不变
```

手机端断开重连一次让配置生效。

### 2.6 维护

- 自定义 DERP 目前是 alpha，客户端升级后可能需要重新 `go install` 并重启
- 建议每 1~2 个月更新一次 derper
- DERP 只转发加密流量，看不到内容

## 3. 方案 B：Headscale + 内置 DERP

彻底替换官方控制面，VPS 自己管登录、密钥、ACL 和 DERP。

### 3.1 大致步骤

1. DNS：`hs.example.com` → VPS
2. 用 Docker 跑 Headscale，挂载 `config.yaml`、`db.sqlite`
3. 配置项：
   - `server_url: https://hs.example.com`
   - `listen_addr: 0.0.0.0:8080`（前面用 nginx/Caddy 终止 TLS）
   - `derp.server.enabled: true`（内置 DERP，需 `stun_listen_addr`，放行 3478/udp）
   - `ip_prefixes: 100.64.0.0/10`
4. 创建用户和预授权 key：
   ```bash
   headscale users create home
   headscale preauthkeys create --user home --reusable --expiration 24h
   ```
5. 所有客户端切换：
   ```bash
   tailscale up --login-server https://hs.example.com --authkey <key>
   ```
6. 迁移 ACL：Headscale 用 `policy.hujson`，语法与 Tailscale 略有差异

### 3.2 代价

- 需要自己维护版本升级、备份 `db.sqlite`、证书续期
- 出问题没有官方后台可查
- 手机端切换控制面后，原来的 tailnet 会变成两套，需要重新登录

建议先用方案 A 跑稳，再决定是否上 B。

## 4. 方案 C：先修直连（不新增组件）

如果直连能建立，视频根本不经过任何中继，速度只受家宽上行限制。

排查顺序：

1. `tailscale netcheck` 看 UDP 是否可用、NAT 类型
2. 确认家里路由器没有屏蔽 UDP 41641，开启 UPnP / NAT-PMP
3. WSL2 多一层 NAT，可尝试：
   - 把 Tailscale 装到 Windows 宿主机（WSL 服务通过端口映射访问）
   - 或在 Windows 11 上启用 WSL 镜像网络模式（`.wslconfig` 的 `networkingMode=mirrored`）
4. 手机侧切 Wi-Fi / 蜂窝网络分别测试

## 5. 带宽与成本

DERP 是**中继**，视频流量会经过 VPS：

| 套餐 | 实际能力 | 适合 |
| --- | --- | --- |
| 3 Mbps | 0.375 MB/s，只能转码 720p 单路 | 传文档、照片、偶尔看低码率 |
| 200 Mbps | 可多路 1080p/4K，受家宽上行限制 | Jellyfin 主力 |

另外确认套餐的**月流量额度**：10 Mbps 看两小时约 9 GB，一个月可到 270 GB；4K 会成倍增长。

## 6. 回滚

- 方案 A：ACL 里删除 `derpMap` 或把 `OmitDefaultRegions` 改为 `false`，客户端自动回落到官方 DERP；VPS 上 `systemctl disable --now derper`
- 方案 B：客户端重新 `tailscale up` 指向官方控制面；保留 Headscale 数据卷以便回查

## 7. 决策建议

| 目标 | 选择 |
| --- | --- |
| 只想解决东京慢，改动最小 | A |
| 完全不想依赖 Tailscale 官方 | B |
| 追求最快、能接受折腾路由器/WSL | C |
| 三者可叠加 | 先 C 排查，再做 A；B 作为长期选项 |
