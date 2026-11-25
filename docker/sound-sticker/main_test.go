package main

import (
	"testing"

	"go.mau.fi/whatsmeow"
	"google.golang.org/protobuf/proto"
)

func TestSoundStickerProtobuf(t *testing.T) {
	for _, animated := range []bool{false, true} {
		input := stickerRequest{Seconds: 3, Width: 220, Height: 220, Animated: animated}
		webp := whatsmeow.UploadResponse{DirectPath: "/sticker", FileSHA256: []byte{1}}
		audio := whatsmeow.UploadResponse{DirectPath: "/sound", FileSHA256: []byte{2}}
		message := buildMessage(input, webp, audio)
		encoded, err := proto.Marshal(message)
		if err != nil {
			t.Fatal(err)
		}
		proto.Reset(message)
		if err := proto.Unmarshal(encoded, message); err != nil {
			t.Fatal(err)
		}
		sticker := message.GetAudioStickerMessage().GetMessage().GetStickerMessage()
		sound := sticker.GetAudioMessage()
		if sticker.GetDirectPath() != "/sticker" || sticker.GetIsAnimated() != animated ||
			sound.GetDirectPath() != "/sound" || sound.GetSeconds() != 3 ||
			sound.GetMimetype() != "audio/ogg; codecs=opus" {
			t.Fatal("misconfigured sound sticker")
		}
	}
}

func TestRecipient(t *testing.T) {
	for chat, want := range map[string]string{
		"12345@c.us":       "12345@s.whatsapp.net",
		"12345@lid":        "12345@lid",
		"12345-67890@g.us": "12345-67890@g.us",
	} {
		got, err := recipient(chat)
		if err != nil || got.String() != want {
			t.Errorf("recipient(%q) = %v, %v", chat, got, err)
		}
	}
	if _, err := recipient("status@broadcast"); err == nil {
		t.Fatal("broadcast destination accepted")
	}
}
