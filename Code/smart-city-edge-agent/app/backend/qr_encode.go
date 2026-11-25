package main

// Minimal pure-Go QR Code encoder (ISO/IEC 18004): byte mode, error correction M, versions 1-40, automatic
// mask choice. Used only by the incident QR report (qr_report.go); no external dependencies.

import (
	"errors"
	"fmt"
	"strings"
)

// per version 1..40 (index 0 unused), ECC level M
var qrEccPerBlockM = [41]int{0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28}
var qrNumBlocksM = [41]int{0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49}

func qrRawModules(ver int) int {
	r := (16*ver+128)*ver + 64
	if ver >= 2 {
		na := ver/7 + 2
		r -= (25*na-10)*na - 55
		if ver >= 7 {
			r -= 36
		}
	}
	return r
}

func qrDataCodewords(ver int) int {
	return qrRawModules(ver)/8 - qrEccPerBlockM[ver]*qrNumBlocksM[ver]
}

// qrMaxBytes is the byte-mode capacity of a version at ECC M.
func qrMaxBytes(ver int) int {
	cc := 8
	if ver >= 10 {
		cc = 16
	}
	return (qrDataCodewords(ver)*8 - 4 - cc) / 8
}

func qrGfMul(x, y byte) byte {
	var z byte
	for i := 7; i >= 0; i-- {
		hi := z >> 7
		z <<= 1
		if hi != 0 {
			z ^= 0x1D // 0x11D without the x^8 bit
		}
		if (y>>uint(i))&1 != 0 {
			z ^= x
		}
	}
	return z
}

func qrRsDivisor(degree int) []byte {
	res := make([]byte, degree)
	res[degree-1] = 1
	root := byte(1)
	for i := 0; i < degree; i++ {
		for j := 0; j < degree; j++ {
			res[j] = qrGfMul(res[j], root)
			if j+1 < degree {
				res[j] ^= res[j+1]
			}
		}
		root = qrGfMul(root, 2)
	}
	return res
}

func qrRsRemainder(data, div []byte) []byte {
	res := make([]byte, len(div))
	for _, b := range data {
		f := b ^ res[0]
		copy(res, res[1:])
		res[len(res)-1] = 0
		for i := range res {
			res[i] ^= qrGfMul(div[i], f)
		}
	}
	return res
}

type qrBits struct {
	b []byte
	n int
}

func (q *qrBits) add(v uint, nbits int) {
	for i := nbits - 1; i >= 0; i-- {
		if q.n%8 == 0 {
			q.b = append(q.b, 0)
		}
		if (v>>uint(i))&1 != 0 {
			q.b[q.n/8] |= 0x80 >> uint(q.n%8)
		}
		q.n++
	}
}

type qrMatrix struct {
	size int
	mod  [][]bool
	fn   [][]bool
}

func (m *qrMatrix) setFn(x, y int, v bool) {
	m.mod[y][x] = v
	m.fn[y][x] = true
}

func qrCheb(dx, dy int) int {
	if dx < 0 {
		dx = -dx
	}
	if dy < 0 {
		dy = -dy
	}
	if dy > dx {
		return dy
	}
	return dx
}

func (m *qrMatrix) drawFinder(cx, cy int) {
	for dy := -4; dy <= 4; dy++ {
		for dx := -4; dx <= 4; dx++ {
			d := qrCheb(dx, dy)
			x, y := cx+dx, cy+dy
			if x >= 0 && x < m.size && y >= 0 && y < m.size {
				m.setFn(x, y, d != 2 && d != 4)
			}
		}
	}
}

func (m *qrMatrix) drawAlign(cx, cy int) {
	for dy := -2; dy <= 2; dy++ {
		for dx := -2; dx <= 2; dx++ {
			m.setFn(cx+dx, cy+dy, qrCheb(dx, dy) != 1)
		}
	}
}

func qrAlignPositions(ver int) []int {
	if ver == 1 {
		return nil
	}
	na := ver/7 + 2
	step := 26
	if ver != 32 {
		step = (ver*4 + na*2 + 1) / (na*2 - 2) * 2
	}
	res := make([]int, na)
	res[0] = 6
	pos := ver*4 + 17 - 7
	for i := na - 1; i >= 1; i-- {
		res[i] = pos
		pos -= step
	}
	return res
}

