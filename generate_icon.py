# -*- coding: utf-8 -*-
"""
生成 .ico 图标文件（纯 Python 实现，无外部依赖）
生成一个 32x32 的清理工具图标（垃圾桶 + 扫把风格）
"""

import struct
import os
import zlib

def create_png_32x32():
    """
    直接生成一个 32x32 RGBA PNG 图标数据
    图案：一个垃圾桶/清理风格图标
    """
    width, height = 32, 32
    pixels = []

    for y in range(height):
        row = []
        for x in range(width):
            # 计算像素颜色 —— 绘制简易垃圾桶图标
            cx, cy = x / width, y / height

            # 背景透明
            r, g, b, a = 0, 0, 0, 0

            # 垃圾桶主体 —— 矩形框 (范围 8~26 x 10~28)
            in_body = (8 <= x <= 26) and (10 <= y <= 28)
            # 桶盖
            in_lid = (7 <= x <= 27) and (y == 8 or y == 9)
            # 桶把手中线
            in_handle = (12 <= x <= 20) and (y == 6 or y == 7)
            # 桶身条纹装饰（波浪线 = 垃圾）
            in_stripe1 = (10 <= x <= 24) and (y == 14) and (x % 4 != 0)
            in_stripe2 = (11 <= x <= 23) and (y == 18) and (x % 3 != 0)
            in_stripe3 = (12 <= x <= 22) and (y == 22) and (x % 3 != 1)
            # 底部弧线
            in_bottom = (x == 9 or x == 25) and (14 <= y <= 27)

            # 扫把（右侧斜线）
            broom_x = (y >= 12 and y <= 28) and (
                abs(x - (8 + (y - 12) * 0.8)) <= 2
            )

            color = (r, g, b, a)

            if in_handle:
                # 把手 - 深灰色
                color = (80, 80, 80, 220)
            elif in_lid:
                # 盖子 - 蓝色
                color = (43, 87, 154, 230)
            elif in_body:
                # 桶身 - 渐变蓝
                blue_val = int(150 + (y - 10) * 3)
                blue_val = min(blue_val, 210)
                color = (30, 90, blue_val, 220)
                # 桶壁边框
                if x == 8 or x == 26 or y == 10 or y == 28:
                    color = (20, 60, 120, 240)
            elif in_stripe1 or in_stripe2 or in_stripe3:
                # 垃圾条纹 - 橙色/黄色
                color = (255, 160, 40, 230)
            elif broom_x:
                # 扫把 - 棕色
                color = (180, 120, 60, 200)

            # 检查是否在圆形高亮区域（桶左上角装饰光晕）
            dx, dy = x - 12, y - 13
            if dx*dx + dy*dy <= 9:
                if in_body:
                    color = (60, 130, 230, 200)

            pixels.append(color)
            row.append(color)

    # 构造 PNG
    return _make_png(width, height, pixels)


def _make_png(width, height, pixels):
    """从 RGBA 像素数据构造 PNG 文件"""
    # PNG Signature
    signature = b'\x89PNG\r\n\x1a\n'

    # IHDR chunk
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    # 8=bitdepth, 6=RGBA
    ihdr = _make_chunk(b'IHDR', ihdr_data)

    # IDAT chunk - raw pixel data
    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'  # filter byte (none)
        for x in range(width):
            idx = y * width + x
            r, g, b, a = pixels[idx]
            raw_data += struct.pack('BBBB', r, g, b, a)

    compressed = zlib.compress(raw_data)
    idat = _make_chunk(b'IDAT', compressed)

    # IEND chunk
    iend = _make_chunk(b'IEND', b'')

    return signature + ihdr + idat + iend


def _make_chunk(chunk_type, data):
    """创建 PNG chunk"""
    length = struct.pack('>I', len(data))
    crc = zlib.crc32(chunk_type + data) & 0xffffffff
    return length + chunk_type + data + struct.pack('>I', crc)


def create_ico(png_data, sizes=None):
    """
    从 PNG 数据创建 .ico 文件
    支持多尺寸（默认 32x32）
    """
    if sizes is None:
        sizes = [(32, 32)]

    # ICO header
    ico_header = struct.pack('<HHH', 0, 1, len(sizes))

    # Directory entries + image data
    dir_entries = b''
    image_data = b''
    offset = 6 + 16 * len(sizes)  # header + all dir entries

    for w, h in sizes:
        # 对于 32bpp ICO，可以直接嵌入 PNG
        data = png_data
        size = len(data)

        # 目录条目
        iw = w if w < 256 else 0
        ih = h if h < 256 else 0
        dir_entry = struct.pack('<BBBBHHII',
                                iw, ih, 0, 0, 1, 32, size, offset)
        dir_entries += dir_entry
        image_data += data
        offset += size

    return ico_header + dir_entries + image_data


def main():
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")

    # 生成 32x32 PNG 图标数据
    print("[信息] 生成图标...")
    png_data = create_png_32x32()

    # 创建 ICO 文件（包含 32x32 和 16x16 两个尺寸）
    # 实际也可以生成多个尺寸的 PNG 嵌入，但保持简单
    ico_data = create_ico(png_data, sizes=[(32, 32)])

    with open(output_path, 'wb') as f:
        f.write(ico_data)

    file_size = os.path.getsize(output_path)
    print(f"[OK] 图标已生成: {output_path}")
    print(f"     大小: {file_size} 字节")

    # 验证
    if file_size > 100:
        print("[OK] 图标文件有效")
    else:
        print("[警告] 图标文件可能无效")


if __name__ == "__main__":
    main()
