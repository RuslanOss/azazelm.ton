#!/usr/bin/env bash
# ============================================================
# Azazel - ustanovka servisa. Vstaetsya v serialnuyu konsol Timeweb.
# Rabinаet BEZ SSH: stavit systemd-unit, sozdaet .env, zapuskaet.
# ============================================================
set -uo pipefail

DIR="/opt/azabot"
echo "=== Azazel install | $(date) ==="

echo "[1/6] katalog"
mkdir -p "$DIR"
cd "$DIR" || { echo "ОШИБКА: нет доступа к $DIR"; exit 1; }

echo "[2/6] fayly"
for f in bot.py continuation_engine.py continuation_engine_v2.py algo_config.py azazel_config.json config.json; do
  [ -f "$DIR/$f" ] || { echo "ОШИБКА: нет $DIR/$f - snachala progon deploy_azazel.sh"; exit 1; }
  echo "    ok: $f"
done

echo "[3/6] .env"
if [ -f "$DIR/.env" ]; then
  echo "    .env uzhe est - ne trogayu"
  grep -q "AZABOT_TOKEN=." "$DIR/.env" && echo "    AZABOT_TOKEN: zapolnen" || echo "    ВНИМАНИЕ: AZABOT_TOKEN pust"
  grep -q "AIRTABLE_TOKEN=." "$DIR/.env" && echo "    AIRTABLE_TOKEN: zapolnen" || echo "    ВНИМАНИЕ: AIRTABLE_TOKEN pust"
else
  cp "$DIR/.env.example" "$DIR/.env" 2>/dev/null && echo "    sozdan iz .env.example" || echo "    ОШИБКА: net .env.example"
  chmod 600 "$DIR/.env"
  echo "    ВПИШИ TOKENY V /opt/azabot/.env, potom zapusti servis"
fi

echo "[4/6] systemd-unit"
cp -f "$DIR/azabot.service" /etc/systemd/system/azabot.service 2>/dev/null \
  || { echo "    net prav na /etc/systemd/system - skopiruy ruchno"; exit 1; }
chmod 644 /etc/systemd/system/azabot.service
systemctl daemon-reload && echo "    daemon-reload: ok"
systemctl enable azabot.service >/dev/null 2>&1 && echo "    enable: ok"

echo "[5/6] zapusk"
systemctl restart azabot.service
sleep 6
systemctl is-active azabot.service | sed "s/^/    status: /"
echo "--- log ---"
journalctl -u azabot.service -n 20 --no-pager 2>/dev/null | sed "s/^/    /"
[ -f /var/log/azabot.log ] && tail -20 /var/log/azabot.log | sed "s/^/    /"

echo "[6/6] proverka tokenov"
if grep -q "AZABOT_TOKEN=." "$DIR/.env" && grep -q "AIRTABLE_TOKEN=." "$DIR/.env"; then
  echo "    tokeny zapolneny - bot dolzhen pisat v /var/log/azabot.log"
  echo "    prover: grep 'Bot zapushchen' /var/log/azabot.log"
else
  echo "    ОШИБКА: tokeny ne zapolneny"
  echo "    vypolni: nano $DIR/.env  (AZABOT_TOKEN, AIRTABLE_TOKEN, AIRTABLE_BASE_ID)"
fi

echo "=== INSTALL DONE ==="
