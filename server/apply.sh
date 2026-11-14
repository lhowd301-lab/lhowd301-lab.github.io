#!/usr/bin/env bash
# 装上网站的更新包：把 /home/ubuntu 里最新的 bh-update-*.zip 解压到网站目录，删掉更新包里列出要删的旧文件，
# 再生成压缩副本、核对所有文件是否都是最新版。装到服务器上（只需一次）后，每次更新运行：sudo bh-apply
set -euo pipefail
ROOT=${BH_ROOT:-/var/www/beyond-horizons}; HOME_DIR=${BH_HOME:-/home/ubuntu}
Z=$(ls -t "$HOME_DIR"/bh-update-*.zip 2>/dev/null | head -1 || true)
[ -n "$Z" ] || { echo "在 $HOME_DIR 里没找到 bh-update-*.zip，先把更新包传上来"; exit 1; }
echo "==> 装上 $(basename "$Z")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
unzip -q "$Z" -d "$T"
if [ -f "$T/server/delete.txt" ]; then
  while IFS= read -r p; do case "$p" in ''|/*|*..*) continue;; esac; rm -f "$ROOT/$p" "$ROOT/$p.gz"; done < "$T/server/delete.txt"
  rm -f "$T/server/delete.txt"
fi
cp -r "$T"/. "$ROOT"/
[ -x /usr/local/bin/bh-update ] && /usr/local/bin/bh-update --compress-only
if python3 "$ROOT/server/check.py"; then
  mkdir -p "$HOME_DIR/bh-old"; mv "$Z" "$HOME_DIR/bh-old/"; echo "更新完成：$(basename "$Z")（用过的更新包移到了 $HOME_DIR/bh-old）"
else
  echo "更新包已经装上，但上面列出的文件和最新版不一致，把截图发给我"; exit 1
fi
