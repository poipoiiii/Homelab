#!/usr/bin/env python3
"""Homarr 看板「砂糖 · 暗夜樱糖」主题一键应用。

用法（在 UbuntuD 内，需要 root：要写 /home/ubuntu/branding 并操作 Homarr 数据库）：

    sudo python3 ~/homelab/branding/apply-sugar-theme.py
    sudo python3 ~/homelab/branding/apply-sugar-theme.py /path/to/素材目录

做的事：
1. 从素材目录取图 8（黄昏）压暗 + 轻模糊，生成 1920×1080 静态背景 bg.jpg；
   /branding/sugar/ 下已有 bg-anim.gif 时，看板背景优先用动图，bg.jpg 只作回退；
2. 从图 6 裁出正方形的看板 logo / 头像 / favicon 一套，写入 /home/ubuntu/branding/sugar；
3. 备份 Homarr 数据库到 D:\\ubuntu_\\.cache\\exports\\homarr；
4. 更新看板背景、logo、favicon、主色、自定义 CSS，以及全站品牌色；
5. 重启 homarr 容器。

只改看板外观，不动应用卡片（图标、链接、布局都保持原样）。
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

DEFAULT_SOURCE = '/mnt/d/ubuntu_/docs/砂糖'
BRANDING_DIR = '/home/ubuntu/branding'
TARGET_DIR = os.path.join(BRANDING_DIR, 'sugar')
BACKUP_ROOT = '/mnt/d/ubuntu_/.cache/branding-backup'
HOMARR_DB = '/var/lib/docker/volumes/homarr_homarr-data/_data/db/db.sqlite'
HOMARR_BACKUP_DIR = '/mnt/d/ubuntu_/.cache/exports/homarr'
HOMARR_CONTAINER = 'homarr'
CSS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sugar-theme.css')
PURE_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sugar-pure.html')

BG_SOURCE = '8.png'
LOGO_SOURCE = '6.jpg'
PURE_ICON_SOURCE = '7.jpeg'

# 动图素材（放在 /home/ubuntu/branding/sugar/，由外部生成，脚本不负责制作）
# 存在时看板背景优先用 GIF，否则退回静态 bg.jpg
BG_ANIM = 'bg-anim.gif'
BG_ANIM_PORTRAIT = 'bg-anim-portrait.gif'

PURE_APP_ID = 'sugarpureapp0000000000001'
PURE_ITEM_ID = 'sugarpureitem000000000001'
PURE_HREF = '/branding/sugar/pure.html'

PRIMARY = '#d6336c'
SECONDARY = '#f783ac'


def fail(message: str) -> None:
    print('错误：' + message, file=sys.stderr)
    sys.exit(1)


def vertical_wash(size, top_alpha: float, bottom_alpha: float, color=(18, 7, 16)):
    """上下渐变的暗色遮罩，越往下越暗。"""
    width, height = size
    strip = Image.new('L', (1, height))
    for y in range(height):
        ratio = y / max(height - 1, 1)
        strip.putpixel((0, y), int(255 * (top_alpha + (bottom_alpha - top_alpha) * ratio)))
    return Image.merge('RGBA', (
        Image.new('L', size, color[0]),
        Image.new('L', size, color[1]),
        Image.new('L', size, color[2]),
        strip.resize(size),
    ))


def vignette(size, strength: float = 0.5):
    """四角压暗，中间保持通透。"""
    width, height = size
    small = Image.new('L', (64, 36), 0)
    draw = ImageDraw.Draw(small)
    # 用椭圆近似径向渐变：中心白、边缘黑，再反相做遮罩
    draw.ellipse((-width // 6, -height // 6, width + width // 6, height + height // 6), fill=255)
    mask = small.filter(ImageFilter.GaussianBlur(6)).resize(size, Image.LANCZOS)
    inverted = mask.point(lambda value: int((255 - value) * strength))
    layer = Image.new('RGBA', size, (10, 4, 10, 255))
    layer.putalpha(inverted)
    return layer


def build_background(source: str, target: str) -> None:
    image = Image.open(source).convert('RGB')
    image = ImageOps.fit(image, (1920, 1080), Image.LANCZOS, centering=(0.5, 0.32))
    image = image.filter(ImageFilter.GaussianBlur(1.2))
    image = ImageEnhance.Brightness(image).enhance(0.94)
    image = ImageEnhance.Color(image).enhance(1.05)
    image = image.convert('RGBA')
    image = Image.alpha_composite(image, vertical_wash(image.size, 0.06, 0.30))
    image = Image.alpha_composite(image, vignette(image.size, 0.30))
    image.convert('RGB').save(target, 'JPEG', quality=88, optimize=True, progressive=True)


def build_logo(source: str) -> Image.Image:
    image = Image.open(source).convert('RGB')
    width, height = image.size
    # 图 6 是 800×717 的正面白衬衫，按短边取正方形，保住发髻和肩线
    side = min(width, height)
    left = (width - side) // 2
    square = image.crop((left, 0, left + side, side))
    return ImageOps.fit(square, (1024, 1024), Image.LANCZOS)


def write_in_place(path: str, image: Image.Image) -> None:
    with open(path, 'wb') as handle:
        image.save(handle, 'PNG', optimize=True)


def round_corners(image: Image.Image, radius_ratio: float = 0.22) -> Image.Image:
    """切圆角，透明底，避免在浅色页头里出现一块硬邦邦的方形照片。"""
    image = image.convert('RGBA')
    size = image.size[0]
    radius = int(size * radius_ratio)
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    image.putalpha(mask)
    return image


def build_branding(source_dir: str) -> None:
    background_source = os.path.join(source_dir, BG_SOURCE)
    logo_source = os.path.join(source_dir, LOGO_SOURCE)
    for path in (background_source, logo_source):
        if not os.path.isfile(path):
            fail('找不到素材：' + path)

    os.makedirs(TARGET_DIR, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup_dir = os.path.join(BACKUP_ROOT, 'sugar-' + stamp)
    os.makedirs(backup_dir, exist_ok=True)
    for name in os.listdir(TARGET_DIR):
        source = os.path.join(TARGET_DIR, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(backup_dir, name))
    print('已备份旧素材 ->', backup_dir)

    build_background(background_source, os.path.join(TARGET_DIR, 'bg.jpg'))

    logo = build_logo(logo_source)
    rounded = round_corners(logo)
    targets = {
        'logo.png': rounded.resize((512, 512), Image.LANCZOS),
        'logo192.png': rounded.resize((192, 192), Image.LANCZOS),
        'avatar.png': rounded.resize((512, 512), Image.LANCZOS),
        'apple-touch-icon.png': rounded.resize((180, 180), Image.LANCZOS),
        'favicon-32.png': logo.resize((32, 32), Image.LANCZOS),
        'favicon-16.png': logo.resize((16, 16), Image.LANCZOS),
    }
    for name, image in targets.items():
        write_in_place(os.path.join(TARGET_DIR, name), image)

    with open(os.path.join(TARGET_DIR, 'favicon.ico'), 'wb') as handle:
        logo.save(handle, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    print('已生成素材：', ', '.join(sorted(os.listdir(TARGET_DIR))))


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(['docker', *args], check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def build_pure(source_dir: str) -> None:
    """纯享模式：一张干净的 1920×1080 原图 + 观感图标 + 独立 HTML 页面。"""
    image = Image.open(os.path.join(source_dir, BG_SOURCE)).convert('RGB')
    image = ImageOps.fit(image, (1920, 1080), Image.LANCZOS, centering=(0.5, 0.32))
    image = image.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=3))
    image = ImageEnhance.Brightness(image).enhance(1.02)
    image = ImageEnhance.Color(image).enhance(1.06)
    image.save(os.path.join(TARGET_DIR, 'pure.jpg'), 'JPEG', quality=90, optimize=True, progressive=True)

    icon_source = os.path.join(source_dir, PURE_ICON_SOURCE)
    if os.path.isfile(icon_source):
        icon = Image.open(icon_source).convert('RGB')
        width, height = icon.size
        side = min(width, height)
        icon = icon.crop(((width - side) // 2, 0, (width + side) // 2, side))
        icon = ImageOps.fit(icon, (512, 512), Image.LANCZOS)
        round_corners(icon).resize((192, 192), Image.LANCZOS).save(
            os.path.join(TARGET_DIR, 'pure-icon.png'), 'PNG', optimize=True
        )

    if not os.path.isfile(PURE_HTML):
        fail('未找到纯享模式页面：' + PURE_HTML)
    shutil.copy2(PURE_HTML, os.path.join(TARGET_DIR, 'pure.html'))

    # 全屏 PWA 外壳：board.html + board.json + sw.js
    for name in ('board.html', 'board.json', 'sw.js'):
        source = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(TARGET_DIR, name))


def ensure_pure_app(con: sqlite3.Connection) -> None:
    """在看板右下角补一张「纯享模式」卡片，已存在则跳过。"""
    board_id = con.execute('select id from board limit 1').fetchone()[0]
    con.execute(
        'insert into app (id, name, description, icon_url, href, ping_url) values (?, ?, ?, ?, ?, null)'
        ' on conflict(id) do update set name = excluded.name, icon_url = excluded.icon_url, href = excluded.href',
        (PURE_APP_ID, '纯享模式', '', '/branding/sugar/pure-icon.png', PURE_HREF),
    )
    advanced_json = json.dumps(
        {'json': {'title': None, 'customCssClasses': [], 'borderColor': ''}}, ensure_ascii=False
    )
    if not con.execute('select 1 from item where id = ?', (PURE_ITEM_ID,)).fetchone():
        options = {
            'json': {
                'appId': PURE_APP_ID,
                'openInNewTab': True,
                'showTitle': True,
                'descriptionDisplayMode': 'hidden',
                'layout': 'column',
                'pingEnabled': False,
            }
        }
        con.execute(
            'insert into item (id, board_id, kind, options, advanced_options) values (?, ?, ?, ?, ?)',
            (PURE_ITEM_ID, board_id, 'app', json.dumps(options, ensure_ascii=False), advanced_json),
        )
    con.execute('update item set advanced_options = ? where id = ?', (advanced_json, PURE_ITEM_ID))

    placements = [
        ('wy3wn5nbf8ksins1nx7hohgn', 5, 2, 1, 2),  # 桌面：最后一列空位
        ('qnca7lzjhdetsbriix41o8ie', 2, 3, 1, 1),  # 手机：第三列空位
    ]
    for layout_id, x, y, width, height in placements:
        exists = con.execute(
            'select 1 from item_layout where item_id = ? and layout_id = ?', (PURE_ITEM_ID, layout_id)
        ).fetchone()
        if exists:
            continue
        if not con.execute('select 1 from layout where id = ?', (layout_id,)).fetchone():
            continue
        con.execute(
            'insert into item_layout (item_id, section_id, layout_id, x_offset, y_offset, width, height)'
            ' values (?, ?, ?, ?, ?, ?, ?)',
            (PURE_ITEM_ID, 'jwbrjild6fjno38jfdvj69f5', layout_id, x, y, width, height),
        )


def update_homarr() -> None:
    if not os.path.exists(HOMARR_DB):
        fail('未找到 Homarr 数据库：' + HOMARR_DB)
    if not os.path.isfile(CSS_FILE):
        fail('未找到自定义 CSS：' + CSS_FILE)

    with open(CSS_FILE, encoding='utf-8') as handle:
        custom_css = handle.read()

    background_url = '/branding/sugar/' + BG_ANIM
    if not os.path.isfile(os.path.join(TARGET_DIR, BG_ANIM)):
        background_url = '/branding/sugar/bg.jpg'
        print('未找到 %s，背景退回静态 bg.jpg' % BG_ANIM)
    if not os.path.isfile(os.path.join(TARGET_DIR, BG_ANIM_PORTRAIT)):
        print('未找到 %s，手机竖屏仍用横屏背景' % BG_ANIM_PORTRAIT)

    running = docker('inspect', '-f', '{{.State.Running}}', HOMARR_CONTAINER, check=False).stdout.strip() == 'true'
    if running:
        docker('stop', HOMARR_CONTAINER)

    try:
        os.makedirs(HOMARR_BACKUP_DIR, exist_ok=True)
        shutil.copy2(HOMARR_DB, os.path.join(HOMARR_BACKUP_DIR, 'db-%s.sqlite' % time.strftime('%Y%m%d-%H%M%S')))

        con = sqlite3.connect(HOMARR_DB)
        con.execute(
            """update board set
                 background_image_url = ?,
                 background_image_attachment = 'fixed',
                 background_image_repeat = 'no-repeat',
                 background_image_size = 'cover',
                 logo_image_url = ?,
                 favicon_image_url = ?,
                 primary_color = ?,
                 secondary_color = ?,
                 opacity = 100,
                 item_radius = 'lg',
                 custom_css = ?""",
            (
                background_url,
                '/branding/sugar/logo192.png',
                '/branding/sugar/favicon-32.png',
                PRIMARY,
                SECONDARY,
                custom_css,
            ),
        )
        con.execute('update user set image = ?', ('/branding/sugar/avatar.png',))
        ensure_pure_app(con)

        row = con.execute("select value from serverSetting where setting_key = 'branding'").fetchone()
        if row:
            payload = json.loads(row[0])
            branding = payload.setdefault('json', {})
            branding.update({
                'logoImageUrl': '/branding/sugar/logo.png',
                'faviconImageUrl': '/branding/sugar/favicon-32.png',
                'primaryColor': PRIMARY,
                'secondaryColor': SECONDARY,
                'signInBackgroundImageUrl': background_url,
                'signInBackgroundOverlay': 0.62,
            })
            con.execute(
                "update serverSetting set value = ? where setting_key = 'branding'",
                (json.dumps(payload, ensure_ascii=False),),
            )
        con.commit()
        con.close()
        print('已更新 Homarr 看板背景 / logo / 主色 / 自定义 CSS，以及全站品牌色')
    finally:
        if running:
            docker('start', HOMARR_CONTAINER)


def main() -> None:
    source_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not os.path.isdir(source_dir):
        fail('找不到素材目录：' + source_dir)
    if not os.access(BRANDING_DIR, os.W_OK):
        fail('没有写权限：%s（请用 sudo 运行）' % BRANDING_DIR)

    build_branding(source_dir)
    build_pure(source_dir)
    update_homarr()

    print('\n完成。浏览器按 Ctrl+F5 强制刷新；想换回旧图可重跑 apply-avatar.py。')


if __name__ == '__main__':
    main()
