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
        "sort_desc": False,
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


def parse_clock_to_seconds(clock_str):
    try:
        m, s = clock_str.split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return None


def seconds_to_clock(sec):
    return f"{sec // 60}:{sec % 60:02d}"


def convert_to_time_remaining(clock_str, period, game_data=None):
    secs_elapsed = parse_clock_to_seconds(clock_str)
    if secs_elapsed is None:
        return clock_str

    period_len = 1200

    if period is not None and period > 3:
        game_type = ""
        if game_data:
            game_type = str(game_data.get("gameType", ""))

        # NHL convention:
        # 02 = regular season
        # 03 = playoffs
        if game_type == "03":
            period_len = 1200
        else:
            period_len = 300

    return seconds_to_clock(max(0, period_len - secs_elapsed))


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


def build_team_lookup(game_data):
    home = game_data.get("homeTeam", {}) or {}
    away = game_data.get("awayTeam", {}) or {}

    return {
        home.get("id"): extract_abbrev(home.get("abbrev"), "HOME"),
        away.get("id"): extract_abbrev(away.get("abbrev"), "AWAY"),
    }


def resolve_team(play, team_lookup, home_abbrev, away_abbrev):
    details = play.get("details", {}) or {}

    for tid in [
        play.get("eventOwnerTeamId"),
        details.get("eventOwnerTeamId"),
        details.get("teamId"),
    ]:
        if tid in team_lookup:
            team = team_lookup[tid]
            break
    else:
        team = (
            extract_abbrev(play.get("teamAbbrev"), None)
            or extract_abbrev(details.get("eventOwnerTeamAbbrev"), None)
            or extract_abbrev(details.get("teamAbbrev"), None)
            or "UNK"
        )

    if team == home_abbrev:
        return f"{team} (Home)"
    elif team == away_abbrev:
        return f"{team} (Away)"
    else:
        return team


def parse_faceoffs(game_data):
    plays = game_data.get("plays", []) or []

    team_lookup = build_team_lookup(game_data)
    teams = list(team_lookup.values())
    home_abbrev = teams[0] if len(teams) > 0 else "HOME"
    away_abbrev = teams[1] if len(teams) > 1 else "AWAY"

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
                "time": convert_to_time_remaining(raw_time, period, game_data),
                "team": resolve_team(play, team_lookup, home_abbrev, away_abbrev),
            }
        )

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

    period_lists = {}
    for f in faceoffs:
        p = f["period"]
        if p not in period_lists:
            period_lists[p] = []
        period_lists[p].append(f)

    for p in period_lists:
        count = 0
        new_list = []
        for f in period_lists[p]:
            count += 1
            f_copy = dict(f)
            f_copy["num"] = count
            new_list.append(f_copy)
        period_lists[p] = new_list

    current_period = faceoffs[-1]["period"] if faceoffs else 1

    return {
        "period_lists": period_lists,
        "current_period": current_period,
        "current_count": len(period_lists.get(current_period, [])),
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
            padding:14px;
            font-size:24px;
            font-weight:600;
            background:{bg};
            color:{color};
            border-radius:8px;
            margin-bottom:14px;">
            {msg}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_faceoff_list(faceoffs, sort_desc):
    if sort_desc:
        faceoffs = list(reversed(faceoffs))

    html_lines = "".join([
        f"<div style='padding:6px 0;'>"
        f"<span style='font-weight:600;'>{str(f['num']).rjust(2)}</span>   {f['time']}   {f['team']}"
        f"</div>"
        for f in faceoffs
    ])

    st.markdown(
        f"""
        <div style="
            font-family: monospace;
            font-size:16px;
            line-height:1.6;
        ">
        {html_lines}
        </div>
        """,
        unsafe_allow_html=True,
    )


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

st.toggle("Show newest first", key="sort_desc")

if st.session_state.tracking:
    state = get_state(st.session_state.selected_game_id)
    st_autorefresh(interval=REFRESH_MS, key="refresh")

    current = state["current_count"]
    period = state["current_period"]

    prev = st.session_state.previous_count
    prev_p = st.session_state.previous_period

    if prev_p == period:
        if prev is not None and current < prev:
            warning_box(f"COUNT DECREASE: {prev} → {current}", True)
        elif prev is not None and current - prev > 1:
            warning_box(f"MULTIPLE FACEOFFS ADDED: +{current - prev}", True)
        else:
            warning_box("STATUS: OK", False)
    else:
        warning_box(f"Period {period} started", False)

    st.session_state.previous_count = current
    st.session_state.previous_period = period

    st.markdown(
        f"<div style='font-size:80px; font-weight:700'>{current}</div>",
        unsafe_allow_html=True,
    )

    bp = state["by_period"]

    st.markdown(
        f"P1: {bp.get(1,0)}   P2: {bp.get(2,0)}   P3: {bp.get(3,0)}   Total: {state['total']}"
    )

    if state["last"]:
        lf = state["last"]
        st.markdown(
            f"<div style='font-size:15px; opacity:0.8;'>"
            f"Last Faceoff — P{lf['period']} {lf['time']}   {lf['team']}"
            f"</div>",
            unsafe_allow_html=True
        )

    st.markdown("")

    periods = sorted(state["period_lists"].keys())
    tabs = st.tabs([f"P{p}" for p in periods])

    for i, p in enumerate(periods):
        with tabs[i]:
            render_faceoff_list(state["period_lists"][p], st.session_state.sort_desc)

else:
    warning_box("STATUS: OK", False)
    st.info("Load games and track a game.")
