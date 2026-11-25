package server

import (
	"context"
	"encoding/json"
	"testing"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestGorkSoundStickerUsesImageAndAudioUploads(t *testing.T) {
	sticker := soundSticker{
		WebP: []byte("RIFF1234WEBP"), Audio: []byte("OggS OpusHead"),
		Seconds: 3, Width: 16, Height: 16, Animated: true,
	}
	payload, err := json.Marshal(sticker)
	if err != nil {
		t.Fatal(err)
	}
	var kinds []whatsmeow.MediaType
	upload := func(_ context.Context, data []byte, kind whatsmeow.MediaType) (whatsmeow.UploadResponse, error) {
		kinds = append(kinds, kind)
		return whatsmeow.UploadResponse{URL: string(data)}, nil
	}
	contextInfo := &waE2E.ContextInfo{}
	message, err := buildSoundSticker(t.Context(), payload, contextInfo, upload)
	if err != nil {
		t.Fatal(err)
	}
	if len(kinds) != 2 || kinds[0] != whatsmeow.MediaImage || kinds[1] != whatsmeow.MediaAudio {
		t.Fatalf("upload kinds: %v", kinds)
	}
	result := message.GetAudioStickerMessage().GetMessage().GetStickerMessage()
	if result.GetURL() != string(sticker.WebP) || result.GetContextInfo() != contextInfo ||
		result.GetWidth() != 16 || result.GetHeight() != 16 || !result.GetIsAnimated() ||
		result.GetAudioMessage().GetURL() != string(sticker.Audio) || result.GetAudioMessage().GetSeconds() != 3 ||
		len(message.GetMessageContextInfo().GetMessageSecret()) != 32 {
		t.Fatalf("incorrect sound sticker: %v", message)
	}
}

func TestGorkSoundStickerRejectsInvalidPayloadBeforeUpload(t *testing.T) {
	upload := func(context.Context, []byte, whatsmeow.MediaType) (whatsmeow.UploadResponse, error) {
		t.Fatal("invalid payload must not upload")
		return whatsmeow.UploadResponse{}, nil
	}
	for _, payload := range [][]byte{[]byte("{}"), []byte("{} {}"), make([]byte, (2<<20)+1)} {
		if _, err := buildSoundSticker(t.Context(), payload, nil, upload); status.Code(err) != codes.InvalidArgument {
			t.Fatalf("expected invalid argument, got %v", err)
		}
	}
}
