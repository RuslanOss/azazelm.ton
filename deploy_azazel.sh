#!/usr/bin/env bash
# ============================================================
# Azazel - DEPLOY. Vstaetsya v serialnuyu konsol Timeweb.
# Rabotaet BEZ SSH. Fajly berutsya s fiksirovannogo kommitta, skript lezhit v main.
# ============================================================
set -uo pipefail

SHA="main"
SHA_PIN="f2ed680681934a060652f783d30528c44c0326e7"
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

echo "[4/10] web-assety (ikonka Mini App)"
if [ "${ONLY_WEB:-0}" = "1" ]; then echo "    rezhim ONLY_WEB=1 - tolko web-assety"; fi
# Ikonka - belyj silujet v PNG. Vsyu logiku (WEBROOT, sha256, ochistka staryh JPEG,
# nginx reload, live-probe) derzhit otdelnyy skript, zdes zovem ego.
WEBASSETS_SHA="0b3413ea683eba5fc912a34f8c081d244ee10db5"
WEBASSETS_BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${WEBASSETS_SHA}"
if curl -fsSL --max-time 40 "${WEBASSETS_BASE}/deploy_web_assets.sh" -o /tmp/_deploy_web_assets.sh; then
  chmod +x /tmp/_deploy_web_assets.sh
  bash /tmp/_deploy_web_assets.sh || echo "    VNIHMANIE: web-assety s oshibkami"
else
  echo "    OSHIBKA: ne skachalsya deploy_web_assets.sh"
fi

if [ "${ONLY_WEB:-0}" = "1" ]; then
  echo "=== WEB-ASSETS DONE ==="
  exit 0
fi


echo "[5/11] proverka sha256"
declare -A WANT=(
  [".env.example"]="d7fdc875ae98e4b0af261489ff020e922964d897ad3c965c641a95fb290753c9"
  ["algo_config.py"]="f8633b28a97183fcceac73aefb8fa95f24f0f034b45854ebda0e3463a7ce9b79"
  ["autotrading_config.json"]="6631e5b2c9200e8f7317abd680e29bd0aa08ea93997b83caefebd95c94455213"
  ["azabot.service"]="a274e24530a6c6967d3aa0e1182d8ba3d4f493b3fabdbbe887f9ea0ecb625f1e"
  ["azazel_api.py"]="317690eecec1291fedb9938da5e8c9a3829cbfb75c2da2145df851cb2b49cb39"
  ["azazel_config.json"]="efa47168b9c20d0e564dba55bce495675bc1b878fc62be96ab757b3d94290a13"
  ["azazel_config_loader.py"]="a1fb911553c3a6b3766e86b9b3b419c227bd5fbacbe4ad74924773710e2a206a"
  ["bot.py"]="001ee4e0d9cd52bd159000f23693c34ea0c0329ea76dd907b4e3d9c6488ace50"
  ["config.json"]="eaa497614f0ddc67ecac234f7d2a9c19f2c1e6b10a28568677d25bd2c050f73b"
  ["continuation_engine.py"]="278e59035c50427a326bb4c51cabc05c421f96d56488aa311820ac10aee0895f"
  ["continuation_engine_v2.py"]="b15fb414918cd97c56648af1227cc9e34e0f266159314f607ce3da131e61e03a"
  ["install.sh"]="9e458e8d45c404a0a259465532456ae505179818e6ab5bb9b109801119eaed26"
  ["scalping_framework_v2.py"]="6af88e1c52eb0efb808e5b0785be5563f060bae5ea5519a3e00a5bae520cedbb"
  ["scalping_strategies.py"]="9a2ab547eb30706c02558154639ec4257bd256bead2a872df29186d34cd5a43a"
  ["steps.py"]="27ebc820e407b6352917e9ec8861658369e1a72fe2200923089a17956ff1d446"
  ["test_cont_v2.py"]="160e9fd59b19e774b521e1ad60f61f9ff30398b5cb07756e769de412db60c53a"
  ["test_cont_v3.py"]="103cb15a9d21edb92a3ec4e4a1e14e2893ac25a69c8b57c0fdf60914caa39062"
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

echo "[6/11] sintaksis i testy"
cd "${DIR}"
python3 -c "import ast; ast.parse(open('bot.py',encoding='utf-8').read()); ast.parse(open('continuation_engine.py',encoding='utf-8').read())" \
  && echo "    sintaksis: OK" || { echo "OSHIBKA: sintaksis sloman"; exit 1; }
bash -n "${DIR}/install.sh" && echo "    install.sh: OK" || { echo "OSHIBKA: install.sh sloman"; exit 1; }
python3 "${DIR}/test_cont_v3.py" > /tmp/_t3.log 2>&1
RC3=$?; echo "    test_cont_v3 rc=${RC3}"; tail -2 /tmp/_t3.log | sed "s/^/      /"
[ ${RC3} -ne 0 ] && { echo "OSHIBKA: testy v3 ne proshli"; exit 1; }
python3 "${DIR}/test_cont_v2.py" > /tmp/_t2.log 2>&1
RC2=$?; echo "    test_cont_v2 rc=${RC2}"; tail -2 /tmp/_t2.log | sed "s/^/      /"

echo "[7/11] .env"
if [ -f "${DIR}/.env" ]; then
  echo "    .env uzhe est - ne trogayu"
else
  cp "${DIR}/.env.example" "${DIR}/.env" && chmod 600 "${DIR}/.env" && echo "    sozdan .env iz .env.example (tokeny pustye - zapolni!)"
fi

echo "[8/11] servis bota"
cp -f "${DIR}/azabot.service" /etc/systemd/system/azabot.service 2>/dev/null && echo "    unit: ok" || echo "    VNIHMANIE: net prav na /etc/systemd/system"
systemctl daemon-reload && echo "    daemon-reload: ok"
systemctl enable azabot.service >/dev/null 2>&1 && echo "    enable: ok"
systemctl restart azabot.service
sleep 7
systemctl is-active azabot.service | sed "s/^/    status: /"

echo "[9/11] server API dlya metrik"
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

echo "[10/11] publichnyy dostup k API (cloudflared tunnel)"
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

echo "[11/11] proverka"
journalctl -u azabot.service -n 15 --no-pager 2>/dev/null | sed "s/^/    /"
[ -f /var/log/azabot.log ] && tail -15 /var/log/azabot.log | sed "s/^/    /"
grep -q "AZABOT_TOKEN=." "${DIR}/.env" && echo "    AZABOT_TOKEN: zapolnen" || echo "    VNIHMANIE: AZABOT_TOKEN pust"
grep -q "AIRTABLE_TOKEN=." "${DIR}/.env" && echo "    AIRTABLE_TOKEN: zapolnen" || echo "    VNIHMANIE: AIRTABLE_TOKEN pust"

if [ -n "${TUNNEL_URL}" ]; then echo "=== DEPLOY OK ${SHA_PIN} | API: ${TUNNEL_URL} ==="; else echo "=== DEPLOY OK ${SHA_PIN} | API lokalno: 127.0.0.1:8787 ==="; fi
