#!/usr/bin/env python3
"""检测 SVG 文本叠字：估算字符渲染宽度，判定同行水平+垂直真实重叠。

针对 svg_to_pptx 渲染特性（不支持 dx，text-anchor=start/middle/end），
提取所有 <text> 的坐标/字号/锚点，按字符类型估算实际渲染宽度，
再用真实字符盒（top=y-0.8fs, bottom=y+0.2fs）判定垂直重叠——
避免误判 KPI 卡「大数字在上 + 小标签在下」的合理设计。

用法:
  python3 tools/check_overlap.py                       # 默认检测 ./svg_output
  python3 tools/check_overlap.py <svg_dir>             # 检测目录下所有 .svg
  python3 tools/check_overlap.py <file.svg>            # 检测单个文件
  python3 tools/check_overlap.py <dir> -v              # 详细模式（显示每个文件）

退出码: 0 = 无叠字, 1 = 有叠字（便于 export.sh / CI 集成）
"""
import argparse
import os
import re
import sys
import glob


def char_width(ch, fs):
    """估算单字符渲染宽度（微软雅黑/Arial 度量近似）。"""
    if ch in ' \t':
        return fs * 0.25
    if '一' <= ch <= '鿿':        # CJK 统一表意
        return fs * 1.0
    if '　' <= ch <= '〿':        # CJK 标点
        return fs * 1.0
    if '＀' <= ch <= '￯':        # 全角字符
        return fs * 1.0
    if ch in "ijl|.,:;'!I":
        return fs * 0.3
    if ch in 'mwMW@':
        return fs * 0.75
    if ch.isdigit() or ch.isupper():
        return fs * 0.6
    return fs * 0.55


def text_width(s, fs):
    return sum(char_width(c, fs) for c in s)


def parse_attrs(tag):
    """从 <text ...> 标签提取属性字典。"""
    attrs = {}
    for m in re.finditer(r'(\w[\w-]*)\s*=\s*"([^"]*)"', tag):
        attrs[m.group(1)] = m.group(2)
    for m in re.finditer(r"(\w[\w-]*)\s*=\s*'([^']*)'", tag):
        attrs[m.group(1)] = m.group(2)
    return attrs


def extract_texts(svg_path):
    """提取所有 <text> 元素的渲染信息（含 bbox）。"""
    with open(svg_path, 'r', encoding='utf-8') as f:
        content = f.read()
    results = []
    for m in re.finditer(r'<text\b([^>]*)>(.*?)</text>', content, re.S):
        attrs = parse_attrs(m.group(1))
        text = re.sub(r'<[^>]+>', '', m.group(2))
        text = (text.replace('&amp;', '&').replace('&lt;', '<')
                    .replace('&gt;', '>').replace('&#160;', ' ')
                    .replace('&nbsp;', ' ')).strip()
        if not text or 'x' not in attrs or 'y' not in attrs:
            continue
        try:
            x, y = float(attrs['x']), float(attrs['y'])
        except ValueError:
            continue
        fs = float(attrs.get('font-size', '16'))
        anchor = attrs.get('text-anchor', 'start')
        w = text_width(text, fs)
        if anchor == 'middle':
            left, right = x - w / 2, x + w / 2
        elif anchor == 'end':
            left, right = x - w, x
        else:
            left, right = x, x + w
        results.append({
            'text': text, 'x': x, 'y': y, 'fs': fs, 'anchor': anchor,
            'left': left, 'right': right,
            'top': y - fs * 0.80, 'bottom': y + fs * 0.20,
        })
    return results


def check_file(svg_path):
    """检测单文件，返回重叠对列表（真实字符盒垂直+水平同时相交）。"""
    texts = extract_texts(svg_path)
    overlaps = []
    n = len(texts)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = texts[i], texts[j]
            v_overlap = min(a['bottom'], b['bottom']) - max(a['top'], b['top'])
            if v_overlap < 1:
                continue
            h_overlap = min(a['right'], b['right']) - max(a['left'], b['left'])
            if h_overlap < 2:
                continue
            overlaps.append((a, b, h_overlap, v_overlap))
    return overlaps


def main():
    ap = argparse.ArgumentParser(description='SVG 文本叠字检测')
    ap.add_argument('target', nargs='?', default='./svg_output',
                    help='SVG 目录或单文件（默认 ./svg_output）')
    ap.add_argument('-v', '--verbose', action='store_true', help='显示每个文件的检测状态')
    args = ap.parse_args()

    if os.path.isdir(args.target):
        files = sorted(glob.glob(os.path.join(args.target, '*.svg')))
    elif os.path.isfile(args.target):
        files = [args.target]
    else:
        print(f'✗ 目标不存在: {args.target}', file=sys.stderr)
        return 2

    if not files:
        print(f'✗ 未找到 .svg 文件: {args.target}', file=sys.stderr)
        return 2

    total = 0
    for f in files:
        ovs = check_file(f)
        if ovs:
            total += len(ovs)
            print(f"\n=== {os.path.basename(f)} ({len(ovs)} 处) ===")
            for a, b, ho, vo in ovs:
                print(f"  y≈{a['y']:.0f}/{b['y']:.0f} 水平重叠{ho:.0f}px 垂直重叠{vo:.0f}px:")
                print(f"    「{a['text'][:30]}」[{a['left']:.0f}-{a['right']:.0f}] fs={a['fs']:.0f}")
                print(f"    「{b['text'][:30]}」[{b['left']:.0f}-{b['right']:.0f}] fs={b['fs']:.0f}")
        elif args.verbose:
            print(f"  ✓ {os.path.basename(f)} 无叠字")

    if total == 0:
        print(f'✓ {len(files)} 个文件，0 处叠字')
        return 0
    print(f'\n总计：{total} 处叠字（{len(files)} 个文件）')
    return 1


if __name__ == '__main__':
    sys.exit(main())
