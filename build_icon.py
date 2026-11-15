"""build_icon.py — 生成应用图标 assets/app.ico

用 Pillow 画，不引入设计文件：底色 #1E4FA8，圆角方块，中间 "AE"，与侧栏品牌块同款。
打包脚本（build_win.py）与窗口快捷方式都用这个 ico。

    python build_icon.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

BLUE = (30, 79, 168, 255)          # #1E4FA8
WHITE = (255, 255, 255, 255)
SIZES = [16, 24, 32, 48, 64, 128, 256]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'assets', 'app.ico')

FONT_CANDIDATES = [
    r'C:\Windows\Fonts\msyhbd.ttc',        # 微软雅黑 Bold
    r'C:\Windows\Fonts\segoeuib.ttf',
    r'C:\Windows\Fonts\arialbd.ttf',
]


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render(size):
    """在 4 倍尺寸上画再缩小：小尺寸下的圆角与字形边缘才不毛糙。"""
    ss = 4
    canvas = size * ss
    img = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(canvas * 0.22)
    d.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=radius, fill=BLUE)

    text = 'AE'
    f = _font(int(canvas * 0.44))
    box = d.textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((canvas - w) / 2 - box[0], (canvas - h) / 2 - box[1]), text, font=f, fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    frames = [render(s) for s in SIZES]
    frames[-1].save(OUT, format='ICO', sizes=[(s, s) for s in SIZES])
    print('已生成 %s（%d 个尺寸：%s）' % (OUT, len(SIZES), ', '.join(str(s) for s in SIZES)))


if __name__ == '__main__':
    main()