func (m *qrMatrix) drawFormat(mask int) {
	data := mask // ECC M = 00
	rem := data
	for i := 0; i < 10; i++ {
		rem = (rem << 1) ^ ((rem >> 9) * 0x537)
	}
	bits := (data<<10 | rem) ^ 0x5412
	bit := func(i int) bool { return (bits>>uint(i))&1 != 0 }
	for i := 0; i <= 5; i++ {
		m.setFn(8, i, bit(i))
	}
	m.setFn(8, 7, bit(6))
	m.setFn(8, 8, bit(7))
	m.setFn(7, 8, bit(8))
	for i := 9; i < 15; i++ {
		m.setFn(14-i, 8, bit(i))
	}
	for i := 0; i < 8; i++ {
		m.setFn(m.size-1-i, 8, bit(i))
	}
	for i := 8; i < 15; i++ {
		m.setFn(8, m.size-15+i, bit(i))
	}
	m.setFn(8, m.size-8, true)
}

func (m *qrMatrix) drawVersion(ver int) {
	if ver < 7 {
		return
	}
	rem := ver
	for i := 0; i < 12; i++ {
		rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
	}
	bits := ver<<12 | rem
	for i := 0; i < 18; i++ {
		b := (bits>>uint(i))&1 != 0
		a := m.size - 11 + i%3
		c := i / 3
		m.setFn(a, c, b)
		m.setFn(c, a, b)
	}
}

func (m *qrMatrix) applyMask(mask int) {
	for y := 0; y < m.size; y++ {
		for x := 0; x < m.size; x++ {
			var inv bool
			switch mask {
			case 0:
				inv = (x+y)%2 == 0
			case 1:
				inv = y%2 == 0
			case 2:
				inv = x%3 == 0
			case 3:
				inv = (x+y)%3 == 0
			case 4:
				inv = (x/3+y/2)%2 == 0
			case 5:
				inv = x*y%2+x*y%3 == 0
			case 6:
				inv = (x*y%2+x*y%3)%2 == 0
			default:
				inv = ((x+y)%2+x*y%3)%2 == 0
			}
			if inv && !m.fn[y][x] {
				m.mod[y][x] = !m.mod[y][x]
			}
		}
	}
}

func (m *qrMatrix) penalty() int {
	n, p := m.size, 0
	pat1 := []bool{true, false, true, true, true, false, true, false, false, false, false}
	pat2 := []bool{false, false, false, false, true, false, true, true, true, false, true}
	for dir := 0; dir < 2; dir++ {
		get := func(i, j int) bool {
			if dir == 0 {
				return m.mod[i][j]
			}
			return m.mod[j][i]
		}
		for i := 0; i < n; i++ {
			run := 1
			for j := 1; j < n; j++ {
				if get(i, j) == get(i, j-1) {
					run++
					continue
				}
				if run >= 5 {
					p += 3 + run - 5
				}
				run = 1
			}
			if run >= 5 {
				p += 3 + run - 5
			}
			for j := 0; j+11 <= n; j++ {
				a, b := true, true
				for k := 0; k < 11; k++ {
					v := get(i, j+k)
					if v != pat1[k] {
						a = false
					}
					if v != pat2[k] {
						b = false
					}
				}
				if a {
					p += 40
				}
				if b {
					p += 40
				}
			}
		}
	}
	for y := 0; y+1 < n; y++ { // 2x2 blocks
		for x := 0; x+1 < n; x++ {
			c := m.mod[y][x]
			if c == m.mod[y][x+1] && c == m.mod[y+1][x] && c == m.mod[y+1][x+1] {
				p += 3
			}
		}
	}
	dark := 0
	for y := range m.mod {
		for _, v := range m.mod[y] {
			if v {
				dark++
			}
		}
	}
	total := n * n
	d := dark*20 - total*10
	if d < 0 {
		d = -d
	}
	k := (d + total - 1) / total
	p += (k - 1) * 10
	return p
}

