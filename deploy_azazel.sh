#!/usr/bin/env bash
# ============================================================
# Azazel - DEPLOY. Vstaetsya v serialnuyu konsol Timeweb.
# Rabotaet BEZ SSH. Fajly berutsya s fiksirovannogo kommitta, skript lezhit v main.
# ============================================================
set -uo pipefail

SHA="main"
SHA_PIN="947eed2d1cd42f0759fa66cd99094b398161c922"
BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${SHA_PIN}"
DIR="/opt/azabot"
BACKUP="${DIR}/backup_$(date +%Y%m%d_%H%M%S)"
LIST="bot.py algo_config.py steps.py azazel_config.json azazel_config_loader.py continuation_engine.py continuation_engine_v2.py config.json autotrading_config.json azazel_api.py azabot.service install.sh .env.example test_cont_v2.py test_cont_v3.py scalping_framework_v2.py scalping_strategies.py"

echo "=== Azazel DEPLOY | pin ${SHA_PIN} ==="

echo "[1/10] dostup k GitHub s servera"
if ! curl -fsSL --max-time 25 "${BASE}/bot.py" -o /tmp/_probe.py; then
  echo "OSHIBKA: server ne vidit raw.githubusercontent.com"
  curl -sI --max-time 15 https://github.com | head -1
  exit 1
fi
echo "    ok"

echo "[2/10] bekap"
mkdir -p "${BACKUP}"
for f in ${LIST}; do
  [ -f "${DIR}/${f}" ] && cp -p "${DIR}/${f}" "${BACKUP}/" && echo "    bekap: ${f}"
done
echo "    bekap: ${BACKUP}"

echo "[3/10] zagruzka po SHA"
for f in ${LIST}; do
  curl -fsSL --max-time 30 "${BASE}/${f}" -o "${DIR}/${f}" || { echo "OSHIBKA: ne skachalsya ${f}"; exit 1; }
  echo "    ${f} (${DIR}/${f} $(stat -c%s "${DIR}/${f}") B)"
done

echo "[4/10] proverka sha256"
declare -A WANT=(
  [".env.example"]="d7fdc875ae98e4b0af261489ff020e922964d897ad3c965c641a95fb290753c9"
  ["algo_config.py"]="f8633b28a97183fcceac73aefb8fa95f24f0f034b45854ebda0e3463a7ce9b79"
  ["autotrading_config.json"]="6631e5b2c9200e8f7317abd680e29bd0aa08ea93997b83caefebd95c94455213"
  ["azabot.service"]="a274e24530a6c6967d3aa0e1182d8ba3d4f493b3fabdbbe887f9ea0ecb625f1e"
  ["azazel_api.py"]="0474ef36e080d3f1cff54df181ff0667fc7cf46c739b9b3ecf5b91606ba770ea"
  ["azazel_config.json"]="e75836e86d6f1755c3c0b6506f58f1feb1373a2a0874051b336ac32835dc3e42"
  ["azazel_config_loader.py"]="fbfe35648766756d1df7fe4afb9f95c352056562fda929a25630c881201a3c20"
  ["bot.py"]="778150bb26683674497e58250c7b39966bcf9e59b665f229f467237f950f9709"
  ["config.json"]="996496977f7e4a2b7720c66b232a04bbce89499914d6658ffc73c86025968591"
  ["continuation_engine.py"]="f19c9b163ffd7f3fb56b8fd826c871328e1c4affd536f252f5f6e7b69110e794"
  ["continuation_engine_v2.py"]="b15fb414918cd97c56648af1227cc9e34e0f266159314f607ce3da131e61e03a"
  ["install.sh"]="9e458e8d45c404a0a259465532456ae505179818e6ab5bb9b109801119eaed26"
  ["scalping_framework_v2.py"]="6af88e1c52eb0efb808e5b0785be5563f060bae5ea5519a3e00a5bae520cedbb"
  ["scalping_strategies.py"]="9a2ab547eb30706c02558154639ec4257bd256bead2a872df29186d34cd5a43a"
  ["steps.py"]="27ebc820e407b6352917e9ec8861658369e1a72fe2200923089a17956ff1d446"
  ["test_cont_v2.py"]="a8516b046e9ec071f1d1b34c0c4955372e6f2ce839b6c65131c9952474467364"
  ["test_cont_v3.py"]="4aa2501bc6520c1f0d6e489aa7899bee7096861be034c0f496a5520f5a1d65f0"
)
FAIL=0
for f in "${!WANT[@]}"; do
  GOT=$(sha256sum "${DIR}/${f}" | cut -d" " -f1)
  if [ "${GOT}" != "${WANT[$f]}" ]; then
    echo "    OSHIBKA sha256: ${f}"; FAIL=1
  else
    echo "    ok: ${f}"
  fi
done
[ $FAIL -ne 0 ] && { echo "OSHIBKA: checksumy ne sovpali - DEPLOY PRERVAN"; exit 1; }

echo "[5/10] sintaksis i testy"
cd "${DIR}"
python3 -c "import ast; ast.parse(open('bot.py',encoding='utf-8').read()); ast.parse(open('continuation_engine.py',encoding='utf-8').read())" \
  && echo "    sintaksis: OK" || { echo "OSHIBKA: sintaksis sloman"; exit 1; }
