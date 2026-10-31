#!/usr/bin/env bash
# NDK r29 job (owner-approved 2026-10-29): detached WSL job, survives Claude limits.
# Launch (PowerShell): wsl bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh ndk29 /mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency/repack/ndk29_job.sh
# Log ~/detached/ndk29.log; progress lines -> repack/STATUS.md; result -> repack/VERDICT.md. Stop: touch repack/STOP_ndk29
# Steps (each idempotent, marker in ~/ndk29job/done.<step>; re-running the script resumes):
#  1 download the official NDK r29 (Linux) whose clang matches the original build (Android 13989888, r563880c, clang 21.0.0;
#    tries r29, r29-beta4..1 in order, sha1 from Google's repository2-3.xml), wget -c to .part, sha1, mv, unzip
#  2 rebuild the UNMODIFIED libggml-hexagon.so with the exact build.ninja flags (-flto -g, prebuilt htp_iface_stub.c.o) and path
#    prefix maps to the original /workspace, /opt/android-ndk-r29, /opt/hexagon/6.6.0.0 paths; compare with 5587a193...
#  3 rebuild the rp1 patch with the same toolchain
#  4 board: lib_rb29 + lib_rp29 (full copies of lib/, only libggml-hexagon.so replaced; .part + md5 + mv), then ONE lab window
#    (lab_run.sh via Git Bash) base / rb29 / rp29 when the app runs and nothing else holds the board
#  5 score.js + VERDICT.md (rp29 deployable only if identical text 6/6 vs base AND faster load). Never deploys.
set -u
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency; J=$P/repack; ST=$J/STATUS.md; STOP=$J/STOP_ndk29
M=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master; K=$M/BOARD_LOCK
A=/mnt/c/Users/hp/Desktop/qidk/Code/platform-tools/adb.exe; GB="/mnt/c/Program Files/Git/bin/bash.exe"; NODE="/mnt/c/Program Files/nodejs/node.exe"
L=/mnt/c/Users/hp/gpu_work/llama.cpp; G=$L/ggml/src/ggml-hexagon; B=$L/build-snapdragon
SDK=/mnt/c/Qualcomm/Hexagon_SDK/6.7.0.1
S=$HOME/ndk29job; mkdir -p $S $HOME/ndk; OUT=$J/ndk29; mkdir -p $OUT
ORIG_MD5=5587a193acca52219c6596581929dfdb; WANT_CLANG=13989888; WIN=rp29_ab
BL=/data/local/tmp/llama.cpp

