#!/usr/bin/env bash
# ============================================================
# Azazel - DEPLOY. Vstaetsya v serialnuyu konsol Timeweb.
# Rabotaet BEZ SSH. Kommit: 7be50d8f42080783c36f58b989816606b227f353
# ============================================================
set -uo pipefail

SHA="7be50d8f42080783c36f58b989816606b227f353"
BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${SHA}"
DIR="/opt/azabot"
BACKUP="${DIR}/backup_$(date +%Y%m%d_%H%M%S)"

echo "=== Azazel DEPLOY | ${SHA} ==="

echo "[1/7] dostup k GitHub s servera"
if ! curl -fsSL --max-time 25 "${BASE}/bot.py" -o /tmp/_probe.py; then
  echo "ОШИБКА: server ne vidit raw.githubusercontent.com"
  curl -sI --max-time 15 https://github.com | head -1
  exit 1
fi
echo "    ok"

echo "[2/7] bekap"
mkdir -p "${BACKUP}"
for f in ${LIST}; do
  [ -f "${DIR}/${f}" ] && cp -p "${DIR}/${f}" "${BACKUP}/" && echo "    bekap: ${f}"
done
echo "    bekap: ${BACKUP}"

echo "[3/7] zagruzka po SHA"
for f in ${LIST}; do
  curl -fsSL --max-time 30 "${BASE}/${f}" -o "${DIR}/${f}" || { echo "ОШИБКА: ne skachalsya ${f}"; exit 1; }
  echo "    ${f} (${DIR}/${f} $(stat -c%s "${DIR}/${f}") Б)"
done

echo "[4/7] proverka sha256"
declare -A WANT=(
  ["continuation_engine.py"]="f19c9b163ffd7f3fb56b8fd826c871328e1c4affd536f252f5f6e7b69110e794"
  ["continuation_engine_v2.py"]="b15fb414918cd97c56648af1227cc9e34e0f266159314f607ce3da131e61e03a"
  ["test_cont_v3.py"]="4aa2501bc6520c1f0d6e489aa7899bee7096861be034c0f496a5520f5a1d65f0"
  ["bot.py"]="b0da3c71954337430b8ee5287d8011a71554388ad5a30d0c2a616ce2050ceb85"
  ["algo_config.py"]="f8633b28a97183fcceac73aefb8fa95f24f0f034b45854ebda0e3463a7ce9b79"
  ["azazel_config.json"]="e75836e86d6f1755c3c0b6506f58f1feb1373a2a0874051b336ac32835dc3e42"
  ["config.json"]="996496977f7e4a2b7720c66b232a04bbce89499914d6658ffc73c86025968591"
  ["azabot.service"]="a274e24530a6c6967d3aa0e1182d8ba3d4f493b3fabdbbe887f9ea0ecb625f1e"
  ["install.sh"]="9e458e8d45c404a0a259465532456ae505179818e6ab5bb9b109801119eaed26"
  [".env.example"]="d7fdc875ae98e4b0af261489ff020e922964d897ad3c965c641a95fb290753c9"
)
FAIL=0
for f in "${!WANT[@]}"; do
  GOT=$(sha256sum "${DIR}/${f}" | cut -d" " -f1)
  if [ "${GOT}" != "${WANT[$f]}" ]; then
    echo "    ОШИБКА sha256: ${f}"; FAIL=1
  else
    echo "    ok: ${f}"
  fi
done
[ $FAIL -ne 0 ] && { echo "ОШИБКА: checksumy ne sovpali - DEPLOY PRERVAN"; exit 1; }

echo "[5/7] sintaksis i testy"
cd "${DIR}"
python3 -c "import ast; ast.parse(open('bot.py',encoding='utf-8').read()); ast.parse(open('continuation_engine.py',encoding='utf-8').read())" \
  && echo "    sintaksis: OK" || { echo "ОШИБКА: sintaksis sloman"; exit 1; }
bash -n "${DIR}/install.sh" && echo "    install.sh: OK" || { echo "ОШИБКА: install.sh sloman"; exit 1; }
python3 "${DIR}/test_cont_v3.py" > /tmp/_t3.log 2>&1
RC3=$?; echo "    test_cont_v3 rc=${RC3}"; tail -2 /tmp/_t3.log | sed "s/^/      /"
[ ${RC3} -ne 0 ] && { echo "ОШИБКА: testy v3 ne proshli"; exit 1; }
python3 "${DIR}/test_cont_v2.py" > /tmp/_t2.log 2>&1
RC2=$?; echo "    test_cont_v2 rc=${RC2}"; tail -2 /tmp/_t2.log | sed "s/^/      /"

echo "[6/7] .env"
if [ -f "${DIR}/.env" ]; then
  echo "    .env uzhe est - ne trogayu"
else
  cp "${DIR}/.env.example" "${DIR}/.env" && chmod 600 "${DIR}/.env" && echo "    sozdan .env iz .env.example (tokeny pustye - zapolni!)"
fi

echo "[7/7] gotovo"
echo "=== DEPLOY OK ${SHA} ==="
echo "TEPER: vypolni ustanovku:"
echo "  curl -fsSL https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${SHA}/install.sh -o /tmp/i.sh && bash /tmp/i.sh"
