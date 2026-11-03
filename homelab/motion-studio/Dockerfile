FROM node:22-bookworm-slim

# ffmpeg 负责编码/合音轨，fonts-noto-cjk 提供中文字形；
# 其余是 chrome-headless-shell 在 slim 镜像里运行所需的系统库。
# Debian 官方源在国内很慢，构建时换成阿里云镜像；海外部署可把这一行删掉。
# 56MB 的 Noto CJK 用 apt 下载容易卡住，下面改用 curl 直接取同一个 deb。
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      ffmpeg fonts-dejavu-core \
      ca-certificates curl \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
      libpango-1.0-0 libcairo2 libasound2 libxshmfence1 libx11-xcb1 libxcb-dri3-0 \
    && curl -fL --retry 5 --max-time 300 -o /tmp/fonts-noto-cjk.deb \
      https://mirrors.aliyun.com/debian/pool/main/f/fonts-noto-cjk/fonts-noto-cjk_20220127+repack1-1_all.deb \
    && apt-get install -y --no-install-recommends /tmp/fonts-noto-cjk.deb \
    && rm -f /tmp/fonts-noto-cjk.deb \
    && rm -rf /var/lib/apt/lists/*

# Puppeteer 解压 chrome-headless-shell 的 zip 需要 unzip；单独一层，避免改动上面的大 apt 缓存
RUN apt-get update \
    && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
# Puppeteer 默认从 Google 存储下载；国内构建改用 npmmirror 的 chrome-for-testing 镜像。
RUN PUPPETEER_SKIP_DOWNLOAD=true npm install --omit=dev --no-audit --no-fund \
    && PUPPETEER_DOWNLOAD_BASE_URL=https://cdn.npmmirror.com/binaries/chrome-for-testing \
       npx puppeteer browsers install chrome-headless-shell \
    && ln -sf "$(find /root/.cache/puppeteer/chrome-headless-shell -type f -name chrome-headless-shell | head -n 1)" /usr/local/bin/chrome-headless-shell

COPY src ./src
COPY scripts ./scripts

ENV NODE_ENV=production \
    PORT=8095 \
    DATA_DIR=/data \
    TZ=Asia/Shanghai \
    HYPERFRAMES_BROWSER_PATH=/usr/local/bin/chrome-headless-shell

EXPOSE 8095

CMD ["node", "src/index.js"]
