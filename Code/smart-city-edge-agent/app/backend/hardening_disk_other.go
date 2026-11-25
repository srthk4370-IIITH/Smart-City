//go:build !linux

package main

func diskFreeTotal(path string) (free, total uint64, ok bool) { return 0, 0, false }
