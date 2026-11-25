package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"strings"
	"syscall"
	"time"

	"github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
	"google.golang.org/protobuf/proto"
	_ "modernc.org/sqlite"
)

const maxRequest = 3 << 20

var accountPattern = regexp.MustCompile("^[0-9]{8,15}$")

type stickerRequest struct {
	Chat     string `json:"chat"`
	WebP     []byte `json:"webp"`
	Audio    []byte `json:"audio"`
	Seconds  uint32 `json:"seconds"`
	Width    uint32 `json:"width"`
	Height   uint32 `json:"height"`
	Animated bool   `json:"animated"`
}

func (r stickerRequest) valid() bool {
	return r.Seconds >= 1 && r.Seconds <= 7 && r.Width >= 1 && r.Width <= 512 &&
		r.Height >= 1 && r.Height <= 512 && len(r.WebP) >= 12 && len(r.WebP) <= 1<<20 &&
		bytes.HasPrefix(r.WebP, []byte("RIFF")) && string(r.WebP[8:12]) == "WEBP" &&
		bytes.HasPrefix(r.Audio, []byte("OggS")) && len(r.Audio) <= 256<<10 &&
		bytes.Contains(r.Audio[:min(len(r.Audio), 128)], []byte("OpusHead"))
}

func buildMessage(r stickerRequest, image, sound whatsmeow.UploadResponse) *waE2E.Message {
	now := time.Now()
	audio := &waE2E.AudioMessage{
		URL: &sound.URL, DirectPath: &sound.DirectPath,
		MediaKey: sound.MediaKey, FileSHA256: sound.FileSHA256, FileEncSHA256: sound.FileEncSHA256,
		FileLength: &sound.FileLength, MediaKeyTimestamp: proto.Int64(now.Unix()),
		Mimetype: proto.String("audio/ogg; codecs=opus"), Seconds: &r.Seconds,
		ContextInfo: &waE2E.ContextInfo{},
	}
	sticker := &waE2E.StickerMessage{
		URL: &image.URL, DirectPath: &image.DirectPath,
		MediaKey: image.MediaKey, FileSHA256: image.FileSHA256, FileEncSHA256: image.FileEncSHA256,
		FileLength: &image.FileLength, MediaKeyTimestamp: proto.Int64(now.Unix()),
		Mimetype: proto.String("image/webp"), IsAnimated: &r.Animated,
		Width: &r.Width, Height: &r.Height,
		StickerSentTS: proto.Int64(now.UnixMilli()), ContextInfo: &waE2E.ContextInfo{},
		Audio: &waE2E.StickerMessage_AudioMessage{AudioMessage: audio},
	}
	secret := make([]byte, 32)
	rand.Read(secret)
	return &waE2E.Message{
		AudioStickerMessage: &waE2E.FutureProofMessage{Message: &waE2E.Message{StickerMessage: sticker}},
		MessageContextInfo:  &waE2E.MessageContextInfo{MessageSecret: secret},
	}
}

func recipient(chat string) (types.JID, error) {
	if prefix, ok := strings.CutSuffix(chat, "@c.us"); ok {
		chat = prefix + "@s.whatsapp.net"
	}
	jid, err := types.ParseJID(chat)
	allowed := jid.Server == types.DefaultUserServer || jid.Server == types.HiddenUserServer || jid.Server == types.GroupServer
	if err != nil || !allowed || jid.User == "" || jid != jid.ToNonAD() {
		return types.EmptyJID, errors.New("invalid chat")
	}
	return jid, nil
}

