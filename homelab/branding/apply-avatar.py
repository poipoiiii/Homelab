#!/usr/bin/env python3
"""一键更换整套头像 / 站点图标。

用法（在 UbuntuD 内，需要 root 才能写 /home/ubuntu/branding、操作 Homarr 数据库）：

    sudo python3 ~/homelab/branding/apply-avatar.py
    sudo python3 ~/homelab/branding/apply-avatar.py /path/to/新头像.png

不传参数时使用 /mnt/d/ubuntu_/homelab/favicon.jpeg。

会做这些事：
1. 备份现有图标到 D:\\ubuntu_\\.cache\\branding-backup\\<时间戳>；
2. 生成 logo.png / logo192.png / avatar.png / favicon.ico / favicon-32.png /
   favicon-16.png / apple-touch-icon.png；
3. 生成 LibreChat 使用的 logo.svg（内嵌 PNG）；
4. 更新 Homarr 的看板 logo、favicon 和用户头像，并重启 homarr
   （不改各应用卡片自己的图标）；
5. Jellyfin / LibreChat / Rong的账单 / 电源面板都是目录挂载，改完即生效，
   无需重建镜像（浏览器按 Ctrl+F5 强制刷新即可）。

非正方形图片会先居中裁成正方形，不做拉伸变形。
"""

import base64
import os
import shutil
import sqlite3
import subprocess
import sys
import time

from PIL import Image, ImageOps

DEFAULT_SOURCE = '/mnt/d/ubuntu_/homelab/favicon.jpeg'
BRANDING_DIR = '/home/ubuntu/branding'
BACKUP_ROOT = '/mnt/d/ubuntu_/.cache/branding-backup'
HOMARR_DB = '/var/lib/docker/volumes/homarr_homarr-data/_data/db/db.sqlite'
HOMARR_BACKUP_DIR = '/mnt/d/ubuntu_/.cache/exports/homarr'
HOMARR_CONTAINER = 'homarr'

# Homarr 里统一使用 192px 版本，够大又不至于拖慢首页
HOMARR_ICON = '/branding/logo192.png'
HOMARR_FAVICON = '/branding/favicon-32.png'


def fail(message: str) -> None:
    print('错误：' + message, file=sys.stderr)
    sys.exit(1)


def load_square(source: str, size: int = 1024) -> Image.Image:
    image = Image.open(source)
    has_alpha = image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)
    image = image.convert('RGBA' if has_alpha else 'RGB')
    return ImageOps.fit(image, (size, size), Image.LANCZOS, centering=(0.5, 0.5))


def write_in_place(path: str, image: Image.Image) -> None:
    """用原地写入保留 inode：Jellyfin 等服务的单文件 bind mount 依赖同一 inode。"""
    with open(path, 'wb') as handle:
        image.save(handle, 'PNG', optimize=True)


def write_ico(path: str, image: Image.Image) -> None:
    with open(path, 'wb') as handle:
        image.save(handle, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def write_librechat_svg(path: str, png_path: str) -> None:
    encoded = base64.b64encode(open(png_path, 'rb').read()).decode()
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" width="192" height="192">'
        '<defs><clipPath id="r"><rect width="192" height="192" rx="44" ry="44"/></clipPath></defs>'
        '<g clip-path="url(#r)"><image width="192" height="192" href="data:image/png;base64,%s"/></g>'
        '</svg>' % encoded
    )
    with open(path, 'w') as handle:
        handle.write(svg)


def generate_branding(source: str) -> None:
    square = load_square(source)
    os.makedirs(BRANDING_DIR, exist_ok=True)

    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup_dir = os.path.join(BACKUP_ROOT, stamp)
    os.makedirs(backup_dir, exist_ok=True)
    for name in os.listdir(BRANDING_DIR):
        src = os.path.join(BRANDING_DIR, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(backup_dir, name))
    print('已备份旧图标 ->', backup_dir)

    targets = {
        'logo.png': square.resize((512, 512), Image.LANCZOS),
        'logo192.png': square.resize((192, 192), Image.LANCZOS),
        'avatar.png': square.resize((512, 512), Image.LANCZOS),
        'apple-touch-icon.png': square.resize((180, 180), Image.LANCZOS),
        'favicon-32.png': square.resize((32, 32), Image.LANCZOS),
        'favicon-16.png': square.resize((16, 16), Image.LANCZOS),
    }
    for name, image in targets.items():
        write_in_place(os.path.join(BRANDING_DIR, name), image)

    write_ico(os.path.join(BRANDING_DIR, 'favicon.ico'), square)
    write_librechat_svg(os.path.join(BRANDING_DIR, 'librechat-logo.svg'), os.path.join(BRANDING_DIR, 'logo192.png'))
    print('已生成图标：', ', '.join(sorted(os.listdir(BRANDING_DIR))))


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(['docker', *args], check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def update_homarr() -> None:
    if not os.path.exists(HOMARR_DB):
        print('跳过 Homarr：未找到数据库', HOMARR_DB)
        return

    exists = docker('inspect', HOMARR_CONTAINER, check=False).returncode == 0
    running = False
    if exists:
        running = docker('inspect', '-f', '{{.State.Running}}', HOMARR_CONTAINER, check=False).stdout.strip() == 'true'
        if running:
            docker('stop', HOMARR_CONTAINER)

    try:
        os.makedirs(HOMARR_BACKUP_DIR, exist_ok=True)
        shutil.copy2(HOMARR_DB, os.path.join(HOMARR_BACKUP_DIR, 'db-%s.sqlite' % time.strftime('%Y%m%d-%H%M%S')))
        con = sqlite3.connect(HOMARR_DB)
        con.execute("update board set logo_image_url = ?, favicon_image_url = ?", (HOMARR_ICON, HOMARR_FAVICON))
        con.execute("update user set image = ?", (HOMARR_ICON,))
        con.commit()
        con.close()
        print('已更新 Homarr 看板 logo / favicon / 用户头像（应用卡片图标保持不变）')
    finally:
        if running:
            docker('start', HOMARR_CONTAINER)


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not os.path.isfile(source):
        fail('找不到图片：' + source)
    if not os.access(BRANDING_DIR, os.W_OK):
        fail('没有写权限：%s（请用 sudo 运行）' % BRANDING_DIR)

    print('使用图片：', source)
    generate_branding(source)
    update_homarr()

    print('\n完成。')
    print('  Homarr / Jellyfin / LibreChat / Rong的账单 / 电源面板 已换图；')
    print('  Cloudreve 的站点 logo 指向 /branding/*，启动后自动生效。')
    print('  浏览器请按 Ctrl+F5 强制刷新图标缓存。')


if __name__ == '__main__':
    main()
