"""Pure functions for the Kalshi-only tennis matchup filter.

A match is shown only when BOTH a live Kalshi match-winner listing and a
separately confirmed, future, PRE-match ESPN fixture can be matched.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from zoneinfo import ZoneInfo

ARIZONA = ZoneInfo("America/Phoenix")


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, OverflowError):
        return None


def key_name(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold().replace("’", "'")
    text = re.sub(r"[^a-z\s-]", " ", text).replace("-", " ")
    return " ".join(text.split())


def same_player(a: str, b: str) -> bool:
    a_words, b_words = key_name(a).split(), key_name(b).split()
    if not a_words or not b_words:
        return False
    if a_words == b_words:
        return True
    if a_words[-1] != b_words[-1]:
        return False
    # A one-token surname can be used when the two opponents are distinct;
    # pair matching also requires both names to match in unique positions.
    if len(a_words) == 1 or len(b_words) == 1:
        return True
    return a_words[0][0] == b_words[0][0]


def decimal_price(value: Any, old_cents: Any = None) -> float | None:
    """Prefer Kalshi's fixed-point dollar fields over legacy cent fields."""
    try:
        if value is not None and str(value) != "":
            p = float(value)
        elif old_cents is not None:
            p = float(old_cents) / 100.0
        else:
            return None
        return p if 0.0 <= p <= 1.0 else None
    except (TypeError, ValueError):
        return None


def market_price(market: dict, side: str = "yes") -> float | None:
    return decimal_price(market.get(f"{side}_ask_dollars"), market.get(f"{side}_ask"))


def market_bid(market: dict, side: str = "yes") -> float | None:
    return decimal_price(market.get(f"{side}_bid_dollars"), market.get(f"{side}_bid"))


def market_last(market: dict) -> float | None:
    return decimal_price(market.get("last_price_dollars"), market.get("last_price"))


def is_open_market(market: dict) -> bool:
    # An explicit API status=open request can still return status="active".
    return market.get("status", "") in ("active", "open")


def matchup_from_event(event: dict) -> dict | None:
    """Recognize real open match-winner contracts; preserve YES/NO side exactly.

    Kalshi's ATP/WTA match markets commonly use ONE binary market, where
    YES means player A and NO means player B. Some series can instead contain
    two distinct per-player YES markets. Never infer the other player's side
    from closing prices or from the title alone.
    """
    markets = [m for m in event.get("markets", []) if isinstance(m, dict)
               and is_open_market(m) and m.get("ticker")
               and market_price(m, "yes") is not None]
    if len(markets) == 1:
        m = markets[0]
        yes = (m.get("yes_sub_title") or "").strip()
        no = (m.get("no_sub_title") or "").strip()
        if (yes and no and key_name(yes) not in {"yes", "winner", "true"}
                and key_name(no) not in {"no", "loser", "false"}
                and not same_player(yes, no)
                and market_price(m, "no") is not None):
            return {"event_ticker": event.get("event_ticker") or event.get("ticker"),
                    "event_title": event.get("title") or "Tennis match",
                    "names": (yes, no), "markets": (m, m),
                    "sides": ("yes", "no")}
    # Alternate: distinct YES contracts, each representing one of two players.
    named = []
    for m in markets:
        name = (m.get("yes_sub_title") or "").strip()
        if not name or key_name(name) in {"yes", "no", "winner", "true", "false"}:
            continue
        if any(same_player(name, old[0]) for old in named):
            continue
        named.append((name, m))
    if len(named) != 2 or same_player(named[0][0], named[1][0]):
        return None
    return {"event_ticker": event.get("event_ticker") or event.get("ticker"),
            "event_title": event.get("title") or "Tennis match",
            "names": (named[0][0], named[1][0]),
            "markets": (named[0][1], named[1][1]),
            "sides": ("yes", "yes")}


def competitor_name(competitor: dict) -> tuple[str, dict] | None:
    if not isinstance(competitor, dict):
        return None
    people = competitor.get("athletes")
    if isinstance(people, list) and len(people) > 1:
        return None  # Exclude doubles
    athlete = competitor.get("athlete") or {}
    if not athlete and isinstance(people, list) and len(people) == 1:
        athlete = people[0].get("athlete", people[0])
    if not isinstance(athlete, dict):
        athlete = {}
    name = athlete.get("displayName") or athlete.get("fullName") or competitor.get("displayName") or ""
    if not name or "/" in name or " & " in name:
        return None
    return str(name), athlete


def espn_competitions(data: dict):
    for event in data.get("events", []):
        if not isinstance(event, dict):
            continue
        tournament = event.get("name") or event.get("shortName") or "Tournament"
        for group in event.get("groupings", []):
            if isinstance(group, dict):
                for comp in group.get("competitions", []):
                    if isinstance(comp, dict):
                        yield tournament, comp, event
        for comp in event.get("competitions", []):
            if isinstance(comp, dict):
                yield tournament, comp, event


