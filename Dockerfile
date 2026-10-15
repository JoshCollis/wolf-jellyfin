# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ghcr.io/games-on-whales/base-app@sha256:d29171bb180d01ea2cb45993d974eca9265da37b6745c67f75cca62a4d193a9d
FROM ${BASE_IMAGE} AS builder
ENV SOURCE_DATE_EPOCH=1788162231
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY locks/builder.rpms /locks/builder.rpms
# Every installed RPM is pinned, including the transitive dependency closure.
RUN dnf install -y --setopt=install_weak_deps=False $(cat /locks/builder.rpms) && dnf clean all && rpm -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | python3 -c 'import sys; sys.stdout.write("".join(sorted(x for x in sys.stdin if not x.startswith("gpg-pubkey-"))))' | grep -v '^gpg-pubkey-' > /locks/actual.rpms && diff -u /locks/builder.rpms /locks/actual.rpms
COPY vendor/jellyfin-desktop.tar.gz /src/source.tar.gz
RUN echo '285cabe7dce0c8eaa48823e75cfa882f4d740e3550f79878f05b0d8025d55f1c  /src/source.tar.gz' | sha256sum -c - && tar -xf /src/source.tar.gz -C /src && mv /src/jellyfin-desktop-* /src/app
COPY vendor/patches/jellyfin-container-aspect.patch /src/jellyfin-container-aspect.patch
COPY tests/aspect_contract.py /src/aspect_contract.py
COPY vendor/patches/apply-kiosk.py vendor/patches/jellyfin-wolf-kiosk.patch /src/
# Keep the distributed diff identical to the strict source transformation.
RUN python3 /src/apply-kiosk.py /src/app --diff > /src/actual-kiosk.patch && diff -u /src/jellyfin-wolf-kiosk.patch /src/actual-kiosk.patch && python3 /src/apply-kiosk.py /src/app
# Equivalent to the shipped one-line patch; strict source guard, no fuzzy application.
RUN python3 -c 'from pathlib import Path; p=Path("/src/app/src/player/PlayerComponent.cpp"); s=p.read_text(); old="QString forceAspect = \"no\";"; assert s.count(old)==1; p.write_text(s.replace(old,"QString forceAspect = \"-1\";"))' && python3 /src/aspect_contract.py /src/app/src/player/PlayerComponent.cpp && cmake -S /src/app -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DENABLE_CEC=OFF -DENABLE_LIRC=OFF -DCHECK_FOR_UPDATES=OFF && cmake --build /build -j 2 && ctest --test-dir /build --output-on-failure && DESTDIR=/install cmake --install /build
FROM ${BASE_IMAGE} AS runtime
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY vendor/rpmfusion-free-release-43-1.noarch.rpm /locks/rpmfusion-free-release.rpm
RUN echo 'd7757257bdce32888020c4ff5a3e3d43cf7c32105ffd2c36aff9a2fcaadef657  /locks/rpmfusion-free-release.rpm' | sha256sum -c - && dnf install -y /locks/rpmfusion-free-release.rpm
COPY locks/runtime.rpms /locks/runtime.rpms
RUN source /etc/os-release && test "$(date -u +%F)" '<' "$SUPPORT_END" && dnf install -y --setopt=install_weak_deps=False $(cat /locks/runtime.rpms) && dnf clean all && rm -rf /home/retro/.local && rpm -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | python3 -c 'import sys; sys.stdout.write("".join(sorted(x for x in sys.stdin if not x.startswith("gpg-pubkey-"))))' | grep -v '^gpg-pubkey-' > /usr/share/packages-wolf-jellyfin.txt && diff -u /locks/runtime.rpms /usr/share/packages-wolf-jellyfin.txt
COPY --from=builder /install/ /
COPY vendor/jellyfin-desktop.tar.gz /usr/share/doc/wolf-jellyfin/jellyfin-desktop-source.tar.gz
COPY vendor/patches/jellyfin-container-aspect.patch vendor/patches/jellyfin-wolf-kiosk.patch vendor/patches/apply-kiosk.py /usr/share/doc/wolf-jellyfin/
COPY LICENSE NOTICE.md /usr/share/doc/wolf-jellyfin/
COPY overlay/ /
ENV HOME=/home/retro UNAME=retro PUID=1000 PGID=1000 UMASK=077 TZ=UTC QT_QPA_PLATFORM=wayland PULSE_SERVER=unix:/run/user/wolf/pulse-socket
LABEL org.opencontainers.image.title="wolf-jellyfin" org.opencontainers.image.description="Pinned Jellyfin Desktop Qt6/libmpv native Wayland app for Wolf" org.opencontainers.image.version="2.0.0-dev-2cb4a44" org.opencontainers.image.licenses="MIT AND GPL-2.0-or-later" org.opencontainers.image.source="https://github.com/JoshCollis/wolf-jellyfin"
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
FROM runtime AS test
RUN dnf install -y --allowerasing --setopt=install_weak_deps=False sway mesa-dri-drivers mesa-vulkan-drivers ffmpeg-free grim jq xorg-x11-server-Xvfb xdotool xorg-x11-xauth python3-websocket-client pulseaudio && dnf clean all
COPY tests/ /opt/wolf-jellyfin/tests/
FROM runtime AS final
