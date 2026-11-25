ARG WAHA_IMAGE=devlikeapro/waha:gows-2026.9.1@sha256:d2056b8dec41b218b54f431b8b4eb7d148346d530bb3658295ecb882944e9a18
FROM golang:1.26.11-bookworm AS gows-build
WORKDIR /gows
RUN apt-get update \
    && apt-get install -y --no-install-recommends libvips-dev protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.12 \
    && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.5.1

# Match the GOWS binary bundled in the pinned WAHA base image.
RUN git init -q \
    && git fetch -q --depth=1 https://github.com/devlikeapro/gows-plus.git 120d076d588335a8d329bb019d2c3804a08bfe5e \
    && git checkout -q --detach FETCH_HEAD
RUN --mount=type=cache,target=/go/pkg/mod \
    make build-proto && cd src && go mod download
COPY sound_sticker.go sound_sticker_test.go src/server/
COPY patch-sound-sticker.sh /tmp/patch-sound-sticker.sh
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    cd src \
    && sh /tmp/patch-sound-sticker.sh \
    && go test ./server -run TestGorkSoundSticker -count=1 \
    && go build -trimpath -o /gork-gows .

FROM ${WAHA_IMAGE}

# Same volume ownership setup used by Orbia.
USER root
COPY --from=gows-build /gork-gows /app/gows
RUN mkdir -p /app/.sessions /app/.media \
    && chown 1000:1000 /app/.sessions /app/.media
USER 1000:1000
