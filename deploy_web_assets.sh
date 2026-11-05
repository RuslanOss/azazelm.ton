#!/usr/bin/env bash
# ============================================================
# Azazel - WEB-ASSETY DEPLOY (tolko ikonka Mini App).
# Vstaetsya v serialnuyu konsol Timeweb. Rabotaet BEZ SSH.
# Menyaet tolto web/app/assets/*.jpg - nikakogo pitona ne trogaet.
# ============================================================
set -uo pipefail

echo "=== Azazel WEB-ASSETY DEPLOY ==="
WEB_SHA="98c695dc218909856ef5688467d90035fa118bc5"
WEB_BASE="https://raw.githubusercontent.com/RuslanOss/azazelm.ton/${WEB_SHA}"
WEB_FILES="web/app/assets/devil-256.jpg web/app/assets/devil-64.jpg web/app/index.html"
declare -A WEB_WANT=(
  ["devil-256.jpg"]="9c232574d3cdbdd0c10f0e0e77b7be9c21f0cbc54f47ccadba28dfc0091e7cc2"
  ["devil-64.jpg"]="80eb9a9bd42efead9269def7089803ef917e7374d1792d5d6e1761d42e603bed"
  ["index.html"]="282ce7655a87e886b48a7a48ea9f16e6a2afc2a10fbaa682bd1c591f1649f712"
)

# 4.1 nayti katalog, v kotorm lezhit staryy ikonka
WEBROOT="${WEBROOT_OVERRIDE:-}"
if [ -z "${WEBROOT}" ]; then
  for c in $(grep -rhoP 'root\s+\K[^;]+' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | sort -u); do
    if [ -f "${c}/app/assets/devil-256.jpg" ]; then WEBROOT="${c}/app"; break; fi
    if [ -f "${c}/assets/devil-256.jpg" ]; then WEBROOT="${c}"; break; fi
  done
fi
if [ -z "${WEBROOT}" ]; then
  FOUND=$(find /var/www /opt /srv /home -name 'devil-256.jpg' 2>/dev/null | head -1)
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
  cp -p "${WEBROOT}/assets/"*.jpg "${WB}/" 2>/dev/null
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
  # 4.5 otvergai nginx i proverka cherez lokalnyy host
  nginx -t >/dev/null 2>&1 && { systemctl reload nginx 2>/dev/null && echo "    nginx reload: ok"; } || echo "    VNIHMANIE: nginx reload ne udalsya"
  sleep 2
  LOC=""
  for PROBE in "http://127.0.0.1" "https://127.0.0.1" "https://azazelm.com"; do
    if curl -fsSk --max-time 15 -H "Host: azazelm.com" "${PROBE}/app/assets/devil-256.jpg" -o /tmp/_w.jpg 2>/dev/null; then
      LOC=$(sha256sum /tmp/_w.jpg | cut -d" " -f1)
      echo "    probe ${PROBE} -> ${LOC:0:12}"
      [ "${LOC}" = "${WEB_WANT[devil-256.jpg]}" ] && break
    fi
  done
  if [ "${LOC}" = "${WEB_WANT[devil-256.jpg]}" ]; then
    echo "    PROVERKA OK: server otdaet novuyu ikonku"
  else
    echo "    VNIHMANIE: lokalno server otdaet staruyu ikonku"
    echo "    fayly na diske obnovleny i s pravilnymi sha256 - prover otkrytiye v Telegram"
  fi
  [ ${WEBFAIL} -ne 0 ] && echo "    VNIHMANIE: web-assety s chastichnymi oshibkami"
fi

if [ "${ONLY_WEB:-0}" = "1" ]; then
  echo "=== WEB-ASSETY DONE ==="
  exit 0
fi


echo "=== WEB-ASSETY DONE ==="
