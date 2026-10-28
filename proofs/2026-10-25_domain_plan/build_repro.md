# Tree (without P1) == deployed backend ab5442 (2026-10-25)
- Built in the repo backend dir with app/build.sh flags (CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags "-s -w", go1.23.4),
  P1 files swapped for their .orig copies (scripts/*.go.orig), claimcheck.go removed -> md5 98395cd1 (deployed ab54423d).
- `cmp -l`: 38 bytes differ, offsets 4013-4053 only = inside the Go build-ID string at offset 4012
  (deployed NWbxX3I.../EnkdGZ3.../QX3hp1J.../HpSWUzx..., rebuild tKFKApr.../EJ3NUZe.../QX3hp1J.../HpSWUzx...; link content id HpSWUzx identical).
  `strings` diff: only the build-ID line. Same 6,553,752 bytes. => severity.go and title.go in the tree ARE the deployed state; no leftovers.
- Earlier /tmp copy builds differed only because they lacked VCS stamping (vcs.revision/modified lines) - not a source difference.
