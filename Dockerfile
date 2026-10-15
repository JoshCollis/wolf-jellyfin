# syntax=docker/dockerfile:1
ARG BASE_IMAGE=ghcr.io/games-on-whales/base-app:fedora
FROM ${BASE_IMAGE} AS base
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN source /etc/os-release && dnf install -y "https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-${VERSION_ID}.noarch.rpm" && dnf upgrade -y --refresh --setopt=install_weak_deps=False && dnf clean all

FROM base AS builder
RUN dnf install -y --setopt=install_weak_deps=False git cmake ninja-build gcc-c++ qt6-qtbase-devel qt6-qtdeclarative-devel qt6-qtwebengine-devel qt6-qtwayland-devel mpv-devel mpvqt-devel SDL2-devel libX11-devel zlib-devel && dnf clean all
# Follow upstream's default branch and retain the exact source used for this build.
RUN git clone --depth 1 https://github.com/jellyfin/jellyfin-desktop.git /src/app && git -C /src/app archive --format=tar.gz --prefix=jellyfin-desktop/ HEAD > /src/source.tar.gz && git -C /src/app rev-parse HEAD > /src/source-commit.txt && git -C /src/app log -1 --format=%ct > /src/source-date.txt
COPY vendor/patches/jellyfin-container-aspect.patch /src/jellyfin-container-aspect.patch
COPY tests/aspect_contract.py /src/aspect_contract.py
COPY vendor/patches/apply-context-menu.py vendor/patches/jellyfin-wolf-context-menu.patch /src/
RUN python3 /src/apply-context-menu.py /src/app --diff > /src/actual-context-menu.patch && diff -u /src/jellyfin-wolf-context-menu.patch /src/actual-context-menu.patch && python3 /src/apply-context-menu.py /src/app
COPY vendor/patches/apply-audio.py vendor/patches/jellyfin-wolf-audio.patch /src/
RUN python3 /src/apply-audio.py /src/app --diff > /src/actual-audio.patch && diff -u /src/jellyfin-wolf-audio.patch /src/actual-audio.patch && python3 /src/apply-audio.py /src/app
COPY vendor/patches/apply-kiosk.py vendor/patches/jellyfin-wolf-kiosk.patch /src/
# Verify compatibility with current upstream before applying either patch.
RUN python3 /src/apply-kiosk.py /src/app --diff > /src/actual-kiosk.patch && diff -u /src/jellyfin-wolf-kiosk.patch /src/actual-kiosk.patch && python3 /src/apply-kiosk.py /src/app
RUN python3 -c 'from pathlib import Path; p=Path("/src/app/src/player/PlayerComponent.cpp"); s=p.read_text(); old="QString forceAspect = \"no\";"; assert s.count(old)==1; p.write_text(s.replace(old,"QString forceAspect = \"-1\";"))' && python3 /src/aspect_contract.py /src/app/src/player/PlayerComponent.cpp && export SOURCE_DATE_EPOCH="$(cat /src/source-date.txt)" && cmake -S /src/app -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DENABLE_CEC=OFF -DENABLE_LIRC=OFF -DCHECK_FOR_UPDATES=OFF && cmake --build /build -j 2 && ctest --test-dir /build --output-on-failure && DESTDIR=/install cmake --install /build

FROM base AS runtime
RUN dnf install -y --setopt=install_weak_deps=False python3 dbus-daemon qt6-qtwebengine qt6-qtdeclarative qt6-qtwayland qt6-qtsvg mpv mpvqt SDL2 libavcodec-freeworld wayland-utils pulseaudio-utils libva-utils util-linux tini && dnf clean all && rm -rf /home/retro/.local && rpm -qa --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > /usr/share/packages-wolf-jellyfin.txt
COPY --from=builder /install/ /
COPY --from=builder /src/source.tar.gz /usr/share/doc/wolf-jellyfin/jellyfin-desktop-source.tar.gz
COPY --from=builder /src/source-commit.txt /usr/share/doc/wolf-jellyfin/jellyfin-desktop-commit.txt
COPY vendor/patches/jellyfin-container-aspect.patch vendor/patches/jellyfin-wolf-kiosk.patch vendor/patches/apply-kiosk.py vendor/patches/jellyfin-wolf-context-menu.patch vendor/patches/apply-context-menu.py vendor/patches/jellyfin-wolf-audio.patch vendor/patches/apply-audio.py /usr/share/doc/wolf-jellyfin/
COPY LICENSE NOTICE.md /usr/share/doc/wolf-jellyfin/
COPY overlay/ /
ENV HOME=/home/retro UNAME=retro PUID=1000 PGID=1000 UMASK=077 TZ=UTC QT_QPA_PLATFORM=wayland PULSE_SERVER=unix:/run/user/wolf/pulse-socket
LABEL org.opencontainers.image.title="wolf-jellyfin" org.opencontainers.image.description="Jellyfin Desktop Qt6/libmpv native Wayland app for Wolf" org.opencontainers.image.licenses="MIT AND GPL-2.0-or-later" org.opencontainers.image.source="https://github.com/JoshCollis/wolf-jellyfin"
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]

FROM runtime AS test
RUN dnf install -y --allowerasing --setopt=install_weak_deps=False sway mesa-dri-drivers mesa-vulkan-drivers ffmpeg-free grim jq xorg-x11-server-Xvfb xdotool xorg-x11-xauth python3-websocket-client pulseaudio && dnf clean all
COPY tests/ /opt/wolf-jellyfin/tests/
FROM runtime AS final
