package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"time"

	"go.mau.fi/util/random"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

const soundStickerMIME = "application/vnd.gork.sound-sticker+json"

type soundSticker struct {
	WebP     []byte
	Audio    []byte
	Seconds  uint32
	Width    uint32
	Height   uint32
	Animated bool
}

func (s soundSticker) valid() bool {
	return s.Seconds >= 1 && s.Seconds <= 7 && s.Width >= 1 && s.Width <= 512 &&
		s.Height >= 1 && s.Height <= 512 && len(s.WebP) >= 12 && len(s.WebP) <= 1<<20 &&
		bytes.HasPrefix(s.WebP, []byte("RIFF")) && string(s.WebP[8:12]) == "WEBP" &&
		bytes.HasPrefix(s.Audio, []byte("OggS")) && len(s.Audio) <= 256<<10 &&
		bytes.Contains(s.Audio[:min(len(s.Audio), 128)], []byte("OpusHead"))
}

func buildSoundSticker(ctx context.Context, payload []byte, contextInfo *waE2E.ContextInfo,
	upload func(context.Context, []byte, whatsmeow.MediaType) (whatsmeow.UploadResponse, error),
) (*waE2E.Message, error) {
	if len(payload) > 2<<20 {
		return nil, status.Error(codes.InvalidArgument, "sound sticker is too large")
	}
	var sticker soundSticker
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&sticker) != nil || decoder.Decode(new(any)) != io.EOF || !sticker.valid() {
		return nil, status.Error(codes.InvalidArgument, "invalid sound sticker")
	}
	image, err := upload(ctx, sticker.WebP, whatsmeow.MediaImage)
	if err != nil {
		return nil, fmt.Errorf("upload sound sticker image: %w", err)
	}
	sound, err := upload(ctx, sticker.Audio, whatsmeow.MediaAudio)
	if err != nil {
		return nil, fmt.Errorf("upload sound sticker audio: %w", err)
	}
	now := time.Now()
	audioMessage := &waE2E.AudioMessage{
		URL: &sound.URL, DirectPath: &sound.DirectPath, MediaKey: sound.MediaKey,
		FileSHA256: sound.FileSHA256, FileEncSHA256: sound.FileEncSHA256,
		FileLength: &sound.FileLength, MediaKeyTimestamp: proto.Int64(now.Unix()),
		Mimetype: proto.String("audio/ogg; codecs=opus"), Seconds: &sticker.Seconds,
		ContextInfo: &waE2E.ContextInfo{},
	}
	stickerMessage := &waE2E.StickerMessage{
		URL: &image.URL, DirectPath: &image.DirectPath, MediaKey: image.MediaKey,
		FileSHA256: image.FileSHA256, FileEncSHA256: image.FileEncSHA256,
		FileLength: &image.FileLength, MediaKeyTimestamp: proto.Int64(now.Unix()),
		Mimetype: proto.String("image/webp"), IsAnimated: &sticker.Animated,
		Width: &sticker.Width, Height: &sticker.Height, StickerSentTS: proto.Int64(now.UnixMilli()),
		Audio: &waE2E.StickerMessage_AudioMessage{AudioMessage: audioMessage}, ContextInfo: contextInfo,
	}
	return &waE2E.Message{
		AudioStickerMessage: &waE2E.FutureProofMessage{Message: &waE2E.Message{StickerMessage: stickerMessage}},
		MessageContextInfo:  &waE2E.MessageContextInfo{MessageSecret: random.Bytes(32)},
	}, nil
}
