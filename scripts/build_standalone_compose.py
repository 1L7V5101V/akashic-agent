#!/usr/bin/env python3
"""从仓库 Compose 生成只使用固定发行镜像的独立启动附件。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
# 浏览器沙箱策略与附件同目录，作为 Compose 的相对路径一起分发。
SANDBOX_PROFILE = ROOT / 'docker/host-runtime/chromium-seccomp.json'
SANDBOX_OPTION = 'seccomp=./' + SANDBOX_PROFILE.name


def is_seccomp(option: str) -> bool:
    """识别 Compose 支持的 seccomp= 与 seccomp: 两种写法。"""
    return option.split('=', 1)[0].split(':', 1)[0] == 'seccomp'


def main() -> None:
    """复用同一份运行配置，仅替换镜像的取得方式。"""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument('--image', required=True, help='带 sha256 digest 的发行镜像')
    _ = parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch(r'ghcr\.io/[a-z0-9_./-]+@sha256:[0-9a-f]{64}', args.image) is None:
        parser.error('--image 必须是固定 digest 的 GHCR 镜像')
    # 1. 不展开端口变量，让下载附件的人仍能通过 AKASHIC_PORT 选择端口。
    result = subprocess.run(
        ['docker', 'compose', '-f', str(ROOT / 'compose.yaml'), 'config',
         '--no-interpolate', '--no-normalize', '--format', 'json'],
        check=True, capture_output=True, text=True,
    )
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f'docker compose config 输出不是合法 JSON：{error}') from error
    service = document['services']['akashic']
    del service['build']
    service['image'] = args.image
    # 2. 附件里没有源码目录：沙箱策略改成同目录相对路径，并随附件一起复制。
    options = service.get('security_opt', [])
    if not any(is_seccomp(option) for option in options):
        parser.error('运行配置缺少浏览器沙箱策略')
    service['security_opt'] = [
        SANDBOX_OPTION if is_seccomp(option) else option for option in options]
    try:
        json.loads(SANDBOX_PROFILE.read_text())
    except json.JSONDecodeError as error:
        parser.error(f'浏览器沙箱策略不是合法 JSON：{error}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for source in (SANDBOX_PROFILE, SANDBOX_PROFILE.with_suffix('.LICENSE')):
        (args.output.parent / source.name).write_bytes(source.read_bytes())
    # 3. JSON 也是合法 YAML；附件没有源码目录、构建参数或额外环境文件依赖。
    with args.output.open('x') as output:
        output.write(json.dumps(document, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
