#!/usr/bin/env bash
# ============================================================
# Azazel - DEPLOY. Vstaetsya v serialnuyu konsol Timeweb.
# Rabotaet BEZ SSH. Fajly berutsya s fiksirovannogo kommitta, skript lezhit v main.
# ============================================================
set -uo pipefail

SHA="main"
BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/main"
DIR="/opt/azabot"
BACKUP="${DIR}/backup_$(date +%Y%m%d_%H%M%S)"
LIST="bot.py algo_config.py steps.py azazel_config.json azazel_config_loader.py continuation_engine.py continuation_engine_v2.py config.json autotrading_config.json azabot.service install.sh .env.example test_cont_v2.py test_cont_v3.py scalping_framework_v2.py scalping_strategies.py"

echo "=== Azazel DEPLOY | main (fajly iz main, khеshi zafiksirovany v etom skripte) ==="

echo "[1/8] dostup k GitHub s servera"
if ! curl -fsSL --max-time 25 "${BASE}/bot.py" -o /tmp/_probe.py; then
  echo "OSHIBKA: server ne vidit raw.githubusercontent.com"
  curl -sI --max-time 15 https://github.com | head -1
  exit 1
fi
echo "    ok"

echo "[2/8] bekap"
mkdir -p "${BACKUP}"
for f in ${LIST}; do
  [ -f "${DIR}/${f}" ] && cp -p "${DIR}/${f}" "${BACKUP}/" && echo "    bekap: ${f}"
done
echo "    bekap: ${BACKUP}"

echo "[3/8] zagruzka po SHA"
for f in ${LIST}; do
  curl -fsSL --max-time 30 "${BASE}/${f}" -o "${DIR}/${f}" || { echo "OSHIBKA: ne skachalsya ${f}"; exit 1; }
  echo "    ${f} (${DIR}/${f} $(stat -c%s "${DIR}/${f}") B)"
done

echo "[4/8] proverka sha256"
declare -A WANT=(
  ["bot.py"]="778150bb26683674497e58250c7b39966bcf9e59b665f229f467237f950f9709"
  ["algo_config.py"]="f8633b28a97183fcceac73aefb8fa95f24f0f034b45854ebda0e3463a7ce9b79"
  ["steps.py"]="27ebc820e407b6352917e9ec8861658369e1a72fe2200923089a17956ff1d446"
  ["azazel_config.json"]="e75836e86d6f1755c3c0b6506f58f1feb1373a2a0874051b336ac32835dc3e42"
  ["azazel_config_loader.py"]="fbfe35648766756d1df7fe4afb9f95c352056562fda929a25630c881201a3c20"
  ["continuation_engine.py"]="f19c9b163ffd7f3fb56b8fd826c871328e1c4affd536f252f5f6e7b69110e794"
  ["continuation_engine_v2.py"]="b15fb414918cd97c56648af1227cc9e34e0f266159314f607ce3da131e61e03a"
  ["config.json"]="996496977f7e4a2b7720c66b232a04bbce89499914d6658ffc73c86025968591"
  ["autotrading_config.json"]="6631e5b2c9200e8f7317abd680e29bd0aa08ea93997b83caefebd95c94455213"
  ["azabot.service"]="370bee442740fe4340dfee1b831ae8cf5d3e946319cf3bd186536f8b958dbcfe"
  ["install.sh"]="9e458e8d45c404a0a259465532456ae505179818e6ab5bb9b109801119eaed26"
  [".env.example"]="d7fdc875ae98e4b0af261489ff020e922964d897ad3c965c641a95fb290753c9"
  ["test_cont_v2.py"]="a8516b046e9ec071f1d1b34c0c4955372e6f2ce839b6c65131c9952474467364"
  ["test_cont_v3.py"]="4aa2501bc6520c1f0d6e489aa7899bee7096861be034c0f496a5520f5a1d65f0"
  ["scalping_framework_v2.py"]="6af88e1c52eb0efb808e5b0785be5563f060bae5ea5519a3e00a5bae520cedbb"
  ["scalping_strategies.py"]="9a2ab547eb30706c02558154639ec4257bd256bead2a872df29186d34cd5a43a"
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

echo "[5/8] sintaksis i testy"
cd "${DIR}"
python3 -c "import ast; ast.parse(open('bot.py',encoding='utf-8').read()); ast.parse(open('continuation_engine.py',encoding='utf-8').read())" \
  && echo "    sintaksis: OK" || { echo "OSHIBKA: sintaksis sloman"; exit 1; }
bash -n "${DIR}/install.sh" && echo "    install.sh: OK" || { echo "OSHIBKA: install.sh sloman"; exit 1; }
python3 "${DIR}/test_cont_v3.py" > /tmp/_t3.log 2>&1
RC3=$?; echo "    test_cont_v3 rc=${RC3}"; tail -2 /tmp/_t3.log | sed "s/^/      /"
[ ${RC3} -ne 0 ] && { echo "OSHIBKA: testy v3 ne proshli"; exit 1; }
python3 "${DIR}/test_cont_v2.py" > /tmp/_t2.log 2>&1
RC2=$?; echo "    test_cont_v2 rc=${RC2}"; tail -2 /tmp/_t2.log | sed "s/^/      /"

echo "[6/8] .env"
if [ -f "${DIR}/.env" ]; then
  echo "    .env uzhe est - ne trogayu"
else
  cp "${DIR}/.env.example" "${DIR}/.env" && chmod 600 "${DIR}/.env" && echo "    sozdan .env iz .env.example (tokeny pustye - zapolni!)"
fi

echo "[7/8] servis"
cp -f "${DIR}/azabot.service" /etc/systemd/system/azabot.service 2>/dev/null && echo "    unit: ok" || echo "    VNIHMANIE: net prav na /etc/systemd/system"
systemctl daemon-reload && echo "    daemon-reload: ok"
systemctl enable azabot.service >/dev/null 2>&1 && echo "    enable: ok"
systemctl restart azabot.service
sleep 7
systemctl is-active azabot.service | sed "s/^/    status: /"

echo "[8/8] proverka"
journalctl -u azabot.service -n 15 --no-pager 2>/dev/null | sed "s/^/    /"
[ -f /var/log/azabot.log ] && tail -15 /var/log/azabot.log | sed "s/^/    /"
grep -q "AZABOT_TOKEN=." "${DIR}/.env" && echo "    AZABOT_TOKEN: zapolnen" || echo "    VNIHMANIE: AZABOT_TOKEN pust"
grep -q "AIRTABLE_TOKEN=." "${DIR}/.env" && echo "    AIRTABLE_TOKEN: zapolnen" || echo "    VNIHMANIE: AIRTABLE_TOKEN pust"

echo "=== DEPLOY OK ${SHA} ==="
