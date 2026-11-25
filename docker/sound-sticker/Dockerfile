FROM golang:1.26.11-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY main.go ./
# Match the WhatsApp client's media classification for wrapped sound stickers.
RUN set -eu; \
    source="$(go list -m -f '{{.Dir}}' go.mau.fi/whatsmeow)"; \
    cp -R "$source" /src/whatsmeow; \
    chmod u+w /src/whatsmeow/send.go; \
    sed -i '/return getMediaTypeFromMessage(msg.LottieStickerMessage.Message)/a\	case msg.AudioStickerMessage != nil:\n		return getMediaTypeFromMessage(msg.AudioStickerMessage.Message)' /src/whatsmeow/send.go; \
    grep -q 'return getMediaTypeFromMessage(msg.AudioStickerMessage.Message)' /src/whatsmeow/send.go; \
    go mod edit -replace go.mau.fi/whatsmeow=./whatsmeow; \
    CGO_ENABLED=0 go build -trimpath -o /sound-sticker .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 0700 -o 1000 -g 1000 /data
COPY --from=build /sound-sticker /usr/local/bin/sound-sticker
USER 1000:1000
ENTRYPOINT ["/usr/local/bin/sound-sticker"]
