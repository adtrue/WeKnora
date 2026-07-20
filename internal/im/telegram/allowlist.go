package telegram

// AdTrue patch: optional allowlist for Telegram channels.
//
// Credential `allowed_chat_ids` (comma-separated Telegram chat and/or user
// IDs) restricts who can talk to the bot. Empty/absent keeps the upstream
// behavior (everyone allowed). A message passes when its group chat ID or
// its sender user ID is in the list, so both DMs and groups can be pinned.

import (
	"context"
	"strings"

	"github.com/Tencent/WeKnora/internal/im"
	"github.com/Tencent/WeKnora/internal/logger"
)

func parseAllowedChatIDs(s string) map[string]struct{} {
	out := map[string]struct{}{}
	for _, part := range strings.Split(s, ",") {
		if p := strings.TrimSpace(part); p != "" {
			out[p] = struct{}{}
		}
	}
	return out
}

// SetAllowedChatIDs installs the allowlist on the adapter (webhook path).
func (a *Adapter) SetAllowedChatIDs(allowed map[string]struct{}) {
	a.allowedChats = allowed
}

func (a *Adapter) messageAllowed(msg *im.IncomingMessage) bool {
	return chatAllowed(a.allowedChats, msg)
}

func chatAllowed(allowed map[string]struct{}, msg *im.IncomingMessage) bool {
	if len(allowed) == 0 || msg == nil {
		return true
	}
	if _, ok := allowed[msg.ChatID]; ok {
		return true
	}
	_, ok := allowed[msg.UserID]
	return ok
}

// wrapAllowlistHandler filters the long-polling message handler.
func wrapAllowlistHandler(allowed map[string]struct{}, h func(context.Context, *im.IncomingMessage) error) func(context.Context, *im.IncomingMessage) error {
	if len(allowed) == 0 {
		return h
	}
	return func(ctx context.Context, msg *im.IncomingMessage) error {
		if !chatAllowed(allowed, msg) {
			logger.Infof(ctx, "[IM] Telegram message dropped (allowed_chat_ids): user=%s chat=%s", msg.UserID, msg.ChatID)
			return nil
		}
		return h(ctx, msg)
	}
}