def parse_espn_matches(data: dict, tour: str) -> list[dict]:
    matches = []
    for tournament, comp, event in espn_competitions(data):
        competitors = comp.get("competitors") or []
        if len(competitors) != 2:
            continue
        p = [competitor_name(c) for c in competitors]
        if p[0] is None or p[1] is None or same_player(p[0][0], p[1][0]):
            continue
        status = comp.get("status") or {}
        typ = status.get("type") or {}
        state = str(typ.get("state") or "").lower()
        name = str(typ.get("name") or "").upper()
        completed = bool(typ.get("completed"))
        is_pre = (state == "pre" or name in ("STATUS_SCHEDULED", "SCHEDULED")) and not completed
        is_post = completed or state == "post" or name in ("STATUS_FINAL", "FINAL")
        start = parse_dt(comp.get("date") or comp.get("startDate"))
        if not start:  # Tournament's event.date is NOT a match start time.
            continue
        winner_idx = None
        for i, c in enumerate(competitors):
            if c.get("winner") is True:
                winner_idx = i
        matches.append({
            "id": str(comp.get("id") or ""),
            "tour": tour,
            "tournament": tournament,
            "round": str((comp.get("round") or {}).get("displayName") or ""),
            "date": start,
            "names": (p[0][0], p[1][0]),
            "athletes": (p[0][1], p[1][1]),
            "pre": is_pre,
            "post": is_post,
            "winner": winner_idx,
            "status": str(typ.get("description") or typ.get("detail") or name or state),
        })
    return matches


def matching_fixture(names: tuple[str, str], fixtures: list[dict], now: datetime,
                     min_lead_minutes: int = 10) -> dict | None:
    candidates = []
    for f in fixtures:
        if not f["pre"] or f["post"]:
            continue
        if f["date"] <= now + timedelta(minutes=min_lead_minutes):
            continue
        a, b = f["names"]
        if ((same_player(names[0], a) and same_player(names[1], b)) or
            (same_player(names[0], b) and same_player(names[1], a))):
            candidates.append(f)
    # Ambiguous aliases must not display an event; strict by design.
    unique = {f.get("id") or (f["date"], f["names"]): f for f in candidates}
    return list(unique.values())[0] if len(unique) == 1 else None


def join_kalshi_espn(events_by_tour: dict, fixtures_by_tour: dict, now: datetime) -> list[dict]:
    result = []
    for tour, events in events_by_tour.items():
        fixtures = fixtures_by_tour.get(tour, [])
        for event in events:
            match = matchup_from_event(event)
            if not match:
                continue
            fixture = matching_fixture(match["names"], fixtures, now)
            if not fixture:
                continue
            market_names = match["names"]
            fixture_names = fixture["names"]
            if same_player(market_names[0], fixture_names[0]):
                markets = match["markets"]
                sides = match["sides"]
            else:
                markets = (match["markets"][1], match["markets"][0])
                sides = (match["sides"][1], match["sides"][0])
            result.append({
                **match, "tour": tour, "fixture": fixture,
                "names": fixture_names, "markets": markets,
                "sides": sides,
            })
    deduped = {m["event_ticker"]: m for m in result if m.get("event_ticker")}
    return sorted(deduped.values(), key=lambda m: (m["fixture"]["date"], m["names"]))


def summarize_form(player: str, past: list[dict], now: datetime,
                   count: int = 5) -> dict:
    recent = []
    for match in past:
        if not match["post"] or match["winner"] is None or match["date"] >= now:
            continue
        if same_player(player, match["names"][0]):
            player_idx = 0
        elif same_player(player, match["names"][1]):
            player_idx = 1
        else:
            continue
        recent.append((match, player_idx == match["winner"]))
    recent.sort(key=lambda item: item[0]["date"], reverse=True)
    recent = recent[:count]
    return {"played": len(recent), "wins": sum(win for _, win in recent),
            "sequence": " ".join("W" if win else "L" for _, win in recent) or "Not available"}


def recent_h2h(a: str, b: str, past: list[dict], now: datetime) -> tuple[int, int]:
    wins = [0, 0]
    for m in past:
        if not m["post"] or m["winner"] is None or m["date"] >= now:
            continue
        first, second = m["names"]
        if same_player(a, first) and same_player(b, second):
            wins[0 if m["winner"] == 0 else 1] += 1
        elif same_player(a, second) and same_player(b, first):
            wins[0 if m["winner"] == 1 else 1] += 1
    return tuple(wins)


def format_az(dt: datetime) -> str:
    return dt.astimezone(ARIZONA).strftime("%a %b %-d · %-I:%M %p MST")


def net_if_win(ask: float, count: int) -> float:
    return round((1.0 - ask) * count, 2)