log() { echo "$(date '+%F %T') $*"; }
st() { log "STATUS: $*"; echo "- $(date '+%m-%d %H:%M') ndk29: $*" >> $ST; }
die() { st "STOPPED: $*"; unlock; exit 1; }
stopchk() { [ -e $STOP ] && die "STOP file present"; true; }
freeram_mb() { powershell.exe -NoProfile -Command "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r '; }
ramguard() {  # Windows free RAM >= 1.5 GB (waits up to 2 h)
  local i=0 r
  while :; do stopchk; r=$(freeram_mb); [ -n "$r" ] && [ "$r" -ge 1536 ] && return 0
    [ $i -eq 0 ] && st "waiting: Windows free RAM ${r:-?} MB < 1536"; i=$((i+1)); [ $i -gt 120 ] && die "Windows RAM low for 2 h"; sleep 60; done
}
diskguard() { local f; f=$(df -Pm $HOME | awk 'NR==2 {print $4}'); [ "$f" -ge 5120 ] || die "WSL disk free ${f} MB < 5 GB"
  f=$(df -Pm /mnt/c | awk 'NR==2 {print $4}'); [ "$f" -ge 1024 ] || die "C: free ${f} MB < 1 GB"; }
done_() { touch $S/done.$1; }
isdone() { [ -e $S/done.$1 ]; }
HAVE_LOCK=0
unlock() { if [ $HAVE_LOCK = 1 ] && [ "$(cat $K 2>/dev/null)" = ndk29 ]; then rm -f $K; HAVE_LOCK=0; fi; true; }
trap unlock EXIT

st "job start (pid $$, log ~/detached/ndk29.log)"
stopchk; diskguard

# ---------- 1. NDK r29 ----------
NDK=""
if isdone ndk; then NDK=$(cat $S/ndk_dir); log "step 1 done before: $NDK"; else
  ramguard
  curl -sfL https://dl.google.com/android/repository/repository2-3.xml -o $S/repo.xml || die "cannot fetch repository2-3.xml"
  for v in r29 r29-beta4 r29-beta3 r29-beta2 r29-beta1; do
    stopchk; diskguard
    z=android-ndk-$v-linux.zip; d=$HOME/ndk/android-ndk-$v
    sha=$(grep -B6 "<url>$z</url>" $S/repo.xml | grep -o '<checksum type="sha1">[0-9a-f]*' | sed 's/.*>//' | tail -1)
    if [ ! -x $d/toolchains/llvm/prebuilt/linux-x86_64/bin/clang ]; then
      if [ ! -e $HOME/ndk/$z ]; then
        st "downloading $z (sha1 ${sha:-unpublished})"
        wget -q -c -O $HOME/ndk/$z.part https://dl.google.com/android/repository/$z || die "download $z failed (re-run resumes)"
        got=$(sha1sum $HOME/ndk/$z.part | cut -d' ' -f1)
        if [ -n "$sha" ] && [ "$got" != "$sha" ]; then rm -f $HOME/ndk/$z.part; die "$z sha1 $got != $sha (deleted, re-run)"; fi
        mv $HOME/ndk/$z.part $HOME/ndk/$z; st "$z sha1 $got ok"
      fi
      rm -rf $HOME/ndk/unz.$v; mkdir -p $HOME/ndk/unz.$v
      unzip -q $HOME/ndk/$z -d $HOME/ndk/unz.$v || die "unzip $z failed"
      mv $HOME/ndk/unz.$v/android-ndk-* $d && rm -rf $HOME/ndk/unz.$v && rm -f $HOME/ndk/$z
    fi
    cv=$($d/toolchains/llvm/prebuilt/linux-x86_64/bin/clang --version | head -1)
    rev=$(grep Pkg.Revision $d/source.properties | tr -d '\r')
    if echo "$cv" | grep -q "$WANT_CLANG"; then st "NDK $v ($rev) clang matches the original: $cv"; NDK=$d; break; fi
    st "NDK $v ($rev) clang differs: $cv"
  done
  if [ -z "$NDK" ]; then NDK=$HOME/ndk/android-ndk-r29; st "no r29 clang matches $WANT_CLANG; using r29 stable"; fi
  echo $NDK > $S/ndk_dir; done_ ndk
fi
[ -x $NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/clang++ ] || die "NDK missing at $NDK"
T=$NDK/toolchains/llvm/prebuilt/linux-x86_64

# ---------- 2/3. builds (exact build.ninja flags) ----------
TGT="--target=aarch64-none-linux-android34 --sysroot=$T/sysroot"
MAP="-ffile-prefix-map=$L=/workspace -ffile-prefix-map=$NDK=/opt/android-ndk-r29 -ffile-prefix-map=$SDK=/opt/hexagon/6.6.0.0"
DEF="-DGGML_BACKEND_BUILD -DGGML_BACKEND_SHARED -DGGML_SCHED_MAX_COPIES=4 -DGGML_SHARED -D_GNU_SOURCE -D_XOPEN_SOURCE=600 -Dggml_hexagon_EXPORTS"
FL="-g -DANDROID -fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -no-canonical-prefixes -D_FORTIFY_SOURCE=2 -Wformat -Werror=format-security  -march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -flto -D_GNU_SOURCE -isystem $T/sysroot/usr/include/c++/v1/ -O3 -DNDEBUG -O3 -DNDEBUG -std=gnu++17 -fPIC -Xclang -fno-pch-timestamp -Wmissing-declarations -Wmissing-noreturn -Wall -Wextra -Wpedantic -Wcast-qual -Wno-unused-function -Wunreachable-code-break -Wunreachable-code-return -Wmissing-prototypes -Wextra-semi"
LCF="-g -DANDROID -fdata-sections -ffunction-sections -funwind-tables -fstack-protector-strong -no-canonical-prefixes -D_FORTIFY_SOURCE=2 -Wformat -Werror=format-security  -march=armv8.7a+fp16+dotprod+i8mm -fvectorize -ffp-model=fast -fno-finite-math-only -flto -D_GNU_SOURCE -isystem $T/sysroot/usr/include/c++/v1/ -O3 -DNDEBUG -O3 -DNDEBUG"
# $1 = dir holding ggml-hexagon.cpp (the original dir, or a copy mapped onto it), $2 = output .so
build() {
  local src=$1 out=$2 w; w=$(mktemp -d)
  local INC="-I$SDK/ipc/fastrpc/rtld/ship/android_aarch64 -I$G/.. -I$G/htp -I$B/ggml/src/ggml-hexagon -I$L/ggml/src/../include -I$SDK/incs -I$SDK/incs/stddef -I$SDK/utils/examples"
  local map2=""; [ "$src" != "$G" ] && map2="-ffile-prefix-map=$src=/workspace/ggml/src/ggml-hexagon" && INC="$INC -I$G"
  ( cd $w && $T/bin/clang++ $TGT $DEF $INC $FL $map2 $MAP -fdebug-compilation-dir=/workspace/build-snapdragon -c $src/ggml-hexagon.cpp -o $w/a.o ) || { rm -rf $w; return 1; }
  ( cd $w && $T/bin/clang++ $TGT $DEF $INC $FL $MAP -fdebug-compilation-dir=/workspace/build-snapdragon -c $G/htp-drv.cpp -o $w/b.o ) || { rm -rf $w; return 1; }
  cp $B/ggml/src/ggml-hexagon/CMakeFiles/htp_iface.dir/htp_iface_stub.c.o $w/s.o
  ( cd $w && $T/bin/clang++ $TGT -fPIC $LCF -static-libstdc++ -Wl,--build-id=sha1 -Wl,--no-undefined-version -Wl,--fatal-warnings -Wl,--no-undefined -Qunused-arguments  -Wl,--gc-sections   -llog -ldl -Xlinker --dependency-file=$w/link.d -shared -Wl,-soname,libggml-hexagon.so -o $out $w/s.o $w/a.o $w/b.o $B/bin/libggml-base.so -latomic -lm ) || { rm -rf $w; return 1; }
  rm -rf $w
}
secmd5() {  # per-section md5 (alloc sections) of $1
  local f=$1 s; for s in .text .rodata .data.rel.ro .data .eh_frame .dynsym .dynstr .rela.dyn; do
    $T/bin/llvm-objcopy -O binary --only-section=$s $f /tmp/ndk29_sec.bin 2>/dev/null && echo "$s $(md5sum < /tmp/ndk29_sec.bin | cut -c1-32) $(stat -c %s /tmp/ndk29_sec.bin)"; done; rm -f /tmp/ndk29_sec.bin
}
if ! isdone rb29; then
  stopchk; ramguard; diskguard; st "step 2: building unmodified lib with $(basename $NDK)"
  build $G $OUT/libggml-hexagon.rb29.so 2> $OUT/build_rb29.err || die "rb29 build failed (see repack/ndk29/build_rb29.err)"
  m=$(md5sum $OUT/libggml-hexagon.rb29.so | cut -d' ' -f1)
  secmd5 $B/bin/libggml-hexagon.so > $OUT/sections_orig.txt; secmd5 $OUT/libggml-hexagon.rb29.so > $OUT/sections_rb29.txt
  $T/bin/llvm-strip --strip-all -o $OUT/orig.stripped.so $B/bin/libggml-hexagon.so; $T/bin/llvm-strip --strip-all -o $OUT/rb29.stripped.so $OUT/libggml-hexagon.rb29.so
  $T/bin/llvm-readelf -S -W $B/bin/libggml-hexagon.so > $OUT/readelf_orig.txt; $T/bin/llvm-readelf -S -W $OUT/libggml-hexagon.rb29.so > $OUT/readelf_rb29.txt
  if [ "$m" = "$ORIG_MD5" ]; then st "rb29 md5 $m == original: toolchain matched exactly"
  else
    tx=$(diff <(grep '^.text ' $OUT/sections_orig.txt) <(grep '^.text ' $OUT/sections_rb29.txt) > /dev/null && echo same || echo DIFFERENT)
    st "rb29 md5 $m != original $ORIG_MD5 (size $(stat -c %s $OUT/libggml-hexagon.rb29.so) vs $(stat -c %s $B/bin/libggml-hexagon.so)); .text $tx; stripped md5 $(md5sum < $OUT/rb29.stripped.so | cut -c1-32) vs $(md5sum < $OUT/orig.stripped.so | cut -c1-32); sections: repack/ndk29/sections_*.txt"
  fi
  done_ rb29
fi
if ! isdone rp29; then
  stopchk; ramguard; diskguard; st "step 3: building rp1 patch"
  rm -rf $S/rpsrc; mkdir -p $S/rpsrc; cp $J/src/ggml-hexagon.rp.cpp $S/rpsrc/ggml-hexagon.cpp
  build $S/rpsrc $OUT/libggml-hexagon.rp29.so 2> $OUT/build_rp29.err || die "rp29 build failed (see repack/ndk29/build_rp29.err)"
  secmd5 $OUT/libggml-hexagon.rp29.so > $OUT/sections_rp29.txt
  st "rp29 md5 $(md5sum $OUT/libggml-hexagon.rp29.so | cut -d' ' -f1)"
  done_ rp29
fi
( cd $OUT && md5sum libggml-hexagon.rb29.so libggml-hexagon.rp29.so > md5.txt )

# ---------- 4. board ----------
sh_() { $A shell "$@" | tr -d '\r'; }
board_free() {  # app up, no other lab window / deploy, no lock, no demo
  [ -e $P/DEMO_NOW ] && { echo "DEMO_NOW"; return 1; }
  if [ -e $K ] && [ "$(cat $K 2>/dev/null)" != ndk29 ] && [ $(( $(date +%s) - $(stat -c %Y $K) )) -lt 10800 ]; then echo "BOARD_LOCK ($(cat $K))"; return 1; fi
  local wp; wp=$(powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | % { \$_.CommandLine } | Select-String -Pattern 'deplo[y][0-9a-z_]*\.sh|la[b]_run\.sh|la[b]_ab\.sh' | Measure-Object | % Count" 2>/dev/null | tr -d '\r ')
  [ "${wp:-0}" != 0 ] && { echo "laptop deploy/lab script running"; return 1; }
  pgrep -f 'deploy[0-9a-z_]*\.sh|lab_run\.sh' > /dev/null && { echo "WSL deploy/lab script running"; return 1; }
  local ps; ps=$(sh_ "ps -A -o NAME=,ARGS=")
  echo "$ps" | grep -q "lab_ab.sh" && { echo "board lab_ab.sh running"; return 1; }
  echo "$ps" | grep -q "^edge-agent" && echo "$ps" | grep -q "^htpd" || { echo "app not running"; return 1; }
  return 0
}
pushlib() {  # $1 dir name, $2 local .so
  local d=$BL/$1 m; m=$(md5sum $2 | cut -d' ' -f1)
  if [ "$(sh_ "md5sum $d/libggml-hexagon.so 2>/dev/null" | cut -d' ' -f1)" = "$m" ]; then log "$1 already on board"; return 0; fi
  sh_ "rm -rf $d.part $d && cp -rp $BL/lib $d.part" || return 1
  $A push "$(wslpath -w $2)" $d.part/libggml-hexagon.so.part > /dev/null || return 1
  [ "$(sh_ "md5sum $d.part/libggml-hexagon.so.part" | cut -d' ' -f1)" = "$m" ] || return 1
  sh_ "mv $d.part/libggml-hexagon.so.part $d.part/libggml-hexagon.so && mv $d.part $d && md5sum $BL/lib/libggml-hexagon.so $d/libggml-hexagon.so" >> $OUT/board_md5.txt
  [ "$(sh_ "md5sum $d/libggml-hexagon.so 2>/dev/null" | cut -d' ' -f1)" = "$m" ]
}
if ! isdone window; then
  stopchk
  i=0; while :; do stopchk; why=$(board_free) && break
    [ $((i % 15)) -eq 0 ] && st "waiting for the board: $why"; i=$((i+1)); [ $i -gt 720 ] && die "board not free for 12 h"; sleep 60; done
  ramguard
  echo ndk29 > $K; HAVE_LOCK=1; ( while [ -e $K ] && [ "$(cat $K 2>/dev/null)" = ndk29 ]; do touch $K; sleep 600; done ) &
  [ "$(sh_ "md5sum $BL/lib/libggml-hexagon.so" | cut -d' ' -f1)" = "$ORIG_MD5" ] || die "live lib md5 is not $ORIG_MD5: not touching anything"
  pushlib lib_rb29 $OUT/libggml-hexagon.rb29.so || die "push lib_rb29 failed"
  pushlib lib_rp29 $OUT/libggml-hexagon.rp29.so || die "push lib_rp29 failed"
  st "step 4: lib_rb29 + lib_rp29 on the board (live lib untouched); starting lab window $WIN (base, rb29, rp29; ~30 min, app stopped)"
  stopchk; board_free > /dev/null || die "board became busy"
  "$GB" -c "cd /c/Users/hp/Desktop/qidk/proofs/2026-10-29_latency && WINDOW_MAX=2700 REQS='10 a 10 a 11 a 12 a 13 a 14 a 15' bash lab_run.sh $WIN \
    'base,htpd_v8x5,qwen35_reasoner_q4_0.gguf,X=0' \
    'rb29,htpd_v8x5,qwen35_reasoner_q4_0.gguf,LD_LIBRARY_PATH=$BL/lib_rb29 ADSP_LIBRARY_PATH=$BL/lib_rb29' \
    'rp29,htpd_v8x5,qwen35_reasoner_q4_0.gguf,LD_LIBRARY_PATH=$BL/lib_rp29 ADSP_LIBRARY_PATH=$BL/lib_rp29 GGML_HEXAGON_REPACK_THREADS=8 GGML_HEXAGON_REPACK_STATS=1'" > $OUT/lab_run_out.txt 2>&1
  unlock
  tail -1 $P/$WIN/ab.log 2>/dev/null | grep -q "lab ab done (ok)" || { st "lab window did not finish ok: $(tail -1 $P/$WIN/ab.log 2>/dev/null)"; die "window not ok (see $WIN/ab.log); re-running the job retries the window"; }
  st "lab window done: $(grep -c . $P/$WIN/ab.log) log lines; app: $(sh_ 'ps -A -o NAME= | grep -E "^(edge-agent|htpd)" | tr "\n" " "')"
  done_ window
fi

# ---------- 5. score + verdict ----------
D=$P/$WIN
for f in $P/repack_ab/base_q*.json; do [ -e "$f" ] && cp $f $D/base0_${f##*/base_}; done  # base from the earlier window: run-to-run check
SC=$("$NODE" "$(wslpath -w $P/score.js)" "$(wslpath -w $D)" base base0 rb29 rp29 2>&1 | tr -d '\r')
echo "$SC" > $OUT/score.txt
ld() { grep -h "reasoner load phases" $D/htpd_$1.log | sed -n 's/.*model \([0-9]*\) ms.*/\1/p' | awk '{s+=$1;n++; a[n]=$1} END {if(n) printf "%.0f ms mean of %d (", s/n, n; for(i=1;i<=n;i++) printf "%s%s", a[i], (i<n?" ":""); if(n) printf ")"}'; }
bk() { grep -h "agents' model back in" $D/htpd_$1.log | sed -n "s/.*model back in \([0-9]*\) ms.*/\1/p" | awk '{s+=$1;n++} END {if(n) printf "%.0f ms mean of %d", s/n, n}'; }
ldm() { grep -h "reasoner load phases" $D/htpd_$1.log | sed -n 's/.*model \([0-9]*\) ms.*/\1/p' | awk '{s+=$1;n++} END {print (n? s/n : 0)}'; }
idt() { echo "$SC" | grep "^$1:" | sed -n 's/.*identical text=\([0-9]*\).*/\1/p'; }
nq() { echo "$SC" | grep "^$1:" | sed -n 's/.*n=\([0-9]*\).*/\1/p'; }
b=$(ldm base); r=$(ldm rp29); ir=$(idt rp29); nr=$(nq rp29)
faster=$(awk -v b="$b" -v r="$r" 'BEGIN {print (r > 0 && b > 0 && r < b) ? "yes" : "no"}')
if [ "${ir:-0}" = "${nr:-x}" ] && [ "${nr:-0}" -ge 6 ] && [ "$faster" = yes ]; then V="DEPLOYABLE (identical text ${ir}/${nr} vs base and faster load) - not deployed; owner decides"
else V="NOT deployable (identical text ${ir:-?}/${nr:-?} vs base, load faster: $faster)"; fi
{
  echo "# Verdict: parallel repack built with NDK $(basename $NDK) (job ndk29, $(date '+%F %T'))"
  echo; echo "**rp29: $V**"; echo
  echo "## Toolchain"; echo "- NDK: $NDK ($(grep Pkg.Revision $NDK/source.properties | tr -d '\r')); clang: $($T/bin/clang --version | head -1)"
  echo "- original libggml-hexagon.so md5 $ORIG_MD5; rb29 (unmodified, this toolchain) md5 $(md5sum < $OUT/libggml-hexagon.rb29.so | cut -c1-32); rp29 md5 $(md5sum < $OUT/libggml-hexagon.rp29.so | cut -c1-32)"
  echo "- per-section md5 (orig vs rb29):"; echo '```'; paste $OUT/sections_orig.txt $OUT/sections_rb29.txt; echo '```'
  echo "## Lab window $WIN (base = live lib; rb29 = unmodified r29 rebuild; rp29 = rp1 patch, 8 threads)"
  echo '```'; echo "$SC"; echo '```'
  echo "base0 = base answers from the earlier repack_ab window (run-to-run reference)."; echo
  for c in base rb29 rp29; do echo "- $c: reasoner load (model phase) $(ld $c); agents' model back $(bk $c)"; done
  echo "- rp29 repack stats: $(grep -h 'repack stats' $D/htpd_rp29.log | head -3 | tr '\n' ';')"
  echo; echo "Rule: rp29 deployable only if identical text 6/6 vs base AND faster reasoner load. Nothing was deployed."
} > $J/VERDICT.md
st "step 5: $V -> repack/VERDICT.md"
st "job done"
