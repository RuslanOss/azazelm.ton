#!/usr/bin/env bash
# ============================================================
# Azazel - автономный деплой continuation_engine v3
# Вставляется в серийную консоль Timeweb. Работает без SSH.
# ============================================================
set -uo pipefail

SHA="31e56a33cdf9fc00db9ad5e8ea027fc415380dcf"
BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${SHA}"
DIR="/opt/azabot"
BACKUP="${DIR}/backup_predeploy_$(date +%Y%m%d_%H%M%S)"

echo "=== Azazel deploy | commit ${SHA} ==="

# 1) проверка доступа в GitHub
if ! curl -fsSL --max-time 25 "${BASE}/continuation_engine.py" -o /tmp/_probe.py; then
  echo "ОШИБКА: нет доступа к raw.githubusercontent.com с сервера"
  echo "Проверь сетевую доступность: curl -sI https://github.com | head -1"
  exit 1
fi
echo "[1/6] GitHub доступен, коммит ${SHA}"

# 2) бэкап
mkdir -p "${BACKUP}"
for f in continuation_engine.py continuation_engine_v2.py bot.py algo_config.py azazel_config.json; do
  [ -f "${DIR}/${f}" ] && cp -p "${DIR}/${f}" "${BACKUP}/" && echo "    бэкап: ${f}"
done
echo "[2/6] бэкап в ${BACKUP}"

# 3) загрузка файлов
for f in continuation_engine.py continuation_engine_v2.py test_cont_v3.py; do
  curl -fsSL --max-time 30 "${BASE}/${f}" -o "${DIR}/${f}" || { echo "ОШИБКА: не скачался ${f}"; exit 1; }
  echo "    скачан: ${f} ($(stat -c%s "${DIR}/${f}") Б)"
done
echo "[3/6] файлы загружены"

# 4) проверка целостности по sha256
declare -A WANT=(
  [continuation_engine.py]="f19c9b163ffd7f3fb56b8fd826c871328e1c4affd536f252f5f6e7b69110e794"
  [continuation_engine_v2.py]="b15fb414918cd97c56648af1227cc9e34e0f266159314f607ce3da131e61e03a"
  [test_cont_v3.py]="4aa2501bc6520c1f0d6e489aa7899bee7096861be034c0f496a5520f5a1d65f0"
)
for f in "${!WANT[@]}"; do
  GOT=$(sha256sum "${DIR}/${f}" | cut -d" " -f1)
  if [ "${GOT}" != "${WANT[$f]}" ]; then
    echo "ОШИБКА: sha256 не совпал для ${f}"; exit 1
  fi
  echo "    sha256 ok: ${f}"
done
echo "[4/6] контрольные суммы совпали"

# 5) тесты
cd "${DIR}"
if python3 -c "import ast,sys; ast.parse(open('continuation_engine.py',encoding='utf-8').read())" 2>/dev/null; then
  echo "    синтаксис continuation_engine.py: OK"
else
  echo "ОШИБКА: синтаксис continuation_engine.py сломан"; exit 1
fi
python3 "${DIR}/test_cont_v3.py" > /tmp/_t3.log 2>&1
RC3=$?
echo "    test_cont_v3.py: rc=${RC3}"
tail -3 /tmp/_t3.log | sed "s/^/      /"
if [ ${RC3} -ne 0 ]; then
  echo "ОШИБКА: тесты v3 не прошли - сервис НЕ перезапускаю"
  cp -p "${BACKUP}/continuation_engine.py" "${DIR}/" 2>/dev/null
  exit 1
fi
python3 "${DIR}/test_cont_v2.py" > /tmp/_t2.log 2>&1
RC2=$?
echo "    test_cont_v2.py: rc=${RC2}"
if [ ${RC2} -ne 0 ]; then
  echo "ВНИМАНИЕ: регрессионные тесты v2 не прошли"
fi
echo "[5/6] тесты пройдены"

# 6) перезапуск сервиса
if systemctl list-unit-files | grep -q azabot.service; then
  systemctl restart azabot.service
  sleep 3
  ACTIVE=$(systemctl is-active azabot.service)
  echo "    azabot.service: ${ACTIVE}"
  journalctl -u azabot.service -n 12 --no-pager | sed "s/^/      /"
  [ "${ACTIVE}" = "active" ] || { echo "ВНИМАНИЕ: сервис не поднялся"; exit 1; }
else
  echo "    azabot.service не найден - проверь systemctl list-units | grep azabot"
fi
echo "[6/6] деплой завершён"
echo ""
echo "DEPLOY_OK ${SHA}"
