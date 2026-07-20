package telegram

import (
	"testing"

	"github.com/Tencent/WeKnora/internal/im"
)

func TestParseAllowedChatIDs(t *testing.T) {
	if got := parseAllowedChatIDs(""); len(got) != 0 {
		t.Fatalf("empty input should allow all, got %v", got)
	}
	got := parseAllowedChatIDs(" 123, -100456 ,789 ")
	for _, id := range []string{"123", "-100456", "789"} {
		if _, ok := got[id]; !ok {
			t.Fatalf("missing %s in %v", id, got)
		}
	}
}

func TestChatAllowed(t *testing.T) {
	allowed := parseAllowedChatIDs("346496439,-100777")
	cases := []struct {
		name string
		msg  *im.IncomingMessage
		want bool
	}{
		{"nil passes", nil, true},
		{"dm allowed user", &im.IncomingMessage{UserID: "346496439"}, true},
		{"group allowed chat, any user", &im.IncomingMessage{ChatID: "-100777", UserID: "999"}, true},
		{"stranger dm", &im.IncomingMessage{UserID: "999"}, false},
		{"stranger group", &im.IncomingMessage{ChatID: "-100999", UserID: "999"}, false},
	}
	for _, c := range cases {
		if got := chatAllowed(allowed, c.msg); got != c.want {
			t.Errorf("%s: got %v want %v", c.name, got, c.want)
		}
	}
	if !chatAllowed(map[string]struct{}{}, &im.IncomingMessage{UserID: "999"}) {
		t.Error("empty allowlist must allow everyone")
	}
}
