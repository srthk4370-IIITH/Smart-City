package main

import (
	"os"
	"path/filepath"
	"testing"
)

// htpd_profile switches the daemon build/options; without it the v1/v2 defaults stay.
func TestHtpdProfile(t *testing.T) {
	old := htpdWorkDir
	htpdWorkDir = t.TempDir()
	t.Cleanup(func() { htpdWorkDir = old })
	withAgentVersion(t, "v2")
	if htpdAgentStreams() != 10 || htpdAgentCtx() != 1280 || len(htpdProfile()) != 0 {
		t.Fatalf("defaults without a profile: %d x %d", htpdAgentStreams(), htpdAgentCtx())
	}
	os.WriteFile(filepath.Join(htpdWorkDir, "htpd_profile"), []byte("# v7 A/B\nbin=/x/htpd_v7\nagents=14\nagent_ctx = 1024\nlayouts=14x1024,10x1280\nenv=HTPD_ROLE_DRAFT=1 HTPD_AGENT_MAX_NEW=160\nmodel=/x/ft_v2t3d_q4_0.gguf\n"), 0o644)
	p := htpdProfile()
	if htpdAgentStreams() != 14 || htpdMaxBatch() != 14 || htpdAgentCtx() != 1024 || p["bin"] != "/x/htpd_v7" ||
		p["layouts"] != "14x1024,10x1280" || p["env"] != "HTPD_ROLE_DRAFT=1 HTPD_AGENT_MAX_NEW=160" {
		t.Fatalf("profile not applied: %v, %d x %d", p, htpdAgentStreams(), htpdAgentCtx())
	}
	if htpdModelPath() != "/x/ft_v2t3d_q4_0.gguf" {
		t.Fatalf("model key not applied: %s", htpdModelPath())
	}
}