func stickerHandler(client *whatsmeow.Client, token string) http.HandlerFunc {
	return func(w http.ResponseWriter, request *http.Request) {
		if subtle.ConstantTimeCompare([]byte(request.Header.Get("Authorization")), []byte("Bearer "+token)) != 1 {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if !client.IsLoggedIn() {
			http.Error(w, "WhatsApp disconnected", http.StatusServiceUnavailable)
			return
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, request.Body, maxRequest))
		decoder.DisallowUnknownFields()
		var sticker stickerRequest
		if decoder.Decode(&sticker) != nil || decoder.Decode(new(any)) != io.EOF || !sticker.valid() {
			http.Error(w, "invalid sticker", http.StatusBadRequest)
			return
		}
		jid, err := recipient(sticker.Chat)
		if err != nil {
			http.Error(w, "invalid chat", http.StatusBadRequest)
			return
		}
		ctx, cancel := context.WithTimeout(request.Context(), 38*time.Second)
		defer cancel()
		if err := send(ctx, client, jid, sticker); err != nil {
			log.Printf("sound sticker send failed: %T", err)
			http.Error(w, "WhatsApp send failed", http.StatusBadGateway)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	}
}

func send(ctx context.Context, client *whatsmeow.Client, jid types.JID, sticker stickerRequest) error {
	image, err := client.Upload(ctx, sticker.WebP, whatsmeow.MediaImage)
	if err != nil {
		return fmt.Errorf("upload WebP: %w", err)
	}
	sound, err := client.Upload(ctx, sticker.Audio, whatsmeow.MediaAudio)
	if err != nil {
		return fmt.Errorf("upload Opus: %w", err)
	}
	_, err = client.SendMessage(ctx, jid, buildMessage(sticker, image, sound))
	return err
}

func pair(ctx context.Context, client *whatsmeow.Client, account string) error {
	ctx, cancel := context.WithTimeout(ctx, 4*time.Minute)
	defer cancel()
	codes, err := client.GetQRChannel(ctx)
	if err != nil {
		return err
	}
	if err := client.Connect(); err != nil {
		return err
	}
	for event := range codes {
		switch event.Event {
		case "code":
			qr, err := qrcode.New(event.Code, qrcode.Medium)
			if err != nil {
				return err
			}
			fmt.Print(qr.ToSmallString(false))
		case "success":
			for !client.IsLoggedIn() {
				select {
				case <-ctx.Done():
					return ctx.Err()
				case <-time.After(250 * time.Millisecond):
				}
			}
			if client.Store.ID.User != account {
				if err := client.Logout(ctx); err != nil {
					return fmt.Errorf("unexpected account; unlink the temporary device manually: %w", err)
				}
				return errors.New("paired account differs from SOUND_STICKER_ACCOUNT")
			}
			fmt.Println("Dispositivo pareado.")
			return nil
		default:
			return fmt.Errorf("pairing ended: %s", event.Event)
		}
	}
	return errors.New("pairing canceled")
}

func run(ctx context.Context) error {
	account := os.Getenv("SOUND_STICKER_ACCOUNT")
	if !accountPattern.MatchString(account) {
		return errors.New("set SOUND_STICKER_ACCOUNT to the Gork phone with country code")
	}
	store, err := sqlstore.New(ctx, "sqlite", "file:/data/device.db?_pragma=foreign_keys(1)", waLog.Noop)
	if err != nil {
		return err
	}
	defer store.Close()
	device, err := store.GetFirstDevice(ctx)
	if err != nil {
		return err
	}
	client := whatsmeow.NewClient(device, waLog.Noop)
	defer client.Disconnect()
	if len(os.Args) == 2 && os.Args[1] == "pair" {
		if device.ID != nil {
			return errors.New("a device is already stored")
		}
		return pair(ctx, client, account)
	}
	token := os.Getenv("SOUND_STICKER_TOKEN")
	if len(token) < 32 {
		return errors.New("set SOUND_STICKER_TOKEN to at least 32 characters")
	}
	if device.ID == nil || device.ID.User != account {
		return errors.New("pair the sticker device with the configured Gork account first")
	}
	if err := client.Connect(); err != nil {
		return err
	}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /sticker", stickerHandler(client, token))
	server := &http.Server{
		Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 15 * time.Second, WriteTimeout: 60 * time.Second, IdleTimeout: 60 * time.Second,
	}
	go func() {
		<-ctx.Done()
		deadline, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(deadline)
	}()
	err = server.ListenAndServe()
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	if err := run(ctx); err != nil {
		log.Fatal(err)
	}
}
