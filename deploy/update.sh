#!/usr/bin/env bash
# 从 GitHub 拉取网站的最新版本（有变化才更新），再给新的文本文件生成 .gz 副本，nginx 直接发压缩好的文件。
# 由 /etc/cron.d/beyond-horizons 每 15 分钟运行一次；带 --compress-only 只做压缩。
set -uo pipefail
ROOT=/var/www/beyond-horizons
cd "$ROOT" || exit 1
if [ "${1:-}" != "--compress-only" ] && [ -d .git ]; then
  old=$(git rev-parse HEAD)
  timeout 900 git fetch --depth 1 -q origin main || { echo "$(date '+%F %T') 拉取失败，下次再试"; exit 0; }
  new=$(git rev-parse FETCH_HEAD)
  [ "$old" = "$new" ] && exit 0
  git reset -q --hard FETCH_HEAD
  git clean -qfd -e '*.gz'
  echo "$(date '+%F %T') 已更新到 ${new:0:7}"
fi
# 源文件比 .gz 新（或没有 .gz）就重新压缩
find "$ROOT" -path "$ROOT/.git" -prune -o -type f \( -name '*.html' -o -name '*.json' -o -name '*.js' -o -name '*.css' -o -name '*.svg' -o -name '*.txt' \) -size +1k -print |
  while IFS= read -r f; do if [ ! -e "$f.gz" ] || [ "$f" -nt "$f.gz" ]; then gzip -kf9 "$f"; fi; done
# 源文件已删掉的 .gz 也删掉
find "$ROOT" -path "$ROOT/.git" -prune -o -type f -name '*.gz' -print | while IFS= read -r g; do [ -f "${g%.gz}" ] || rm -f "$g"; done
# 偶尔清理一下 .git，免得越存越大
if [ -d .git ] && [ $((RANDOM % 40)) -eq 0 ]; then git gc -q --prune=now 2>/dev/null || true; fi
exit 0