bash -n "${DIR}/install.sh" && echo "    install.sh: OK" || { echo "OSHIBKA: install.sh sloman"; exit 1; }
python3 "${DIR}/test_cont_v3.py" > /tmp/_t3.log 2>&1
RC3=$?; echo "    test_cont_v3 rc=${RC3}"; tail -2 /tmp/_t3.log | sed "s/^/      /"
[ ${RC3} -ne 0 ] && { echo "OSHIBKA: testy v3 ne proshli"; exit 1; }
python3 "${DIR}/test_cont_v2.py" > /tmp/_t2.log 2>&1
RC2=$?; echo "    test_cont_v2 rc=${RC2}"; tail -2 /tmp/_t2.log | sed "s/^/      /"

echo "[6/10] .env"
if [ -f "${DIR}/.env" ]; then
  echo "    .env uzhe est - ne trogayu"
else
  cp "${DIR}/.env.example" "${DIR}/.env" && chmod 600 "${DIR}/.env" && echo "    sozdan .env iz .env.example (tokeny pustye - zapolni!)"
fi

echo "[7/10] servis bota"
cp -f "${DIR}/azabot.service" /etc/systemd/system/azabot.service 2>/dev/null && echo "    unit: ok" || echo "    VNIHMANIE: net prav na /etc/systemd/system"
systemctl daemon-reload && echo "    daemon-reload: ok"
systemctl enable azabot.service >/dev/null 2>&1 && echo "    enable: ok"
systemctl restart azabot.service
sleep 7
systemctl is-active azabot.service | sed "s/^/    status: /"

echo "[8/10] server API dlya metrik"
cat > /etc/systemd/system/azazelapi.service <<'UNIT'
[Unit]
Description=Azazel Metrics API
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/azabot
EnvironmentFile=-/opt/azabot/.env
Environment=AZAZEL_API_PORT=8787
ExecStart=/usr/bin/python3 /opt/azabot/azazel_api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload >/dev/null 2>&1
systemctl enable azazelapi.service >/dev/null 2>&1 && echo "    enable azazelapi: ok" || echo "    VNIHMANIE: net prav na enable"
systemctl restart azazelapi.service
sleep 4
API_ST=$(systemctl is-active azazelapi.service)
echo "    status azazelapi: ${API_ST}"
if [ "${API_ST}" = "active" ]; then
  curl -fsS --max-time 8 http://127.0.0.1:8787/health && echo "" || echo "    VNIHMANIE: /health ne otvechaet"
else
  journalctl -u azazelapi.service -n 10 --no-pager 2>/dev/null | sed "s/^/      /"
fi

echo "[9/10] publichnyy dostup k API (cloudflared tunnel)"
TUNNEL_URL=""
CF_BIN="/usr/local/bin/cloudflared"
if [ ! -x "${CF_BIN}" ]; then
  echo "    cloudflared ne ustanovlen - stavlyu"
  if curl -fsSL --max-time 120 https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o "${CF_BIN}"; then
    chmod +x "${CF_BIN}"
    echo "    ustanovlen: $(${CF_BIN} --version 2>&1 | head -1)"
  else
    echo "    VNIHMANIE: ne udalos skachat cloudflared - tunel propushchen"
  fi
fi
if [ -x "${CF_BIN}" ]; then
  cat > /etc/systemd/system/azazel-tunnel.service <<'TUNIT'
[Unit]
Description=Azazel Cloudflare tunnel
After=network.target azazelapi.service
Wants=azazelapi.service

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8787 --logfile /var/log/azazel-tunnel.log
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
TUNIT
  systemctl daemon-reload >/dev/null 2>&1
  systemctl enable azazel-tunnel.service >/dev/null 2>&1 && echo "    enable tunel: ok"
  systemctl restart azazel-tunnel.service
  sleep 20
  TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /var/log/azazel-tunnel.log 2>/dev/null | tail -1)
  if [ -z "${TUNNEL_URL}" ]; then
    TUNNEL_URL=$(journalctl -u azazel-tunnel.service -n 60 --no-pager 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1)
  fi
  if [ -n "${TUNNEL_URL}" ]; then
    echo "    tunel: ${TUNNEL_URL}"
    curl -fsS --max-time 12 "${TUNNEL_URL}/health" && echo "" || echo "    VNIHMANIE: tunel est, no /health ne otvechaet"
  else
    echo "    VNIHMANIE: URL ne izvlechen (prover /var/log/azazel-tunnel.log)"
    tail -10 /var/log/azazel-tunnel.log 2>/dev/null | sed "s/^/      /"
  fi
else
  echo "    PROPUSK: cloudflared nedostupen"
fi

echo "[10/10] proverka"
journalctl -u azabot.service -n 15 --no-pager 2>/dev/null | sed "s/^/    /"
[ -f /var/log/azabot.log ] && tail -15 /var/log/azabot.log | sed "s/^/    /"
grep -q "AZABOT_TOKEN=." "${DIR}/.env" && echo "    AZABOT_TOKEN: zapolnen" || echo "    VNIHMANIE: AZABOT_TOKEN pust"
grep -q "AIRTABLE_TOKEN=." "${DIR}/.env" && echo "    AIRTABLE_TOKEN: zapolnen" || echo "    VNIHMANIE: AIRTABLE_TOKEN pust"

if [ -n "${TUNNEL_URL}" ]; then echo "=== DEPLOY OK ${SHA_PIN} | API: ${TUNNEL_URL} ==="; else echo "=== DEPLOY OK ${SHA_PIN} | API lokalno: 127.0.0.1:8787 ==="; fi
