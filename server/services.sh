#!/usr/bin/env bash
# 把网站更新包里带的服务程序装上并重启：榕忆聊天（deploy/pet_api.py → bh-pet）、网站后台（deploy/bh_admin.py → bh-admin）。
# 只更新已经装过的服务；程序没变就不动。sudo bh-apply 装完更新包后会自动运行这一步，也可以单独运行：
#   sudo bash /var/www/beyond-horizons/server/services.sh
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "请在命令前加 sudo 再运行"; exit 1; }
ROOT=${BH_ROOT:-/var/www/beyond-horizons}; D="$ROOT/deploy"; O=/opt/beyond-horizons
put() { if [ -f "$1" ] && ! cmp -s "$1" "$2"; then install -D -m 644 "$1" "$2"; return 0; fi; return 1; }
up() {   # 重启并确认服务起来了
  systemctl daemon-reload; systemctl restart "$1"; sleep 1.5
  if systemctl is-active --quiet "$1"; then echo "    $2已更新并重启"; else echo "    $2没起来，看看报错（截图发给我）："; journalctl -u "$1" -n 15 --no-pager; fi
}
echo "==> 更新服务程序"
if [ -f /etc/systemd/system/bh-pet.service ]; then
  c=0; put "$D/pet_api.py" "$O/pet_api.py" && c=1; put "$D/pet-api.service" /etc/systemd/system/bh-pet.service && c=1
  if [ $c = 1 ]; then up bh-pet "榕忆聊天"; else echo "    榕忆聊天：已经是最新"; fi
else
  echo "    （榕忆聊天还没装：要接 AI 的话运行 sudo bash $D/pet-setup.sh）"
fi
if [ -f /etc/systemd/system/bh-admin.service ]; then
  c=0; put "$D/bh_admin.py" "$O/bh_admin.py" && c=1; put "$D/ip2region_v4.xdb" "$O/ip2region_v4.xdb" && c=1
  for f in "$D"/ip2region/*.py; do put "$f" "$O/ip2region/$(basename "$f")" && c=1; done
  put "$D/bh-admin.service" /etc/systemd/system/bh-admin.service && c=1
  if [ $c = 1 ]; then up bh-admin "网站后台"; else echo "    网站后台：已经是最新"; fi
else
  echo "    （网站后台还没装：要用的话运行 sudo bash $D/admin-setup.sh）"
fi
# 后台转发允许传大一点的文件（背景音乐最大 60 MB）：把旧配置里的 client_max_body_size 10m 改成 64m（nginx 检查不通过就还原）
NGX=$( [ -x /www/server/nginx/sbin/nginx ] && echo /www/server/nginx/sbin/nginx || command -v nginx || true )
nchanged=()
for f in /etc/nginx/sites-available/beyond-horizons* /etc/nginx/conf.d/beyond-horizons*.conf /www/server/panel/vhost/nginx/beyond-horizons*.conf; do
  [ -f "$f" ] || continue
  case "$f" in *.bak*) continue ;; esac
  grep -q '127.0.0.1:8788.*client_max_body_size 10m' "$f" || continue
  cp "$f" "$f.bak-size"
  sed -i '/127.0.0.1:8788/ s/proxy_read_timeout 30s; client_max_body_size 10m;/proxy_read_timeout 120s; client_max_body_size 64m;/' "$f"
  nchanged+=("$f")
done
if [ ${#nchanged[@]} -gt 0 ]; then
  if [ -n "$NGX" ] && "$NGX" -t 2>/dev/null; then
    systemctl reload nginx 2>/dev/null || "$NGX" -s reload
    for f in "${nchanged[@]}"; do rm -f "$f.bak-size"; done; echo "    后台上传上限已改成 64 MB（可以传歌了）"
  else
    for f in "${nchanged[@]}"; do mv -f "$f.bak-size" "$f"; done; echo "    nginx 配置检查没通过，上传上限没改（截图发给我）"
  fi
fi
# bh-apply 自己也换成最新版
[ -f "$ROOT/server/apply.sh" ] && ! cmp -s "$ROOT/server/apply.sh" /usr/local/bin/bh-apply && install -m 755 "$ROOT/server/apply.sh" /usr/local/bin/bh-apply && echo "    bh-apply 已更新"
exit 0
