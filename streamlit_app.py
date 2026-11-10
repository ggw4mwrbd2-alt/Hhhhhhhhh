"""Kalshi Tennis Scout — read-only, Kalshi-verified, upcoming ATP/WTA singles.

Run: streamlit run streamlit_app.py
No Kalshi trading credentials are needed or accepted.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

from tennis_core import (
    ARIZONA, format_az, join_kalshi_espn, key_name, market_bid,
    market_last, market_price, net_if_win, parse_espn_matches,
    recent_h2h, same_player, summarize_form,
)

API = "https://external-api.kalshi.com/trade-api/v2"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis"
SERIES = {"ATP": "KXATPMATCH", "WTA": "KXWTAMATCH"}
USER_AGENT = "KalshiTennisScout/1.0 (read-only statistics dashboard)"

st.set_page_config(page_title="Kalshi Tennis Scout", page_icon="🎾", layout="wide")


def get_json(url: str, params: dict | None = None) -> dict:
    r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT,
                                                  "Accept": "application/json"}, timeout=14)
    r.raise_for_status()
    value = r.json()
    if not isinstance(value, dict):
        raise ValueError(f"Unexpected response from {url}")
    return value


@st.cache_data(ttl=90, show_spinner=False)
def get_kalshi_events(series: str) -> list[dict]:
    """Only genuine open Kalshi match events; fetch all available pages."""
    result, cursor = [], None
    for _ in range(20):
        params = {"series_ticker": series, "status": "open", "limit": 200,
                  "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        page = get_json(f"{API}/events", params)
        result.extend(page.get("events", []))
        cursor = page.get("cursor")
        if not cursor:
            return result
    raise RuntimeError("Kalshi event pagination exceeded 20 pages; not displaying incomplete data")


@st.cache_data(ttl=90, show_spinner=False)
def get_espn_current(tour: str, month: str, day: str, tomorrow: str) -> list[dict]:
    """Strict live schedule/status source. No event status, no display."""
    matches = {}
    for date_term in (month, day, tomorrow):
        response = get_json(f"{ESPN}/{tour.lower()}/scoreboard", {"dates": date_term})
        for m in parse_espn_matches(response, tour):
            identity = m["id"] or (m["names"], m["date"])
            # Prefer the freshest (date-filtered) schedule state.
            matches[identity] = m
    return list(matches.values())


@st.cache_data(ttl=60 * 60 * 3, show_spinner=False)
def get_history(tour: str, month_keys: tuple[str, ...]) -> list[dict]:
    """ESPN monthly scoreboard results are a *limited sample*, not career H2H."""
    matches = {}
    for month in month_keys:
        response = get_json(f"{ESPN}/{tour.lower()}/scoreboard", {"dates": month})
        for m in parse_espn_matches(response, tour):
            identity = m["id"] or (m["names"], m["date"])
            matches[identity] = m
    return list(matches.values())


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def get_rankings(tour: str) -> dict[str, int]:
    """ESPN ranking data if offered by the feed; missing rank remains missing."""
    data = get_json(f"{ESPN}/{tour.lower()}/rankings")
    output = {}

    def walk(obj, depth=0):
        if depth > 11:
            return
        if isinstance(obj, list):
            for child in obj:
                walk(child, depth + 1)
        if isinstance(obj, dict):
            athlete = obj.get("athlete")
            rank = obj.get("current") or obj.get("rank")
            if isinstance(rank, dict):
                rank = rank.get("current") or rank.get("value") or rank.get("rank")
            if isinstance(athlete, dict) and rank is not None:
                name = athlete.get("displayName") or athlete.get("fullName")
                try:
                    n = int(rank)
                    if name and n > 0:
                        output[key_name(name)] = n
                except (TypeError, ValueError):
                    pass
            for child in obj.values():
                if isinstance(child, (dict, list)):
                    walk(child, depth + 1)
    walk(data)
    return output


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def get_player_profile(tour: str, athlete_id: str) -> dict:
    if not athlete_id:
        return {}
    return get_json(f"{ESPN}/{tour.lower()}/athletes/{athlete_id}")


def get_secret(name: str) -> str:
    try:
        return str(st.secrets.get(name) or os.environ.get(name) or "")
    except Exception:
        return str(os.environ.get(name) or "")


def date_months(now: datetime) -> tuple[str, ...]:
    first = now.replace(day=1)
    prev = first - timedelta(days=1)
    before_prev = prev.replace(day=1) - timedelta(days=1)
    return tuple(d.strftime("%Y%m") for d in (before_prev, prev, first))


def currency(q: float | None) -> str:
    return "—" if q is None else f"{100 * q:.1f}¢"


def person_rank(name: str, rankings: dict) -> str:
    for source_name, rank in rankings.items():
        if same_player(name, source_name):
            return f"#{rank}"
    return "Not available"


def profile_age(tour: str, athlete: dict, now: datetime) -> str:
    birth = athlete.get("dateOfBirth") or ""
    if not birth and athlete.get("id"):
        try:
            profile = get_player_profile(tour, str(athlete["id"]))
            bio = profile.get("athlete", profile)
            birth = bio.get("dateOfBirth") or ""
        except Exception:
            birth = ""
    if not birth:
        return "Not available"
    try:
        birthday = datetime.fromisoformat(str(birth)[:10]).date()
        today = now.date()
        if birthday > today:
            return "Not available"
        return str(today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day)))
    except ValueError:
        return "Not available"


def render_analyst(match: dict, history: list[dict], rankings: dict, now: datetime):
    fixture = match["fixture"]
    names = match["names"]
    quotes = match["markets"]
    sides = match["sides"]
    st.subheader(f"{names[0]} vs {names[1]}")
    st.caption(f"{match['tour']} · {fixture['tournament']} · {fixture['round'] or 'Round unlisted'} · "
               f"{format_az(fixture['date'])}")
    st.info(f"Confirmed: both named player outcomes appear in Kalshi's OPEN match market; "
            f"the same singles match is marked PRE-MATCH by ESPN. "
            f"Checked at {now.astimezone(ARIZONA).strftime('%-I:%M %p MST')}.")
    st.write(f"**Kalshi event ID:** `{match['event_ticker']}`")
    market_url = (f"https://kalshi.com/markets/{SERIES[match['tour']].lower()}/"
                  f"{'atp' if match['tour'] == 'ATP' else 'wta'}-tennis-match/"
                  f"{match['event_ticker'].lower()}")
    st.link_button("Open this match on Kalshi", market_url)

    cols = st.columns(2)
    forms = []
    for i in (0, 1):
        name, m = names[i], quotes[i]
        f = summarize_form(name, history, now)
        forms.append(f)
        with cols[i]:
            st.markdown(f"#### {name}")
            side = sides[i]
            st.metric(f"{side.upper()} ask (entry price)", currency(market_price(m, side)))
            st.write(f"**{side.upper()} bid:** {currency(market_bid(m, side))}")
            if side == "yes":
                st.caption(f"Last YES trade: {currency(market_last(m))}")
            st.write(f"**ATP/WTA rank:** {person_rank(name, rankings)}")
            athlete = fixture["athletes"][i]
            st.write(f"**Age:** {profile_age(match['tour'], athlete, now)}")
            st.write(f"**Recent form:** {f['sequence']} "
                     f"({f['wins']}/{f['played']} wins, sample)")
            st.caption(f"Market: {m['ticker']}")

    h2h = recent_h2h(names[0], names[1], history, now)
    st.write(f"**Head-to-head in loaded ESPN results:** {h2h[0]}–{h2h[1]} "
             "(not lifetime head-to-head).")
    st.caption("Recent form uses up to five completed singles matches in ESPN's loaded "
               "recent months. Missing results/rankings/ages are not guessed. Surface "
               "statistics and career H2H require additional verified research.")

    st.divider()
    st.subheader("Contract payoff calculator")
    pick = st.selectbox("Select winning outcome", names, key=f"pick-{match['event_ticker']}")
    contracts = st.number_input("Number of contracts", min_value=1, max_value=1000, value=10, step=1)
    idx = 0 if pick == names[0] else 1
    price = market_price(quotes[idx], sides[idx])
    if price is None:
        st.warning("No executable ask price is present.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Ask cost", f"${price * contracts:,.2f}")
        c2.metric("Net if selected side wins", f"${net_if_win(price, contracts):,.2f}")
        c3.metric("Loss if selected side loses", f"${price * contracts:,.2f}")
        st.caption(f"Break-even probability before fees: {price:.1%}. "
                   "Excludes trading fees, slippage, settlement adjustments, and partial fills. "
                   "Displayed quotes may have changed; check Kalshi before trading.")
        with st.expander("Check potential value against YOUR probability estimate"):
            estimate = st.number_input("Your independently estimated chance (%)", min_value=1.0,
                                       max_value=99.0, value=round(price * 100, 1), step=1.0)
            st.write(f"Difference from entry ask: **{estimate - 100 * price:+.1f} percentage points** "
                     "before fees. This is not a model-generated probability or a bet recommendation.")

    st.divider()
    st.subheader("Optional AI research")
    st.caption("Uses OpenAI API web search and may incur charges. It only researches this "
               "already Kalshi-verified match; it cannot add unverified matches to the list.")
    if not get_secret("OPENAI_API_KEY"):
        st.info("Add an OPENAI_API_KEY in your app's Streamlit secrets to enable cited AI research. "
                "The Kalshi scanner and payoff calculator work without it.")
    elif st.button("Research ages, surface records, H2H and recent form", type="primary"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=get_secret("OPENAI_API_KEY"), timeout=45)
            prompt = f"""Analyze this UPCOMING tennis singles match with citations for every external fact.
