#!/usr/bin/env bash
# ============================================================
# Azazel - автономный деплой. Вставляется в серийную консоль Timeweb.
# Работает БЕЗ SSH: качает файлы по SHA, проверяет sha256, гоняет тесты.
# Коммит: 6f436892241571e2dd41b59fc129ed82e4a25d60
# ============================================================
set -uo pipefail

SHA="6f436892241571e2dd41b59fc129ed82e4a25d60"
BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${SHA}"
DIR="/opt/azabot"
BACKUP="${DIR}/backup_$(date +%Y%m%d_%H%M%S)"

echo "=== Azazel deploy | commit ${SHA} ==="

echo "[1/7] проверка доступа к GitHub с сервера"
if ! curl -fsSL --max-time 25 "${BASE}/bot.py" -o /tmp/_probe.py; then
  echo "ОШИБКА: сервер не видит raw.githubusercontent.com"
  curl -sI --max-time 15 https://github.com | head -1
  exit 1
fi
echo "    ок"

echo "[2/7] бэкап текущих файлов"
mkdir -p "${BACKUP}"
for f in continuation_engine.py continuation_engine_v2.py test_cont_v3.py bot.py algo_config.py azazel_config.json config.json; do
  [ -f "${DIR}/${f}" ] && cp -p "${DIR}/${f}" "${BACKUP}/" && echo "    бэкап: ${f}"
done
echo "    бэкап: ${BACKUP}"

echo "[3/7] загрузка файлов по SHA"
for f in continuation_engine.py continuation_engine_v2.py test_cont_v3.py bot.py algo_config.py azazel_config.json config.json; do
  curl -fsSL --max-time 30 "${BASE}/${f}" -o "${DIR}/${f}" || { echo "ОШИБКА: не скачался ${f}"; exit 1; }
  echo "    ${f} (${DIR}/${f} $(stat -c%s "${DIR}/${f}") Б)"
done

echo "[4/7] проверка sha256"
declare -A WANT=(
  ["continuation_engine.py"]="f19c9b163ffd7f3fb56b8fd826c871328e1c4affd536f252f5f6e7b69110e794"
  ["continuation_engine_v2.py"]="b15fb414918cd97c56648af1227cc9e34e0f266159314f607ce3da131e61e03a"
  ["test_cont_v3.py"]="4aa2501bc6520c1f0d6e489aa7899bee7096861be034c0f496a5520f5a1d65f0"
  ["bot.py"]="5ce072724a2a36b38db3c5d500dc6cf1878554e288b7727331b46c154bc3dd44"
  ["algo_config.py"]="f8633b28a97183fcceac73aefb8fa95f24f0f034b45854ebda0e3463a7ce9b79"
  ["azazel_config.json"]="e75836e86d6f1755c3c0b6506f58f1feb1373a2a0874051b336ac32835dc3e42"
  ["config.json"]="996496977f7e4a2b7720c66b232a04bbce89499914d6658ffc73c86025968591"
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
[ $FAIL -ne 0 ] && { echo "ОШИБКА: контрольные суммы не совпали - деплой прерван"; exit 1; }

echo "[5/7] синтаксис и тесты"
cd "${DIR}"
python3 -c "import ast; ast.parse(open('bot.py',encoding='utf-8').read()); ast.parse(open('continuation_engine.py',encoding='utf-8').read())" \
  && echo "    синтаксис: OK" || { echo "ОШИБКА: синтаксис сломан"; exit 1; }
python3 "${DIR}/test_cont_v3.py" > /tmp/_t3.log 2>&1
RC3=$?; echo "    test_cont_v3 rc=${RC3}"; tail -2 /tmp/_t3.log | sed "s/^/      /"
[ ${RC3} -ne 0 ] && { echo "ОШИБКА: тесты v3 не прошли, сервис НЕ перезапускаю"; exit 1; }
python3 "${DIR}/test_cont_v2.py" > /tmp/_t2.log 2>&1
RC2=$?; echo "    test_cont_v2 rc=${RC2}"; tail -2 /tmp/_t2.log | sed "s/^/      /"

echo "[6/7] перезапуск сервиса"
if systemctl list-unit-files 2>/dev/null | grep -q azabot; then
  systemctl restart azabot.service && echo "    azabot.service перезапущен"
  sleep 3
  systemctl is-active azabot.service | sed "s/^/    status: /"
else
  echo "    azabot.service не найден - только файлы обновлены"
fi

echo "[7/7] готово"
echo "=== DEPLOY OK ${SHA} ==="
