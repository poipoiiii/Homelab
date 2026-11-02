FROM node:22-bookworm-slim

# ffmpeg 负责编码，fonts-noto-cjk 提供中文字形（DejaVu 没有中文，缺字会变方块）
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY src ./src
COPY scripts ./scripts

ENV NODE_ENV=production \
    PORT=8095 \
    DATA_DIR=/data \
    TZ=Asia/Shanghai

EXPOSE 8095

CMD ["node", "src/index.js"]
