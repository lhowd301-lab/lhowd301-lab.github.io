#!/usr/bin/env bash
# Beyond Horizons：在 Ubuntu 服务器上用 nginx 把这个网站发布出去，并每 15 分钟自动从 GitHub 同步最新版本。
# 不会动服务器上原有的网站：默认单独开在 8080 端口（被占用就顺延到 8081 / 8088 / 8888），也可以指定：PORT=9000
# 在服务器上运行（一行，复制粘贴进终端）：
#   sudo apt-get install -y git && sudo git clone --depth 1 https://github.com/lhowd301-lab/lhowd301-lab.github.io.git /var/www/beyond-horizons && sudo bash /var/www/beyond-horizons/deploy/install.sh
# 重复运行也没关系。
set -euo pipefail
ROOT=/var/www/beyond-horizons
REPO=https://github.com/lhowd301-lab/lhowd301-lab.github.io.git
[ "$(id -u)" = 0 ] || { echo "请在命令前加 sudo 再运行"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

busy() { ss -ltnH "( sport = :$1 )" 2>/dev/null | grep -q .; }
echo "==> 现在服务器上在用的网页端口："
ss -ltnpH 2>/dev/null | awk '{print "    " $4 "  " $6}' | grep -E ':(80|443|8080|8081|8088|8888) ' || echo "    （80 / 443 / 8080 都空着）"

# 用哪个 nginx：宝塔面板自带的，或者系统的（没有就装一个，但先不让它自己启动，免得抢原来网站的 80 端口）
if [ -x /www/server/nginx/sbin/nginx ] && [ -d /www/server/panel/vhost/nginx ]; then
  NGX=/www/server/nginx/sbin/nginx; CONF=/www/server/panel/vhost/nginx/beyond-horizons.conf; KIND=bt
  echo "==> 检测到宝塔面板，用它自带的 nginx"
  command -v git >/dev/null || apt-get install -y -qq git >/dev/null
else
  KIND=sys
  if ! command -v nginx >/dev/null 2>&1; then
    echo "==> 安装 nginx"
    printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; chmod +x /usr/sbin/policy-rc.d
    apt-get update -qq; apt-get install -y -qq nginx git >/dev/null
    rm -f /usr/sbin/policy-rc.d
    rm -f /etc/nginx/sites-enabled/default   # 刚装的 nginx 自带的示例页，没人用，免得它去占 80 端口
  else
    echo "==> 用服务器上已有的 nginx（原来的网站配置一律不动）"
    command -v git >/dev/null || apt-get install -y -qq git >/dev/null
  fi
  NGX=$(command -v nginx)
  if [ -d /etc/nginx/sites-available ]; then CONF=/etc/nginx/sites-available/beyond-horizons; else CONF=/etc/nginx/conf.d/beyond-horizons.conf; fi
fi

# 端口：之前装过就沿用，否则从 8080 起找一个空的
if [ -z "${PORT:-}" ] && [ -f "$CONF" ]; then PORT=$(grep -oE 'listen [0-9]+' "$CONF" | head -1 | awk '{print $2}'); fi
if [ -z "${PORT:-}" ]; then
  for p in 8080 8081 8088 8888; do busy "$p" || { PORT=$p; break; }; done
fi
[ -n "${PORT:-}" ] || { echo "8080/8081/8088/8888 都被占用了，请用 PORT=端口号 指定一个"; exit 1; }
if busy "$PORT" && ! ss -ltnpH "( sport = :$PORT )" | grep -q nginx; then echo "$PORT 端口已被别的程序占用，请用 PORT=端口号 换一个"; exit 1; fi

if [ ! -d "$ROOT/.git" ] && [ ! -f "$ROOT/index.html" ]; then
  echo "==> 从 GitHub 下载网站（约 220 MB，视网络需要几分钟）"
  git clone --depth 1 "$REPO" "$ROOT"
fi
[ -f "$ROOT/index.html" ] || { echo "在 $ROOT 里没找到网站文件"; exit 1; }
git config --system --add safe.directory "$ROOT" 2>/dev/null || true

echo "==> 给文本文件生成压缩副本（访客下载量少一半左右）"
install -m 755 "$ROOT/deploy/update.sh" /usr/local/bin/bh-update
/usr/local/bin/bh-update --compress-only

echo "==> 配置 nginx：这个网站开在 $PORT 端口"
sed -e "s#__PORT__#$PORT#g" -e "s#__ROOT__#$ROOT#g" "$ROOT/deploy/nginx.conf" > "$CONF"
[ "$KIND" = sys ] && [ -d /etc/nginx/sites-enabled ] && ln -sf "$CONF" /etc/nginx/sites-enabled/beyond-horizons
if ! "$NGX" -t 2>/dev/null; then sed -i '/gzip_static/d' "$CONF"; fi      # 个别 nginx 没编译 gzip_static
if ! "$NGX" -t 2>/dev/null; then sed -i '/listen \[::\]/d' "$CONF"; fi    # 没开 IPv6 的机器
"$NGX" -t
if [ "$KIND" = bt ]; then "$NGX" -s reload; else
  systemctl enable nginx >/dev/null 2>&1 || true
  if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
fi
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow "$PORT"/tcp >/dev/null; fi

if [ -d "$ROOT/.git" ]; then
  echo "==> 每 15 分钟自动同步 GitHub 上的新版本"
  echo "*/15 * * * * root /usr/local/bin/bh-update >> /var/log/bh-update.log 2>&1" > /etc/cron.d/beyond-horizons
  chmod 644 /etc/cron.d/beyond-horizons
else
  echo "（网站是手动上传的，不是 git 下载的，所以不会自动同步更新）"
fi

IP=$(curl -s --max-time 3 http://metadata.tencentyun.com/latest/meta-data/public-ipv4 || true)
echo
echo "完成！原来的网站不受影响；这个网站在： http://${IP:-你的服务器公网IP}:$PORT"
echo "还要做一步：到腾讯云控制台这台服务器的「防火墙」里，添加一条规则放通 TCP $PORT 端口，外面才打得开。"
