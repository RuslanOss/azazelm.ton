#!/usr/bin/env bash
# ============================================================
# Azazel - WEB-ASSETS DEPLOY (Mini App icons).
# Vstaetsya v serialnuyu konsol Timeweb. Rabotaet BEZ SSH.
# Menyaet tolko web/app/assets/*.png + web/app/index.html.
# Ikonka: nochnoe zvezdnoe nebo + belyj siluet (25adbf7b).
# ============================================================
set -uo pipefail

echo "=== Azazel WEB-ASSETS DEPLOY ==="
WEB_SHA="1261867c505f715bee1a179e20cc249e2a823170"
WEB_BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${WEB_SHA}"
WEB_FILES="web/app/assets/devil-256.png web/app/assets/devil-64.png web/app/index.html"
declare -A WEB_WANT=(
  ["devil-256.png"]="e5db284da3f2577da339381d7434d1b1956a2526196057751a492b8832c74ce6"
  ["devil-64.png"]="53621fe3b65d925458a63faff3004c3c9f59f1fd67a24e3507141afbed5ba7de"
  ["index.html"]="29733bbe26b6aaf88f67f78c1ea5e9022cb7c919daf8bcfc2da80fc8591b68a2"
)

# 4.1 nayti katalog s assetami
WEBROOT="${WEBROOT_OVERRIDE:-}"
if [ -z "${WEBROOT}" ]; then
  for c in $(grep -rhoP 'root\s+\K[^;]+' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | sort -u); do
    if [ -f "${c}/app/assets/devil-256.png" ]; then WEBROOT="${c}/app"; break; fi
    if [ -f "${c}/assets/devil-256.png" ]; then WEBROOT="${c}"; break; fi
  done
fi
if [ -z "${WEBROOT}" ]; then
  FOUND=$(find /var/www /opt /srv /home -name 'devil-256.png' 2>/dev/null | head -1)
  if [ -n "${FOUND}" ]; then WEBROOT="$(dirname "$(dirname "${FOUND}")")"; fi
fi
if [ -z "${WEBROOT}" ] || [ ! -d "${WEBROOT}/assets" ]; then
  echo "    OSHIBKA: ne nashel katalog s assets/ - ukazhi WEBROOT vruchnuyu"
  WEBROOT=""
else
  echo "    WEBROOT: ${WEBROOT}"
fi

if [ -n "${WEBROOT}" ]; then
  # 4.2 bekap starogo
  WB="${WEBROOT}/backup_$(date +%Y%m%d_%H%M%S)"
  mkdir -p "${WB}"
  cp -p "${WEBROOT}/assets/"*.png "${WB}/" 2>/dev/null
  cp -p "${WEBROOT}/index.html" "${WB}/" 2>/dev/null
  echo "    bekap: ${WB}"

  # 4.3 zagruzka
  WEBFAIL=0
  for f in ${WEB_FILES}; do
    name=$(basename "${f}")
    dest="${WEBROOT}/assets/${name}"
    [ "${name}" = "index.html" ] && dest="${WEBROOT}/index.html"
    if curl -fsSL --max-time 40 "${WEB_BASE}/${f}" -o "${dest}.new"; then
      mv -f "${dest}.new" "${dest}"
      echo "    ${name} (${dest} $(stat -c%s "${dest}") B)"
    else
      echo "    OSHIBKA: ne skachalsya ${name}"; WEBFAIL=1
    fi
  done

  # 4.4 proverka sha256
  for name in "${!WEB_WANT[@]}"; do
    target="${WEBROOT}/assets/${name}"
    [ "${name}" = "index.html" ] && target="${WEBROOT}/index.html"
    GOT=$(sha256sum "${target}" 2>/dev/null | cut -d" " -f1)
    if [ "${GOT}" != "${WEB_WANT[$name]}" ]; then
      echo "    OSHIBKA sha256: ${name}"; WEBFAIL=1
    else
      echo "    ok: ${name}"
    fi
  done

  # 4.5 pochistit starye JPEG-ikonki (tolko .jpg v assets/)
  for old in "${WEBROOT}/assets/devil-256.jpg" "${WEBROOT}/assets/devil-64.jpg"; do
    if [ -f "${old}" ]; then
      rm -f "${old}" && echo "    udalen: ${old}"
    fi
  done

  # 4.6 otvergai nginx i proverka cherez lokalnyy host
  nginx -t >/dev/null 2>&1 && { systemctl reload nginx 2>/dev/null && echo "    nginx reload: ok"; } || echo "    VNIHMANIE: nginx reload ne udalsya"
  sleep 2
  LOC=""
  for PROBE in "http://127.0.0.1" "https://127.0.0.1" "https://azazelm.com"; do
    if curl -fsSk --max-time 15 -H "Host: azazelm.com" "${PROBE}/app/assets/devil-256.png" -o /tmp/_w.png 2>/dev/null; then
      LOC=$(sha256sum /tmp/_w.png | cut -d" " -f1)
      echo "    probe ${PROBE} -> ${LOC:0:12}"
      [ "${LOC}" = "${WEB_WANT[devil-256.png]}" ] && break
    fi
  done
  if [ "${LOC}" = "${WEB_WANT[devil-256.png]}" ]; then
    echo "    PROVERKA OK: server otdaet novuyu ikonku"
  else
    echo "    VNIHMANIE: lokalno server otdaet staruyu ikonku"
    echo "    fayly na diske obnovleny i s pravilnymi sha256 - prover otkrytiye v Telegram"
  fi
  [ ${WEBFAIL} -ne 0 ] && echo "    VNIHMANIE: web-assety s chastichnymi oshibkami"
fi

if [ "${ONLY_WEB:-0}" = "1" ]; then
  echo "=== WEB-ASSETS DONE ==="
  exit 0
fi

echo "=== WEB-ASSETS DONE ==="
