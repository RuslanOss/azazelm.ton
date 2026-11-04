#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kliент Timeweb Cloud MCP: server-side dlya azabot.

Ispolzuet API-key kak Bearer v MCP-endpoint /api/v1/mcp.
Vse zaprosy idut cherez streamable HTTP (Accept: application/json, text/event-stream).
"""
import json
import os
import urllib.request

MCP_URL = os.environ.get("TIMEWEB_MCP_URL", "https://api.timeweb.cloud/api/v1/mcp").strip()
API_KEY = os.environ.get("TIMEWEB_API_KEY", "").strip()
TIMEOUT = int(os.environ.get("TIMEWEB_TIMEOUT", "60"))


def _parse(text):
    """Otpravka otveta MCP: soderzhit data: stroki (SSE) ili chistyy JSON."""
    chunks = []
    for line in text.splitlines():
        if line.startswith("data:"):
            chunks.append(line[5:].lstrip())
    if chunks:
        text = "\n".join(chunks)
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text[:500]}


def _rpc(method, params=None, _id=1):
    if not API_KEY:
        raise RuntimeError("TIMEWEB_API_KEY ne zadan")
    body = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + API_KEY,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return _parse(r.read().decode("utf-8", errors="replace"))


def _init():
    return _rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "azabot", "version": "1.0"},
    })


def list_tools():
    """Spisok dostupnyh instrumentov."""
    _init()
    res = _rpc("tools/list", {})
    out = []
    for t in (res.get("result") or {}).get("tools") or []:
        out.append({"name": t.get("name"), "description": (t.get("description") or "")[:200]})
    return out


def call(tool, args=None):
    """Vyzov instrumenta MCP -> razobrannyy result."""
    _init()
    res = _rpc("tools/call", {"name": tool, "arguments": args or {}})
    if "error" in res and res.get("error"):
        return {"ok": False, "error": res["error"]}
    try:
        payload = json.loads(res["result"]["content"][0]["text"])
    except Exception:
        payload = res.get("result")
    return {"ok": True, "data": payload}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for t in list_tools():
            print("-", t["name"], "|", t["description"])
    elif len(sys.argv) > 2:
        try:
            args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        except Exception:
            args = {}
        print(json.dumps(call(sys.argv[1], args), ensure_ascii=False, indent=2)[:4000])
    else:
        print(json.dumps(list_tools(), ensure_ascii=False, indent=2)[:4000])