// qrEncode returns the module matrix (true = dark, no quiet zone) and the version chosen.
func qrEncode(data []byte) ([][]bool, int, error) {
	ver := 0
	for v := 1; v <= 40; v++ {
		if len(data) <= qrMaxBytes(v) {
			ver = v
			break
		}
	}
	if ver == 0 {
		return nil, 0, errors.New("qr: data too long for version 40-M")
	}
	cc := 8
	if ver >= 10 {
		cc = 16
	}
	var bb qrBits
	bb.add(4, 4) // byte mode
	bb.add(uint(len(data)), cc)
	for _, c := range data {
		bb.add(uint(c), 8)
	}
	capBits := qrDataCodewords(ver) * 8
	t := capBits - bb.n
	if t > 4 {
		t = 4
	}
	bb.add(0, t)
	if bb.n%8 != 0 {
		bb.add(0, 8-bb.n%8)
	}
	for pad := byte(0xEC); len(bb.b) < qrDataCodewords(ver); pad ^= 0xEC ^ 0x11 {
		bb.b = append(bb.b, pad)
	}
	nb, eccLen := qrNumBlocksM[ver], qrEccPerBlockM[ver]
	raw := qrRawModules(ver) / 8
	nShort := nb - raw%nb
	shortLen := raw / nb
	div := qrRsDivisor(eccLen)
	blocks := make([][]byte, nb)
	k := 0
	for i := 0; i < nb; i++ {
		dl := shortLen - eccLen
		if i >= nShort {
			dl++
		}
		d := append([]byte{}, bb.b[k:k+dl]...)
		k += dl
		e := qrRsRemainder(d, div)
		if i < nShort {
			d = append(d, 0)
		}
		blocks[i] = append(d, e...)
	}
	var cw []byte
	for i := 0; i < len(blocks[0]); i++ {
		for j := 0; j < nb; j++ {
			if i != shortLen-eccLen || j >= nShort {
				cw = append(cw, blocks[j][i])
			}
		}
	}
	size := ver*4 + 17
	m := &qrMatrix{size: size, mod: make([][]bool, size), fn: make([][]bool, size)}
	for i := range m.mod {
		m.mod[i] = make([]bool, size)
		m.fn[i] = make([]bool, size)
	}
	for i := 0; i < size; i++ {
		m.setFn(6, i, i%2 == 0)
		m.setFn(i, 6, i%2 == 0)
	}
	m.drawFinder(3, 3)
	m.drawFinder(size-4, 3)
	m.drawFinder(3, size-4)
	ap := qrAlignPositions(ver)
	for i := range ap {
		for j := range ap {
			if (i == 0 && j == 0) || (i == 0 && j == len(ap)-1) || (i == len(ap)-1 && j == 0) {
				continue
			}
			m.drawAlign(ap[i], ap[j])
		}
	}
	m.drawFormat(0)
	m.drawVersion(ver)
	bi := 0
	for right := size - 1; right >= 1; right -= 2 {
		if right == 6 {
			right = 5
		}
		for vert := 0; vert < size; vert++ {
			for j := 0; j < 2; j++ {
				x := right - j
				up := ((right + 1) & 2) == 0
				y := vert
				if up {
					y = size - 1 - vert
				}
				if !m.fn[y][x] && bi < len(cw)*8 {
					m.mod[y][x] = (cw[bi>>3]>>uint(7-bi&7))&1 != 0
					bi++
				}
			}
		}
	}
	best, bestP := 0, -1
	for mk := 0; mk < 8; mk++ {
		m.applyMask(mk)
		m.drawFormat(mk)
		if p := m.penalty(); bestP < 0 || p < bestP {
			best, bestP = mk, p
		}
		m.applyMask(mk)
	}
	m.applyMask(best)
	m.drawFormat(best)
	return m.mod, ver, nil
}

// qrSVG renders modules as one path with a 4-module quiet zone on a white background.
func qrSVG(mod [][]bool) string {
	n := len(mod)
	var sb strings.Builder
	t := n + 8
	fmt.Fprintf(&sb, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges"><rect width="%d" height="%d" fill="#fff"/><path fill="#000" d="`, t, t, t, t)
	for y := 0; y < n; y++ {
		for x := 0; x < n; {
			if !mod[y][x] {
				x++
				continue
			}
			s := x
			for x < n && mod[y][x] {
				x++
			}
			fmt.Fprintf(&sb, "M%d %dh%dv1h-%dz", s+4, y+4, x-s, x-s)
		}
	}
	sb.WriteString(`"/></svg>`)
	return sb.String()
}
