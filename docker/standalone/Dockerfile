FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm AS source
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
# 仓库地址可覆盖：默认为上游，fork 构建时传自己的地址（不带 .git 后缀）。
ARG AKASHIC_REPOSITORY=https://github.com/kachofugetsu09/akashic-agent
ARG AKASHIC_REVISION
WORKDIR /source
RUN git init && git remote add origin "${AKASHIC_REPOSITORY}.git" \
    && git fetch --depth=1 origin "${AKASHIC_REVISION}" && git checkout --detach FETCH_HEAD

FROM python:3.12-slim-bookworm AS build
COPY --from=node /usr/local /usr/local
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
# 只按锁文件和 SDK 内容建立依赖层；改 README 或业务源码时无需重装依赖。
COPY --from=source /source/docker/host-runtime/requirements.lock /tmp/requirements.lock
COPY --from=source /source/sdk/python /tmp/sdk
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && /opt/venv/bin/pip install --no-cache-dir --no-deps /tmp/sdk
COPY --from=source /source /source
WORKDIR /source
RUN /opt/venv/bin/python scripts/build_plugin_distribution.py --revision HEAD --output /opt/distribution \
    && /opt/venv/bin/python scripts/distribution_runtime.py prepare-wheels --distribution /opt/distribution \
    && /opt/venv/bin/python -c "from pathlib import Path; from scripts.install_plugin_distribution import extract_core; extract_core(Path('/opt/distribution'), Path('/opt/core'))"

FROM python:3.12-slim-bookworm
ARG AKASHIC_REPOSITORY=https://github.com/kachofugetsu09/akashic-agent
ARG AKASHIC_REVISION
LABEL org.opencontainers.image.source=$AKASHIC_REPOSITORY \
      org.opencontainers.image.revision=$AKASHIC_REVISION
# Chromium 运行库与中英文字体：与 playwright 锁版本的 Debian 12 依赖表对应。
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates zsh curl ripgrep \
        libasound2 libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcairo2 libcups2 \
        libdbus-1-3 libdrm2 libfontconfig1 libfreetype6 libgbm1 libglib2.0-0 libnspr4 \
        libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 \
        libxfixes3 libxkbcommon0 libxrandr2 \
        fonts-liberation fonts-noto-color-emoji fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 akashic && useradd --uid 1000 --gid 1000 --create-home akashic \
    && mkdir /data && chown akashic:akashic /data
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/distribution /opt/distribution
COPY --from=build /opt/core /opt/core
# 插件源码保留临时目录的 700 权限；运行用户需要读取，但不应改写镜像制品。
RUN chmod -R a=rX /opt/distribution
# 浏览器在构建期安装并设为只读：运行容器不联网下载，也不需要可写的缓存目录。
ENV PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    AKASHIC_EXECUTION_MODE=local PYTHONUNBUFFERED=1 AKASHIC_PLUGIN_DISTRIBUTION=/opt/distribution
RUN /opt/venv/bin/python -m playwright install --only-shell chromium \
    && chmod -R a=rX /opt/ms-playwright
USER akashic
WORKDIR /opt/core
EXPOSE 2236
ENTRYPOINT ["python", "scripts/start.py", "--distribution", "/opt/distribution", "--state", "/data", "--no-browser"]
