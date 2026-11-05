#!/usr/bin/env bash
# 给网站右下角的萌宠「榕忆」接上大模型，让它能聊天。在服务器上运行：
#   sudo bash /var/www/beyond-horizons/deploy/pet-setup.sh
# 它会：问你用哪家大模型、让你粘贴 API key（输入时不显示）→ 存进 /etc/beyond-horizons/pet.env（只有 root 能读）
#      → 装好聊天服务（本机 127.0.0.1:8787，开机自启）→ 在网站的 nginx 配置里加上 /api/pet 转发 → 发一句“你好”试试。
# 换 key / 换模型：再运行一次。网站更新后只更新聊天程序（不重新输入 key）：
#   sudo bash /var/www/beyond-horizons/deploy/pet-setup.sh --update
# key 只在这台服务器上输入，不要发到聊天、截图、普通文件或仓库里。
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "请在命令前加 sudo 再运行"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
ENVF=/etc/beyond-horizons/pet.env
command -v python3 >/dev/null || { apt-get update -qq; apt-get install -y -qq python3 >/dev/null; }
command -v curl >/dev/null || apt-get install -y -qq curl >/dev/null

echo "==> 安装聊天程序"
install -d -m 755 /opt/beyond-horizons
install -m 644 "$HERE/pet_api.py" /opt/beyond-horizons/pet_api.py
install -m 644 "$HERE/pet-api.service" /etc/systemd/system/bh-pet.service

if [ "${1:-}" != "--update" ] || [ ! -f "$ENVF" ]; then
  echo
  echo "用哪家的大模型？（服务器在国内，建议选国内的，OpenAI / Claude 在国内服务器上一般连不上）"
  echo "  1) DeepSeek 深度求索（默认）   platform.deepseek.com"
  echo "  2) Kimi 月之暗面               platform.moonshot.cn"
  echo "  3) 通义千问 阿里云百炼          bailian.console.aliyun.com"
  echo "  4) 其他 OpenAI 兼容接口"
  echo "  5) Claude（Anthropic）"
  read -rp "输入编号 [1]: " n; n=${n:-1}
  case "$n" in
    2) PROV=openai; BASE=https://api.moonshot.cn/v1; MODEL=moonshot-v1-8k ;;
    3) PROV=openai; BASE=https://dashscope.aliyuncs.com/compatible-mode/v1; MODEL=qwen-plus ;;
    4) PROV=openai; read -rp "接口地址（例如 https://xxx.com/v1，不含 /chat/completions）: " BASE; MODEL=gpt-4o-mini ;;
    5) PROV=anthropic; BASE=https://api.anthropic.com; MODEL=claude-haiku-5-5 ;;
    *) PROV=openai; BASE=https://api.deepseek.com; MODEL=deepseek-chat ;;
  esac
  read -rp "模型名 [$MODEL]: " m; MODEL=${m:-$MODEL}
  KEY=""
  while [ -z "$KEY" ]; do
    read -rsp "粘贴 API key（输入时屏幕上不显示，粘贴后直接按回车）: " KEY; echo
    KEY=$(printf '%s' "$KEY" | tr -d '[:space:]')
  done
  case "$KEY" in *[!A-Za-z0-9._:-]*) echo "（提示：key 里有不常见的字符，如果后面测试失败，检查一下是不是复制多了东西）" ;; esac
  install -d -m 700 /etc/beyond-horizons
  ( umask 077; printf 'PET_PROVIDER=%s\nPET_API_BASE=%s\nPET_MODEL=%s\nPET_API_KEY=%s\n' "$PROV" "$BASE" "$MODEL" "$KEY" > "$ENVF" )
  chmod 600 "$ENVF"; unset KEY
  echo "==> key 已存进 $ENVF（只有 root 能读）"
fi

echo "==> 启动聊天服务"
systemctl daemon-reload
systemctl enable bh-pet >/dev/null 2>&1
systemctl restart bh-pet
sleep 1

echo "==> 在网站的 nginx 配置里加上 /api/pet"
NGX=$( [ -x /www/server/nginx/sbin/nginx ] && echo /www/server/nginx/sbin/nginx || command -v nginx || true )
changed=()
for f in /etc/nginx/sites-available/beyond-horizons* /etc/nginx/conf.d/beyond-horizons*.conf /www/server/panel/vhost/nginx/beyond-horizons*.conf; do
  [ -f "$f" ] || continue
  case "$f" in *.bak-pet) continue ;; esac
  grep -q '/api/pet' "$f" && continue
  grep -q 'try_files' "$f" || continue
  cp "$f" "$f.bak-pet"
  python3 - "$f" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding='utf-8').read()
block = ('    # 和榕忆聊天：转给本机的聊天服务（deploy/pet_api.py，key 在服务器上）\n'
         '    location ^~ /api/pet { proxy_pass http://127.0.0.1:8787; proxy_http_version 1.1; proxy_set_header Host $host; '
         'proxy_set_header X-Real-IP $remote_addr; proxy_read_timeout 45s; client_max_body_size 32k; }\n')
out = []
for line in s.split('\n'):
    if line.strip().startswith('location / {') and 'try_files' in line:
        out.append(block.rstrip('\n'))
    out.append(line)
open(p, 'w', encoding='utf-8').write('\n'.join(out))
PY
  changed+=("$f")
done
if [ ${#changed[@]} -gt 0 ]; then
  if [ -n "$NGX" ] && "$NGX" -t 2>/dev/null; then
    systemctl reload nginx 2>/dev/null || "$NGX" -s reload
    for f in "${changed[@]}"; do rm -f "$f.bak-pet"; echo "    已加到 $f"; done
  else
    for f in "${changed[@]}"; do mv -f "$f.bak-pet" "$f"; done
    echo "    nginx 配置检查没通过，已经还原，没有改动。把下面这段手动加到网站的 server { } 里："
    echo '    location ^~ /api/pet { proxy_pass http://127.0.0.1:8787; proxy_set_header X-Real-IP $remote_addr; proxy_read_timeout 45s; }'
  fi
else
  echo "    已经加过了（或没找到网站的 nginx 配置：先运行 deploy/install.sh）"
fi

echo "==> 试一下"
if curl -s --max-time 5 http://127.0.0.1:8787/api/pet/health | grep -q '"configured": true'; then
  r=$(curl -s --max-time 40 -X POST http://127.0.0.1:8787/api/pet -H 'Content-Type: application/json' \
      -d '{"messages":[{"role":"user","content":"你好呀，你是谁？"}],"ctx":{"stage":"小树苗","moisture":60,"attach":70,"hour":12}}')
  if printf '%s' "$r" | grep -q '"reply"'; then
    echo "    榕忆说：$(printf '%s' "$r" | python3 -c 'import sys,json; print(json.load(sys.stdin)["reply"])')"
    echo
    echo "完成！打开网站，抓到榕忆以后点右下角的它就能聊天了。"
  else
    echo "    聊天服务起来了，但问大模型失败：$r"
    echo "    多半是 key 不对、账户没余额，或模型名写错。再运行一次本脚本重新输入。查看日志：journalctl -u bh-pet -n 30"
  fi
else
  echo "    聊天服务没起来，查看日志：journalctl -u bh-pet -n 30"
fi
