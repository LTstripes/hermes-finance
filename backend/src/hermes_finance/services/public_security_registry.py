"""Opt-in public MOEX metadata, never source/account/holding evidence.

The bounded process-local cache contains public metadata only. Preview/Apply
read it offline; only the explicit consent endpoint may populate it.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock

import httpx2

from hermes_finance.statement_import.mybroker import MyBrokerError, digest
from hermes_finance.statement_import.mybroker_identity import ISIN

BASE = "https://iss.moex.com/iss"
TTL = timedelta(hours=1)
_cache: dict[str, dict] = {}
_current: dict[str, str] = {}
_lock = RLock()


def _now():
    return datetime.now(timezone.utc)


def _rows(payload, block):
    table = payload[block]
    columns, rows = table["columns"], table["data"]
    if len(set(columns)) != len(columns) or len(rows) > 100:
        raise ValueError("registry_shape")
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _get(client, path, **params):
    response = client.get(BASE + path, params={"iss.meta": "off", **params})
    response.raise_for_status()
    if len(response.content) > 1024 * 1024:
        raise ValueError("registry_response_limit")
    return response.json()


def _discover(client, isin):
    matches = {}
    # Empty final page proves exhaustion. Truncation/any failed page is UNKNOWN.
    start = 0
    for _ in range(20):
        rows = _rows(_get(client, "/securities.json", q=isin, start=start, limit=100), "securities")
        for row in rows:
            if row.get("isin") == isin:
                secid = row.get("secid")
                if not isinstance(secid, str) or not secid.isascii() or not secid.isalnum():
                    raise ValueError("registry_secid_invalid")
                if secid in matches and matches[secid] != row:
                    raise ValueError("registry_duplicate_conflict")
                matches[secid] = row
        if not rows:
            return list(matches.values())
        start += len(rows)
        if start > 1000:
            break
    raise ValueError("registry_search_truncated")


def _lookup(client, isin):
    candidates = []
    for row in _discover(client, isin):
        secid = row["secid"]
        url = BASE + f"/securities/{secid}.json"
        payload = _get(client, f"/securities/{secid}.json")
        fields = _rows(payload, "description")
        if len({f["name"] for f in fields}) != len(fields):
            raise ValueError("registry_description_conflict")
        description = {f["name"]: f["value"] for f in fields}
        reasons = []
        if description.get("ISIN") != isin or description.get("SECID") != secid:
            reasons.append("official_exact_identity_conflict")
        kind = {"stock_bonds": "bond", "stock_shares": "stock"}.get(description.get("GROUP"))
        supported_types = {
            "bond": {
                "corporate_bond",
                "exchange_bond",
                "ofz_bond",
                "municipal_bond",
                "subfederal_bond",
                "euro_bond",
            },
            "stock": {"common_share", "preferred_share"},
        }
        if description.get("TYPE") not in supported_types.get(kind, set()):
            reasons.append("official_type_unsupported")
        if (
            not kind
            or row.get("group") != description.get("GROUP")
            or row.get("type") != description.get("TYPE")
        ):
            reasons.append("official_type_unproven")
        if row.get("is_traded") != 1:
            reasons.append("official_current_status_unproven")
        # FACEUNIT proves bond denomination. Settlement CURRENCYID never does.
        currency = description.get("FACEUNIT") if kind == "bond" else None
        # Exact official nominal-code alias; retain raw FACEUNIT in description.
        if currency == "SUR":
            currency = "RUB"
        if currency not in {"RUB", "USD", "EUR", "CNY", "GBP", "CHF", "JPY", "HKD"}:
            currency = None
            reasons.append("instrument_currency_unproven")
        candidates.append(
            {
                "isin": isin,
                "secid": secid,
                "name": description.get("NAME"),
                "instrument_type": kind,
                "currency": currency,
                "currency_field": "FACEUNIT" if currency else None,
                "url": url,
                "reasons": reasons,
                "description": description,
                "search_row": row,
            }
        )
    return candidates


def lookup_public(isins: list[str], *, consent: bool, client=None):
    if consent is not True:
        raise MyBrokerError("public_lookup_consent_required")
    if not 1 <= len(isins) <= 32 or any(not ISIN.fullmatch(i) for i in isins):
        raise MyBrokerError("public_lookup_isins_invalid")
    results = []
    own = client is None
    if own:
        client = httpx2.Client(timeout=5, follow_redirects=False, trust_env=False)
    try:
        for isin in sorted(set(isins)):
            try:
                candidates = _lookup(client, isin)
                reasons = [] if len(candidates) == 1 else ["official_missing_or_ambiguous"]
            except (ValueError, KeyError, TypeError, httpx2.HTTPError):
                candidates, reasons = [], ["official_lookup_unavailable"]
            material = {
                "isin": isin,
                "candidates": candidates,
                "reasons": reasons,
                "retrieved_at": _now().isoformat(),
                "expires_at": (_now() + TTL).isoformat(),
            }
            material["proof_id"] = digest(material)
            with _lock:
                # Bounded public cache; eviction makes old review stale, never trusted.
                if len(_cache) >= 512:
                    evicted_id = next(iter(_cache))
                    evicted = _cache.pop(evicted_id)
                    if _current.get(evicted["isin"]) == evicted_id:
                        _current.pop(evicted["isin"])
                _cache[material["proof_id"]] = material
                _current[isin] = material["proof_id"]
            results.append(deepcopy(material))
    finally:
        if own:
            client.close()
    return results


def denomination_proof(proof_id, isin, kind):
    with _lock:
        item = deepcopy(_cache.get(proof_id)) if _current.get(isin) == proof_id else None
    if not item or item["isin"] != isin or datetime.fromisoformat(item["expires_at"]) <= _now():
        return None
    if item["reasons"] or len(item["candidates"]) != 1:
        return None
    candidate = item["candidates"][0]
    if candidate["reasons"] or candidate["instrument_type"] != kind:
        return None
    return {**candidate, "retrieved_at": item["retrieved_at"], "proof_id": proof_id}
