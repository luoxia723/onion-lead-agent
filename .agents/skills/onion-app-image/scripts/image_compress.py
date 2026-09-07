#!/usr/bin/env python3
"""
image_compress.py - Pillow 压缩图片到目标 KB。

# 使用示例

  python3 image_compress.py \\
    /tmp/in.png /tmp/out.jpg \\
    --target-kb 200

# 策略

  1. 若传 target_width/target_height，先按 cover 居中裁切到目标尺寸
  2. 再转 JPG（去 alpha），从 quality=85 起逐步降低直到达标
  3. 有精确目标宽高时始终保持该像素尺寸，不能为减小体积继续缩图
  4. 未指定精确宽高时才允许按 0.9 逐级缩小，最多 10 轮
  5. 无法同时满足尺寸和体积时明确失败，不留下假成功文件

# 退出码

  0: 成功
  1: 输入文件不存在 / 不可读
  2: 压缩失败（无法满足目标尺寸/体积）
"""

import argparse
import os
import sys
from typing import Optional

try:
    from PIL import Image
except ImportError:
    print("❌ 需要安装 Pillow：pip install Pillow", file=sys.stderr)
    sys.exit(1)


def resize_cover(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """Resize to cover target dimensions, then center-crop exactly."""
    if target_width <= 0 or target_height <= 0:
        raise ValueError("target width/height must be positive")
    scale = max(target_width / img.width, target_height / img.height)
    resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = max(0, (resized.width - target_width) // 2)
    top = max(0, (resized.height - target_height) // 2)
    return resized.crop((left, top, left + target_width, top + target_height))


def compress(
    input_path: str,
    output_path: str,
    target_kb: int = 200,
    target_width: Optional[int] = None,
    target_height: Optional[int] = None,
) -> str:
    """压缩到目标 KB。返回最终输出路径。"""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input not found: {input_path}")
    if target_kb <= 0:
        raise ValueError("target_kb must be positive")
    if bool(target_width) != bool(target_height):
        raise ValueError("target_width and target_height must be provided together")

    img = Image.open(input_path).convert("RGB")  # PNG → RGB（去 alpha）
    if target_width and target_height:
        img = resize_cover(img, target_width, target_height)

    output = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    temp_output = output + ".tmp.jpg"
    scales = [1.0] if target_width and target_height else [0.9**index for index in range(10)]

    try:
        for scale in scales:
            if scale < 1.0:
                new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
                scaled = img.resize(new_size, Image.LANCZOS)
            else:
                scaled = img

            for quality in range(85, 24, -5):
                scaled.save(temp_output, "JPEG", quality=quality, optimize=True, subsampling=2)
                size_kb = os.path.getsize(temp_output) / 1024
                if size_kb <= target_kb:
                    os.replace(temp_output, output)
                    print(
                        f"✅ {input_path} → {output} "
                        f"({scaled.width}x{scaled.height}, {size_kb:.1f} KB, q={quality}, scale={scale:.2f})"
                    )
                    return output
    finally:
        if os.path.exists(temp_output):
            os.unlink(temp_output)

    exact = f"{target_width}x{target_height}" if target_width and target_height else "未指定"
    raise ValueError(f"cannot satisfy target_kb={target_kb} at exact_size={exact}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="输入图片路径")
    parser.add_argument("output", help="输出图片路径（.jpg）")
    parser.add_argument("--target-kb", type=int, default=200, help="目标大小（KB）")
    parser.add_argument("--target-width", type=int, help="导出目标宽度")
    parser.add_argument("--target-height", type=int, help="导出目标高度")
    args = parser.parse_args()

    try:
        compress(args.input, args.output, args.target_kb, args.target_width, args.target_height)
        sys.exit(0)
    except FileNotFoundError as e:
        print(f"🔴 {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"🔴 压缩失败：{e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
