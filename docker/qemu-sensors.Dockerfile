# syntax=docker/dockerfile:1
# Builds Espressif's QEMU (pinned tag) with the patch series in qemu-patches/ applied, and
# drops the result into an existing image in place of the stock qemu-system-xtensa.
#
#   docker build -f docker/qemu-sensors.Dockerfile --build-arg BASE_IMAGE=<image> -t <tag> .
#
# The QEMU source and the patches are GPL-2.0-or-later; see qemu-patches/LICENSE.

ARG BASE_IMAGE=espressif/idf:v6.1@sha256:81893c71bb5e570088901f21def8684c25cd2a9020281bd01b843a7655edb18c

FROM ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3 AS qemu-build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl xz-utils patch ninja-build pkg-config \
        python3 python3-venv libglib2.0-dev libpixman-1-dev libgcrypt20-dev libslirp-dev \
        libfdt-dev git \
    && rm -rf /var/lib/apt/lists/*

ARG QEMU_TAG=esp-develop-9.2.2-20260417
ARG QEMU_VER=esp_develop_9.2.2_20260417
# sha256 published alongside the release (qemu-${QEMU_VER}-checksum.sha256)
ARG QEMU_SRC_SHA256=66015182274b9fda7d3c7f19e8f160e6e23947217cc149c7aa97e1586dfc6198
WORKDIR /src
RUN curl -fsSL -o qemu.tar.xz \
        https://github.com/espressif/qemu/releases/download/${QEMU_TAG}/qemu-${QEMU_VER}-src.tar.xz \
    && echo "${QEMU_SRC_SHA256}  qemu.tar.xz" | sha256sum -c - \
    && mkdir qemu && tar xJf qemu.tar.xz -C qemu --strip-components=1 && rm qemu.tar.xz

COPY qemu-patches/*.patch /src/patches/
RUN cd qemu && for p in /src/patches/*.patch; do echo "applying $p"; patch -p1 --no-backup-if-mismatch < "$p"; done

# Same flag set as Espressif's configure-native.sh, minus SDL (headless use only).
RUN cd qemu && ./configure \
        --bindir=bin --datadir=share/qemu --prefix=/opt/qemu --with-suffix="" \
        --target-list=xtensa-softmmu --without-default-features \
        --enable-gcrypt --enable-pixman --enable-slirp --enable-stack-protector \
        --extra-cflags=-Werror --with-pkgversion="${QEMU_VER}+dryflash" \
    && ninja -C build -j8 install \
    && find /opt/qemu/share/qemu -maxdepth 1 -mindepth 1 -not -name 'esp*.bin' -exec rm -rf {} +

FROM ${BASE_IMAGE}
ARG QEMU_VER=esp_develop_9.2.2_20260417
COPY --from=qemu-build /opt/qemu/ /opt/esp/tools/qemu-xtensa/${QEMU_VER}/qemu/
# The stock QEMU links the same libraries except libfdt; install whatever the base lacks.
RUN Q=/opt/esp/tools/qemu-xtensa/${QEMU_VER}/qemu/bin/qemu-system-xtensa; \
    if ldd "$Q" | grep -q "not found"; then \
        apt-get update && apt-get install -y --no-install-recommends \
            libfdt1 libpixman-1-0 libgcrypt20 libslirp0 libglib2.0-0t64 \
        && rm -rf /var/lib/apt/lists/*; \
    fi \
    && "$Q" --version | grep -q dryflash
