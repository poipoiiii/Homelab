# 自定义域名接入方案（example.com，预留）

> 状态：**未实施**，等 tailnet 入口稳定后再做。
> 目标：用 `*.example.com` 代替 `*.ts.net` 访问 tailnet 内的服务。

## 1. 为什么不能直接用

- Tailscale 的 tailnet 域名只能从官方随机列表里选（`cat-crocodile.ts.net` 这类），不支持自定义。
- `example.com` 的 DNS 在阿里云（`dns1.example.com`），主域 A 记录当前指向 VPS `203.0.113.10`。
- 家里没有公网 IP，`*.example.com` 只能解析到 WSL 节点的 tailnet 地址 `100.64.0.10`，**只有装了 Tailscale 的设备能连**。
- VPS 上现有证书只签了 `example.com`，不是泛域名，不能复用给子域。
- 没有公网 80/443，Let's Encrypt 只能走 **DNS-01**。
- `tailscale serve` 已占用 `100.64.0.10:443`，Caddy 要接管 443 必须先停 serve。

## 2. 规划

| 子域 | 后端 | 说明 |
| --- | --- | --- |
| `home.example.com` | `127.0.0.1:7575` | Homarr 入口 |
| `cloud.example.com` | `127.0.0.1:8080` | Cloudreve |
| `jellyfin.example.com` | `127.0.0.1:8096` | Jellyfin |
| `vault.example.com` | `127.0.0.1:8082` | Vaultwarden |

全部 A 记录指向 `100.64.0.10`，不要指向 VPS，否则等于把服务公开。

## 3. 实施步骤

### 3.1 阿里云 DNS

在阿里云控制台为每个子域添加 A 记录，值 `100.64.0.10`。不要加泛解析到 VPS。

### 3.2 创建最小权限 AccessKey

RAM 子账号，只授予 DNS 权限（`AliyunDNSFullAccess` 或仅该域名的解析权限），用于 acme.sh 自动续期。密钥不要写进仓库。

### 3.3 签发泛域名证书（DNS-01）

```bash
curl https://get.acme.sh | sh -s email=you@example.com

export Ali_Key="<AccessKeyId>"
export Ali_Secret="<AccessKeySecret>"

~/.acme.sh/acme.sh --issue --dns dns_ali \
  -d example.com -d '*.example.com'
```

### 3.4 安装证书到 Caddy 目录

```bash
mkdir -p /home/ubuntu/caddy/certs
~/.acme.sh/acme.sh --install-cert -d example.com \
  --key-file       /home/ubuntu/caddy/certs/key.pem \
  --fullchain-file /home/ubuntu/caddy/certs/fullchain.pem \
  --reloadcmd      "docker exec caddy caddy reload --config /etc/caddy/Caddyfile"
```

acme.sh 会装一个 cron，每 60 天自动续期。

### 3.5 Caddy 反向代理

`/home/ubuntu/caddy/docker-compose.yml`：

```yaml
services:
  caddy:
    image: caddy:2
    container_name: caddy
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./certs:/etc/caddy/certs:ro
      - caddy_data:/data
    environment:
      - TZ=Asia/Shanghai

volumes:
  caddy_data:
```

`/home/ubuntu/caddy/Caddyfile`：

```caddyfile
{
    auto_https off
    admin 127.0.0.1:2019
}

https://home.example.com {
    bind 100.64.0.10
    tls /etc/caddy/certs/fullchain.pem /etc/caddy/certs/key.pem
    reverse_proxy 127.0.0.1:7575
}

https://cloud.example.com {
    bind 100.64.0.10
    tls /etc/caddy/certs/fullchain.pem /etc/caddy/certs/key.pem
    reverse_proxy 127.0.0.1:8080
}

https://jellyfin.example.com {
    bind 100.64.0.10
    tls /etc/caddy/certs/fullchain.pem /etc/caddy/certs/key.pem
    reverse_proxy 127.0.0.1:8096
}

https://vault.example.com {
    bind 100.64.0.10
    tls /etc/caddy/certs/fullchain.pem /etc/caddy/certs/key.pem
    reverse_proxy 127.0.0.1:8082
}
```

用 `network_mode: host` + `bind` 是为了只监听 tailnet 地址，不占 Windows 侧的 443。

### 3.6 停掉 tailscale serve

```bash
tailscale serve reset
```

之后所有入口由 Caddy 接管，`tailscale serve status` 应为空。

### 3.7 验证

```bash
curl --resolve cloud.example.com:443:100.64.0.10 https://cloud.example.com -o /dev/null -w '%{http_code}\n'
```

手机上用同一地址访问；没装 Tailscale 的设备会直接连不上，这是预期行为。

### 3.8 更新 Homarr

把卡片地址从 `https://home.<tailnet>.ts.net:8443` 改成 `https://cloud.example.com`，其余同理。

## 4. 回滚

```bash
cd /home/ubuntu/caddy && docker compose down
tailscale serve --bg --https=443  http://127.0.0.1:7575
tailscale serve --bg --https=8443 http://127.0.0.1:8080
```

DNS 记录可保留（不影响），或删除。

## 5. 风险与注意

- **AccessKey 泄漏等于域名被接管**：只给 DNS 权限，定期轮换。
- **证书续期依赖 acme.sh 的 cron**：WSL 长期关机可能错过续期，开机后手动跑一次 `~/.acme.sh/acme.sh --cron`。
- **所有入口依赖 tailscale0**：Tailscale 断开时全部 502，与现在 `serve` 的行为一致。
- **A 记录会公开 100.64.0.10**：该地址只在 tailnet 内可路由，公网连不上，但会暴露内网编址习惯。
- 如果以后想加统一登录，可在 Caddy 前面挂 Authelia，或直接用 Caddy 的 `forward_auth`。

## 6. 附：Jellyfin 公网 HTTPS（VPS nginx，另一条线）

这条和上面的 tailnet 方案互不影响：保留 frp 时，给公网入口加一层 HTTPS，避免 Jellyfin 在公网明文跑。

**现状**：VPS `203.0.113.10` 的 80/443 已被现有 nginx 占用（`https://example.com` 是“个人站点”站点），**不要再装 Caddy**，直接在 nginx 里加一个 server 块。

### 6.1 DNS

阿里云添加 A 记录：`jellyfin` → `203.0.113.10`。

### 6.2 VPS 新建站点配置

`/etc/nginx/conf.d/jellyfin.conf`：

```nginx
server {
    listen 80;
    server_name jellyfin.example.com;

    location / {
        proxy_pass http://127.0.0.1:8096;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
nginx -t && nginx -s reload
```

先用 `http://jellyfin.example.com` 确认能出 Jellyfin 页面，再签证书。

### 6.3 申请证书

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d jellyfin.example.com
```

certbot 会自动把上面的 server 块改成 443 + 证书，并注册续期。

### 6.4 关闭公网 8096

阿里云安全组删除 8096 的入方向规则（保留 25565 给 MC），外部统一走 443。

### 6.5 注意

- 家里 Jellyfin 容器必须运行，否则 nginx 返回 502。
- frpc 的 `jellyfin` 转发保持 `remotePort = 8096` 不变。
- 如果 nginx 由 1Panel/宝塔 管理，直接在面板里建反向代理站点，不要手改配置。
- 该入口是**公网可达**的，和 tailnet 的私密入口不同；担心安全时可在 nginx 上加 basic auth 或只放行特定 IP。
