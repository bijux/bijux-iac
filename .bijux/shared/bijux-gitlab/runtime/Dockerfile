FROM mcr.microsoft.com/playwright@sha256:6446946a1d9fd62d9ae501312a2d76a43ee688542b21622056a372959b65d63d
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        python3 python3-venv python3-yaml git make curl ca-certificates \
        perl shellcheck xz-utils jq \
    && rm -rf /var/lib/apt/lists/*
