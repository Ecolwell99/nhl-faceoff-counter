import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

SCOREBOARD_URL = "https://api-web.nhle.com/v1/scoreboard/now"
PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
REFRESH_MS = 3000

st.set_page_config(page_title="Faceoff Counter", layout="centered")


def init_state():
    defaults = {
        "games": [],
        "selected_game_label": None,
        "selected_game_id": None,
        "tracking": False,
        "previous_count": None,
        "previous_period": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def fetch_json(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def extract_abbrev(value, fallback="UNK"):
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        if value.get("default"):
            return value["default"]
        for v in value.values():
            if isinstance(v, str) and v:
                return v
    return fallback


def load_live_games():
    data = fetch_json(SCOREBOARD_URL)
    games = []

    for day in data.get("gamesByDate", []):
        for game in day.get("games", []):
            if game.get("gameState") in {"LIVE", "CRIT"}:
                away = extract_abbrev(game.get("awayTeam", {}).get("abbrev"), "AWAY")
                home = extract_abbrev(game.get("homeTeam", {}).get("abbrev"), "HOME")
                gid = game.get("id")
                label = f"{away} @ {home} ({gid})"
                games.append({"label": label, "id": gid})

    return games


def parse_clock_to_seconds(clock_str):
    try:
        m, s = clock_str.split(":")
        return int(m) * 60 + int(s)
    except:
        return None


def seconds_to_clock(sec):
    return f"{sec//60}:{sec%60:02d}"


def convert_to_time_remaining(clock_str, period):
    secs_elapsed = parse_clock_to_seconds(clock_str)
    if secs_elapsed is None:
        return clock_str

    period_len = 300 if (period and period > 3) else 1200
    return seconds_to_clock(max(0, period_len - secs_elapsed))


def build_team_lookup(game_data):
    home = game_data.get("homeTeam", {}) or {}
    away = game_data.get("awayTeam", {}) or {}

    return {
        home.get("id"): extract_abbrev(home.get("abbrev"), "HOME"),
        away.get("id"): extract_abbrev(away.get("abbrev"), "AWAY"),
    }


def resolve_team(play, team_lookup, home_abbrev, away_abbrev):
    details = play.get("details", {}) or {}

    # Try IDs
    for tid in [
        play.get("eventOwnerTeamId"),
        details.get("eventOwnerTeamId"),
        details.get("teamId"),
    ]:
        if tid in team_lookup:
            team = team_lookup[tid]
            break
    else:
        # fallback abbrev
        team = (
            extract_abbrev(play.get("teamAbbrev"), None)
            or extract_abbrev(details.get("eventOwnerTeamAbbrev"), None)
            or extract_abbrev(details.get("teamAbbrev"), None)
            or "UNK"
        )

    # attach Home/Away
    if team == home_abbrev:
        return f"{team} (Home)"
    elif team == away_abbrev:
        return f"{team} (Away)"
    else:
        return team


def parse_faceoffs(game_data):
    plays = game_data.get("plays", []) or []

    team_lookup = build_team_lookup(game_data)
    home_abbrev = list(team_lookup.values())[0]
    away_abbrev = list(team_lookup.values())[1]

    faceoffs = []

    for play in plays:
        if str(play.get("typeDescKey", "")).lower() != "faceoff":
            continue

        period = play.get("periodDescriptor", {}).get("number")
        raw_time = play.get("timeInPeriod", "")

        faceoffs.append(
            {
                "event_id": play.get("eventId"),
                "period": period,
                "time": convert_to_time_remaining(raw_time, period),
                "team": resolve_team(play, team_lookup, home_abbrev, away_abbrev),
            }
        )

    # dedupe
    seen = {}
    for f in faceoffs:
        seen[f["event_id"]] = f

    return list(seen.values())


def get_state(game_id):
    data = fetch_json(PBP_URL.format(game_id=game_id))
    faceoffs = parse_faceoffs(data)

    by_period = {}
    for f in faceoffs:
        by_period[f["period"]] = by_period.get(f["period"], 0) + 1

    current_period = faceoffs[-1]["period"] if faceoffs else 1
    current_list = [f for f in faceoffs if f["period"] == current_period]

    return {
        "current_period": current_period,
        "current_list": current_list,
        "current_count": len(current_list),
        "by_period": by_period,
        "total": len(faceoffs),
        "last": faceoffs[-1] if faceoffs else None,
    }


def warning_box(msg, alert):
    color = "#ffd966" if alert else "#66ff99"
    bg = "#3a1600" if alert else "#132117"

    st.markdown(
        f"""
        <div style="
            padding:16px;
            font-size:26px;
            font-weight:700;
            background:{bg};
            color:{color};
            border-radius:10px;
            margin-bottom:16px;">
            {msg}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------- APP ---------------- #
init_state()

st.title("NHL Faceoff Counter")

col1, col2 = st.columns(2)

with col1:
    if st.button("Load Live Games", use_container_width=True):
        games = load_live_games()
        st.session_state.games = games

        if games:
            st.session_state.selected_game_label = games[0]["label"]
            st.session_state.selected_game_id = games[0]["id"]
        else:
            st.info("No live games found.")

labels = [g["label"] for g in st.session_state.games]

selected = st.selectbox("Games", options=labels)

if selected:
    for g in st.session_state.games:
        if g["label"] == selected:
            st.session_state.selected_game_id = g["id"]

with col2:
    if st.button("Track Selected Game", use_container_width=True):
        st.session_state.tracking = True
        st.session_state.previous_count = None
        st.session_state.previous_period = None


if st.session_state.tracking:
    st_autorefresh(interval=REFRESH_MS, key="refresh")

    state = get_state(st.session_state.selected_game_id)

    current = state["current_count"]
    period = state["current_period"]

    prev = st.session_state.previous_count
    prev_p = st.session_state.previous_period

    if prev_p == period:
        if prev is not None and current < prev:
            warning_box(f"⚠ COUNT DECREASE: {prev} → {current}", True)
        elif prev is not None and current - prev > 1:
            warning_box(f"⚠ MULTIPLE FACEOFFS ADDED: +{current - prev}", True)
        else:
            warning_box("STATUS: OK", False)
    else:
        warning_box(f"Period {period} started", False)

    st.session_state.previous_count = current
    st.session_state.previous_period = period

    st.markdown(f"<div style='font-size:80px;font-weight:800'>{current}</div>", unsafe_allow_html=True)

    bp = state["by_period"]
    st.markdown(
        f"**P1:** {bp.get(1,0)} | **P2:** {bp.get(2,0)} | **P3:** {bp.get(3,0)} | **Total:** {state['total']}"
    )

    if state["last"]:
        lf = state["last"]
        st.markdown(f"**Last Faceoff:** P{lf['period']} {lf['time']} | {lf['team']}")

    st.subheader(f"Period {period} Faceoffs")

    lines = [
        f"{i+1}. {f['time']} | {f['team']}"
        for i, f in enumerate(state["current_list"])
    ]

    st.code("\n".join(lines) if lines else "No faceoffs yet.")

else:
    warning_box("STATUS: OK", False)
    st.info("Load games and track a game.")
