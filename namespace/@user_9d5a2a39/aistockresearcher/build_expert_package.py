# -*- coding: utf-8 -*-
"""build_expert_package.py — WorkBuddy 专家包构建脚本（stock-researcher）

按 open.workbuddy.cn/docs/expert 规范组装专家包：
  1. 组装结构到临时目录：.codebuddy-plugin/plugin.json + agents/
     + skills/stock-researcher/（SKILL.md + scripts/ + stock_researcher/
     + tests/ + config/ + pkg/ + pytest.ini + README.md + requirements.txt + runtests.py）
  2. 纯标准库程序化生成 512×512 股票研究主题头像（≤500KB，仓库内不留二进制）
  3. 规范自检：字段完整性/字数/标签数/提示词数/头像规格/版本链一致/
     scripts 完整性/tests 完整性
  4. 打包 zip：内含以专家 name 命名的单一顶层目录（平台按
     <name>/.codebuddy-plugin/plugin.json 解析；缺此顶层目录会报"缺少 plugin.json"）
  5. 产出 D:\\claude 开发\\专家包\\stock-researcher-expert-<版本>.zip，
     并重新打开 zip 校验顶层结构/关键文件/垃圾文件/目录深度

用法：python build_expert_package.py
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PLUGIN_NAME = 'stock-researcher'
OUT_DIR = r'D:\claude 开发\专家包'

SKILL_COPY_ITEMS = ['SKILL.md', 'scripts', 'stock_researcher', 'tests', 'config',
                    'pkg', 'pytest.ini', 'README.md', 'requirements.txt', 'runtests.py']
PLUGIN_FIELDS_REQUIRED = ['name', 'expertType', 'version', 'description', 'author',
                          'agents', 'agentName', 'displayName',
                          'profession', 'displayDescription', 'avatar', 'categoryId',
                          'defaultInitPrompt', 'plugin', 'tags', 'quickPrompts']
IGNORE_PATTERNS = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '.pytest_cache', 'outputs', 'workspace',
    '*.tmp', '.gitignore', '.git', '.DS_Store', '__MACOSX')


# ---------------------------------------------------------------- PNG 头像
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))


def write_png(path: str, w: int, h: int, buf: bytearray) -> None:
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += buf[y * stride:(y + 1) * stride]
    png = (b'\x89PNG\r\n\x1a\n'
           + _png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + _png_chunk(b'IDAT', zlib.compress(bytes(raw), 9))
           + _png_chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


def generate_avatar(path: str, size: int = 512) -> None:
    """股票研究主题头像：深蓝渐变底 + 全球市场图表 + 分析元素 + 上扬趋势线。"""
    W = H = size
    s = float(size)
    cx, cy = size / 2.0, size / 2.0
    buf = bytearray(W * H * 3)

    def blend(x: float, y: float, rgb, a: float) -> None:
        xi, yi = int(x), int(y)
        if 0 <= xi < W and 0 <= yi < H:
            i = (yi * W + xi) * 3
            for k in range(3):
                buf[i + k] = int(buf[i + k] * (1 - a) + rgb[k] * a)

    def blend_disc(xc: float, yc: float, r: float, rgb, a: float) -> None:
        for yy in range(int(yc - r) - 1, int(yc + r) + 2):
            for xx in range(int(xc - r) - 1, int(xc + r) + 2):
                d = math.hypot(xx - xc, yy - yc)
                if d <= r:
                    blend(xx, yy, rgb, a)

    def draw_line(x0, y0, x1, y1, rgb, a, width: float = 2.0) -> None:
        steps = max(2, int(math.hypot(x1 - x0, y1 - y0) * 2))
        for i in range(steps + 1):
            t = i / steps
            xc, yc = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            r = width / 2.0
            for oy in range(-int(r) - 1, int(r) + 2):
                for ox in range(-int(r) - 1, int(r) + 2):
                    if ox * ox + oy * oy <= r * r:
                        blend(xc + ox, yc + oy, rgb, a)

    # 配色：深蓝渐变 + 金融青 + 白色 + 绿色
    top, bottom = (15, 25, 55), (25, 40, 75)
    cyan, light_cyan = (70, 180, 220), (110, 200, 240)
    white = (240, 248, 255)
    green = (70, 195, 115)
    red = (215, 75, 75)
    gold = (220, 185, 75)

    # 背景渐变 + 中央柔光
    for y in range(H):
        t = y / (H - 1)
        base = tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3))
        row = y * W * 3
        for x in range(W):
            d = math.hypot(x - cx, y - cy)
            glow = math.exp(-(d / (s * 0.48)) ** 2) * 0.15
            i = row + x * 3
            for k in range(3):
                buf[i + k] = int(base[k] + (cyan[k] - base[k]) * glow)

    # 全球市场图表元素（多条趋势线）
    # A 股趋势线
    poly_a = [(0.10 * s, 0.68 * s), (0.22 * s, 0.55 * s), (0.35 * s, 0.60 * s),
              (0.48 * s, 0.45 * s), (0.60 * s, 0.38 * s), (0.72 * s, 0.30 * s)]
    for p0, p1 in zip(poly_a, poly_a[1:]):
        draw_line(p0[0], p0[1], p1[0], p1[1], cyan, 0.7, 2.5)
    for px, py in poly_a:
        blend_disc(px, py, 3.5, light_cyan, 0.8)

    # 美股趋势线
    poly_us = [(0.15 * s, 0.72 * s), (0.28 * s, 0.62 * s), (0.40 * s, 0.65 * s),
               (0.52 * s, 0.50 * s), (0.65 * s, 0.42 * s), (0.78 * s, 0.35 * s)]
    for p0, p1 in zip(poly_us, poly_us[1:]):
        draw_line(p0[0], p0[1], p1[0], p1[1], green, 0.6, 2.0)
    for px, py in poly_us:
        blend_disc(px, py, 3.0, green, 0.7)

    # 港股趋势线
    poly_hk = [(0.12 * s, 0.75 * s), (0.25 * s, 0.68 * s), (0.38 * s, 0.70 * s),
               (0.50 * s, 0.58 * s), (0.62 * s, 0.52 * s), (0.75 * s, 0.42 * s)]
    for p0, p1 in zip(poly_hk, poly_hk[1:]):
        draw_line(p0[0], p0[1], p1[0], p1[1], gold, 0.5, 1.8)

    # 中央地球/全球符号
    earth_x, earth_y, earth_r = 0.38 * s, 0.38 * s, 0.15 * s
    blend_disc(earth_x, earth_y, earth_r, cyan, 0.3)
    for ring_r, ring_a in ((earth_r, 0.6), (earth_r * 0.7, 0.4)):
        for ang in range(0, 3600):
            a = math.pi / 180 * (ang / 10.0)
            blend(earth_x + ring_r * math.cos(a), earth_y + ring_r * math.sin(a),
                  white, ring_a * 0.3)

    # 分析符号（放大镜）
    mag_x, mag_y, mag_r = 0.68 * s, 0.68 * s, 0.12 * s
    for ring_r, ring_a in ((mag_r, 0.7), (mag_r - 2, 0.35)):
        for ang in range(0, 3600):
            a = math.pi / 180 * (ang / 10.0)
            blend(mag_x + ring_r * math.cos(a), mag_y + ring_r * math.sin(a),
                  white, ring_a)
    hx, hy = mag_x + mag_r * 0.7, mag_y + mag_r * 0.7
    draw_line(hx, hy, hx + 0.08 * s, hy + 0.08 * s, white, 0.7, 4.0)

    # 星光点缀
    rng = random.Random(20260908)
    for _ in range(14):
        x, y = rng.uniform(10, W - 10), rng.uniform(10, H - 10)
        bright = rng.uniform(0.35, 0.85)
        col = tuple(int(200 + 55 * bright) for _ in range(3))
        for ox in range(-2, 3):
            for oy in range(-2, 3):
                dd = math.hypot(ox, oy)
                if dd <= 2:
                    blend(x + ox, y + oy, col, bright * (1 - dd / 2.6))
        if bright > 0.7:
            for step in range(1, 4):
                a = bright * (1 - step / 4) * 0.5
                blend(x + step, y, col, a)
                blend(x - step, y, col, a)
                blend(x, y + step, col, a)
                blend(x, y - step, col, a)

    write_png(path, W, H, buf)


# ---------------------------------------------------------------- 版本/组装
def skill_version() -> str:
    """从 SKILL.md 读取 version。"""
    skill_path = os.path.join(ROOT, 'SKILL.md')
    with open(skill_path, encoding='utf-8') as f:
        content = f.read()
    m = re.search(r'^version:\s*["\']?([^"\'}\s]+)', content, re.MULTILINE)
    assert m, '无法读取 SKILL.md 的 version'
    return m.group(1)


def assemble(staging: str) -> dict:
    """复制源文件 + skill 全量 + 生成头像 → 返回 plugin.json 内容。"""
    # 复制 .codebuddy-plugin/plugin.json 和 agents/
    for rel in (os.path.join('.codebuddy-plugin', 'plugin.json'),
                os.path.join('agents', PLUGIN_NAME + '.md')):
        dst = os.path.join(staging, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), dst)

    # 复制 skill 文件到 skills/<name>/
    skill_dst = os.path.join(staging, 'skills', PLUGIN_NAME)
    os.makedirs(skill_dst, exist_ok=True)
    for item in SKILL_COPY_ITEMS:
        src = os.path.join(ROOT, item)
        dst = os.path.join(skill_dst, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=IGNORE_PATTERNS)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)

    # 生成股票研究主题头像（512×512 PNG，≤500KB）
    avatar_dir = os.path.join(staging, 'avatars')
    os.makedirs(avatar_dir, exist_ok=True)
    generate_avatar(os.path.join(avatar_dir, 'expert.png'))

    with open(os.path.join(staging, '.codebuddy-plugin', 'plugin.json'),
              encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------------- 自检
def validate(staging: str, plugin: dict) -> list:
    """规范自检，返回 [检查项, 通过] 列表；失败即 AssertionError。"""
    checks = []

    def check(name: str, cond: bool, detail: str = '') -> None:
        assert cond, f'自检失败：{name} {detail}'
        checks.append((name, detail or 'OK'))

    skill_ver = skill_version()

    check('name 小写字母+连字符',
          re.fullmatch(r'[a-z0-9-]+', plugin['name']) is not None, plugin['name'])
    check('expertType=agent', plugin['expertType'] == 'agent')
    check('plugin=name', plugin['plugin'] == plugin['name'])
    check('版本链一致（plugin/SKILL.md）',
          plugin['version'] == skill_ver,
          f"plugin={plugin['version']} skill={skill_ver}")
    for k in PLUGIN_FIELDS_REQUIRED:
        check(f'字段齐全 {k}', k in plugin and plugin[k] not in (None, '', [], {}))
    check('agents 字符串路径数组',
          isinstance(plugin['agents'], list)
          and all(isinstance(a, str) for a in plugin['agents'])
          and len(plugin['agents']) > 0)
    check('agents/<agentName>.md 存在',
          os.path.isfile(os.path.join(staging, 'agents', plugin['agentName'] + '.md')))
    check('categoryId 行业分类', re.fullmatch(r'\d{2}-[A-Za-z]+', plugin['categoryId'])
          is not None, plugin['categoryId'])
    tags = plugin['tags']
    check('tags 恰好 3 个', isinstance(tags, list) and len(tags) == 3, str(tags))
    check('每条 tags 含 en/zh',
          all(isinstance(t, dict) and t.get('en') and t.get('zh') for t in tags))
    qp = plugin['quickPrompts']
    check('quickPrompts 恰好 3 条', isinstance(qp, list) and len(qp) == 3)
    check('每条 quickPrompts 含 en/zh',
          all(isinstance(q, dict) and q.get('en') and q.get('zh') for q in qp))
    check('defaultInitPrompt=quickPrompts[0]', plugin['defaultInitPrompt'] == qp[0])
    zh = plugin['displayDescription']['zh']
    check('displayDescription.zh 40-50 字', 40 <= len(zh) <= 50, f'{len(zh)} 字')
    for k in ('displayName', 'profession', 'displayDescription'):
        check(f'{k} 含 en/zh',
              isinstance(plugin[k], dict) and plugin[k].get('en') and plugin[k].get('zh'))
    check('author 含 name/email',
          isinstance(plugin['author'], dict) and plugin['author'].get('name')
          and plugin['author'].get('email'))

    # 头像：512×512 PNG（IHDR）且 ≤500KB
    avatar = os.path.join(staging, plugin['avatar'])
    check('头像存在', os.path.isfile(avatar), plugin['avatar'])
    size_bytes = os.path.getsize(avatar)
    check('头像 ≤500KB', size_bytes <= 500 * 1024, f'{size_bytes // 1024}KB')
    with open(avatar, 'rb') as f:
        head = f.read(24)
    w, h = struct.unpack('>II', head[16:24])
    check('头像 512×512 PNG', (w, h) == (512, 512) and head[:8] == b'\x89PNG\r\n\x1a\n',
          f'{w}x{h}')

    # agent 提示词 frontmatter 要点
    with open(os.path.join(staging, 'agents', plugin['agentName'] + '.md'),
              encoding='utf-8') as f:
        agent_md = f.read()
    check('agent frontmatter name', f'name: {PLUGIN_NAME}' in agent_md)
    check('agent 免责声明', '免责' in agent_md or '投资建议' in agent_md)
    check('agent 核心约束', '约束' in agent_md or 'constraint' in agent_md.lower())

    # scripts 完整性
    skill_dir = os.path.join(staging, 'skills', PLUGIN_NAME)
    scripts_dir = os.path.join(skill_dir, 'scripts')
    expected_scripts = ['stock_predict.py', 'market_overview.py']
    for script in expected_scripts:
        check(f'scripts/{script}', os.path.isfile(os.path.join(scripts_dir, script)))

    # stock_researcher 核心包完整性
    pkg_dir = os.path.join(skill_dir, 'stock_researcher')
    expected_modules = ['__init__.py', 'quantitative_engine.py', 'agents_master_council.py',
                        'voice_interface.py', 'knowledge_sync.py']
    for mod in expected_modules:
        check(f'stock_researcher/{mod}', os.path.isfile(os.path.join(pkg_dir, mod)))

    # tests 完整性
    tests_dir = os.path.join(skill_dir, 'tests')
    expected_tests = ['conftest.py', 'test_quant_v71.py']
    for test in expected_tests:
        check(f'tests/{test}', os.path.isfile(os.path.join(tests_dir, test)))

    # 根文件
    for fn in ('SKILL.md', 'pytest.ini', 'README.md', 'requirements.txt', 'runtests.py'):
        check(f'skill 根文件 {fn}', os.path.isfile(os.path.join(skill_dir, fn)))

    return checks


def verify_zip(zip_path: str, pkg_folder: str) -> list:
    """重新打开产出的 zip，校验平台解析所需的顶层结构。"""
    checks = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        manifest = f'{pkg_folder}/.codebuddy-plugin/plugin.json'
        assert manifest in names, (
            f'zip 缺少顶层清单 {manifest}；现有根项：'
            f'{sorted({n.split("/")[0] for n in names})}')
        checks.append((f'zip 顶层目录 {pkg_folder}/', 'OK'))
        checks.append((f'zip 清单 {manifest}', 'OK'))
        key_rels = [
            f'agents/{PLUGIN_NAME}.md',
            'avatars/expert.png',
            f'skills/{PLUGIN_NAME}/SKILL.md',
            f'skills/{PLUGIN_NAME}/scripts/stock_predict.py',
            f'skills/{PLUGIN_NAME}/stock_researcher/__init__.py',
            f'skills/{PLUGIN_NAME}/stock_researcher/quantitative_engine.py',
            f'skills/{PLUGIN_NAME}/tests/conftest.py',
            f'skills/{PLUGIN_NAME}/pytest.ini',
        ]
        for rel in key_rels:
            assert f'{pkg_folder}/{rel}' in names, f'zip 缺少 {pkg_folder}/{rel}'
        checks.append(('zip 关键文件齐备', 'agents/avatars/skills 全量'))
        junk = [n for n in names
                if '.DS_Store' in n or '__MACOSX' in n or n.endswith('.pyc')
                or '__pycache__' in n or '.pytest_cache' in n
                or n.endswith('.jpg') or n.endswith('.jpeg')
                or n.endswith('.gif') or n.endswith('.ico') or n.endswith('.svg')]
        assert not junk, f'zip 含垃圾文件：{junk}'
        checks.append(('zip 无 .DS_Store/__MACOSX__/.pyc/__pycache__', 'OK'))
        roots = {n.split('/')[0] for n in names}
        assert roots == {pkg_folder}, f'zip 顶层应仅含 {pkg_folder}/，实际：{roots}'
        checks.append(('zip 仅单一顶层目录', pkg_folder))
        max_depth = max(n.count('/') for n in names) + 1
        assert max_depth <= 6, f'zip 内目录层级过深（{max_depth} 段），防平台层级超限'
        checks.append(('zip 目录深度安全', f'最深 {max_depth} 段'))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser(description='构建 WorkBuddy 专家包（stock-researcher）')
    args = ap.parse_args()

    version = skill_version()
    staging = os.path.join(tempfile.gettempdir(), f'{PLUGIN_NAME}-expert-{version}')
    if os.path.exists(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)

    plugin = assemble(staging)
    checks = validate(staging, plugin)

    pkg_folder = plugin['name']

    os.makedirs(OUT_DIR, exist_ok=True)
    zip_path = os.path.join(OUT_DIR, f'{PLUGIN_NAME}-expert-{version}.zip')

    skip_names = {'__pycache__', '.DS_Store', '__MACOSX', '.pytest_cache'}
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(staging):
            dirnames[:] = [d for d in dirnames if d not in skip_names]
            for fn in filenames:
                if fn in skip_names or fn.endswith('.pyc'):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, staging).replace(os.sep, '/')
                zf.write(full, f'{pkg_folder}/{rel}')

    checks += verify_zip(zip_path, pkg_folder)

    print(f'✅ 专家包构建完成：{zip_path}（{os.path.getsize(zip_path) // 1024}KB）')
    print(f'   zip 内顶层目录：{pkg_folder}/'
          f'（清单 {pkg_folder}/.codebuddy-plugin/plugin.json）')
    print(f'   暂存目录（保留以便检查包结构，可手动清理）：{staging}')
    print(f'   共 {len(checks)} 项规范自检全部通过：')
    for name, detail in checks:
        print(f'   - {name}：{detail}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
