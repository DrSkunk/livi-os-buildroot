FROM ubuntu:24.04

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \
        bc bison build-essential ca-certificates cpio curl file flex gettext \
        git jq libncurses-dev libssl-dev python3 rsync shellcheck squashfs-tools sudo unzip wget \
        xz-utils && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /build && chown ubuntu:ubuntu /build
USER ubuntu
WORKDIR /workspace