Match: {names[0]} vs {names[1]}; {match['tour']}, {fixture['tournament']}, {fixture['round']}.
Start: {fixture['date'].isoformat()}. Kalshi event: {match['event_ticker']}.
Kalshi asks: {names[0]}={sides[0].upper()} {currency(market_price(quotes[0], sides[0]))},
{names[1]}={sides[1].upper()} {currency(market_price(quotes[1], sides[1]))}.
ESPN recent-form sample: {names[0]}={forms[0]['sequence']}, {names[1]}={forms[1]['sequence']}.
ESPN limited H2H sample {h2h[0]}-{h2h[1]}.
Find: each player's date of birth/age, currently dated rankings, most recent 5 match results,
career head-to-head if independently available, surface performance and injuries ONLY if
reliably sourced, and tactical matchup factors. Be cautious about season/year/tournament
ambiguity. Cite URLs, name the date of data, say Not verified when missing.
Do NOT invent injury news, numerical win probabilities, or guaranteed returns.
Do not make a betting recommendation. Explain how market entry price affects risk/reward.
Do NOT assume the match is still pre-match when this research completes: require the user to refresh.
"""
            answer = client.responses.create(model="gpt-5-mini", tools=[{"type": "web_search"}],
                                             input=prompt)
            st.markdown(answer.output_text)
        except Exception as exc:
            st.error(f"AI research failed: {exc}")


st.title("🎾 Kalshi Tennis Scout")
st.caption("Verified Kalshi match-winner markets × ESPN pre-match fixtures · Arizona MST · read-only")

now = datetime.now(timezone.utc)
now_az = now.astimezone(ARIZONA)
with st.sidebar:
    st.header("Filters")
    tour_choices = st.multiselect("Tour", ["ATP", "WTA"], default=["ATP", "WTA"])
    hours = st.select_slider("Upcoming window", options=[12, 24, 48, 72, 168], value=48,
                             format_func=lambda n: f"{n} hours")
    if st.button("Refresh live data"):
        get_kalshi_events.clear()
        get_espn_current.clear()
        st.rerun()
    st.caption("Only verified upcoming matches appear. Unconfirmed Challenger/ITF "
               "start times are intentionally excluded in this version.")
    st.caption("Markets shown may change; no trade execution or account connection.")

if not tour_choices:
    st.warning("Select ATP or WTA in the sidebar.")
    st.stop()

match_events, espn_fixtures, errors = {}, {}, []
with st.spinner("Checking Kalshi and independent tennis status feeds…"):
    for tour in tour_choices:
        try:
            match_events[tour] = get_kalshi_events(SERIES[tour])
        except Exception as exc:
            match_events[tour] = []
            errors.append(f"Kalshi {tour} unavailable: {exc}")
        try:
            month = now_az.strftime("%Y%m")
            day = now_az.strftime("%Y%m%d")
            tomorrow = (now_az + timedelta(days=1)).strftime("%Y%m%d")
            espn_fixtures[tour] = get_espn_current(tour, month, day, tomorrow)
        except Exception as exc:
            espn_fixtures[tour] = []
            errors.append(f"ESPN {tour} unavailable: {exc}")

for err in errors:
    st.error(err)

matched = join_kalshi_espn(match_events, espn_fixtures, now)
upcoming = [m for m in matched if m["fixture"]["date"] <= now + timedelta(hours=hours)]
summary, quality = st.columns(2)
summary.metric("Confirmed upcoming Kalshi matches", len(upcoming))
quality.metric("Live market events checked", sum(len(v) for v in match_events.values()))
st.caption("Strict filter: open Kalshi match-winner outcome(s) for both players, "
           "confident player identity match, ESPN singles status scheduled, "
           "and scheduled start at least 10 minutes in the future. ")

if errors:
    st.warning("One or more upstream sources failed. Missing matches are not filled with guesses.")
if not upcoming:
    st.info("No upcoming matches met *both* verification checks in the selected window. "
            "This does not mean Kalshi has no tennis markets. Try a longer window or refresh later.")
    st.link_button("View Kalshi tennis markets", "https://kalshi.com/category/sports/tennis")
    st.stop()

rows = []
for m in upcoming:
    rows.append({
        "Arizona start": format_az(m["fixture"]["date"]),
        "Tour": m["tour"],
        "Match": f"{m['names'][0]} vs {m['names'][1]}",
        "Player 1 entry ask": f"{m['sides'][0].upper()} {currency(market_price(m['markets'][0], m['sides'][0]))}",
        "Player 2 entry ask": f"{m['sides'][1].upper()} {currency(market_price(m['markets'][1], m['sides'][1]))}",
        "Kalshi event": m["event_ticker"],
    })

st.dataframe(rows, use_container_width=True, hide_index=True)
labels = [f"{format_az(m['fixture']['date'])} | {m['names'][0]} vs {m['names'][1]} "
          f"({m['tour']})" for m in upcoming]
selection = st.selectbox("Choose a verified matchup to analyze", range(len(upcoming)),
                         format_func=lambda i: labels[i])
chosen = upcoming[selection]
with st.spinner("Loading limited historical results and rankings…"):
    try:
        hist = get_history(chosen["tour"], date_months(now_az))
    except Exception as exc:
        hist = []
        st.warning(f"Historical results unavailable: {exc}")
    try:
        ranks = get_rankings(chosen["tour"])
    except Exception as exc:
        ranks = {}
        st.warning(f"Ranking data unavailable: {exc}")
render_analyst(chosen, hist, ranks, now)

st.divider()
st.caption("Data: public Kalshi Markets/Events API; ESPN tennis scoreboard/rankings. "
           "No unattended monitoring, automatic trades, market alerts, or personal account access. "
           "Unofficial ESPN endpoint may change. This tool cannot guarantee upstream feeds are instantaneous. "
           "Kalshi settlement rules and fees control actual outcomes and payouts.")
