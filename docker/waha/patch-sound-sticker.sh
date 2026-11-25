#!/bin/sh
set -eu

test "$(grep -Fc 'case __.MediaType_STICKER:' server/messages.go)" = 1
sed -i '/case __\.MediaType_STICKER:/a\
			if req.Media.Mimetype == soundStickerMIME {\
				message, err = buildSoundSticker(ctx, req.Media.Content, contextInfo,\
					func(ctx context.Context, content []byte, mediaType whatsmeow.MediaType) (whatsmeow.UploadResponse, error) {\
						return cli.UploadMedia(ctx, jid, content, mediaType)\
					})\
				if err != nil {\
					return nil, err\
				}\
				break\
			}' server/messages.go

# Unwrap the sound sticker for the same type and media classification as WebP.
source="$(go list -m -f '{{.Dir}}' go.mau.fi/whatsmeow)"
cp -R "$source" /whatsmeow
chmod u+w /whatsmeow
for classifier in getTypeFromMessage getMediaTypeFromMessage; do
    marker="return $classifier(msg.LottieStickerMessage.Message)"
    test "$(grep -Fc "$marker" /whatsmeow/send.go)" = 1
    sed -i "/$classifier(msg.LottieStickerMessage.Message)/a\\
	case msg.AudioStickerMessage != nil:\\
		return $classifier(msg.AudioStickerMessage.Message)" /whatsmeow/send.go
done
gofmt -w server/messages.go /whatsmeow/send.go
go mod edit -replace go.mau.fi/whatsmeow=/whatsmeow
