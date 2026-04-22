import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

SCOREBOARD_URL = "https://api-web.nhle.com/v1/scoreboard/now"
PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
REFRESH_MS = 3000

st.set_page_config(page_title="Faceoff Counter", layout="centered")


# ------------------ STATE ------------------ #
def init_state():
    defaults = {
        "games": [],
        "selected_game_label": None,
        "selected_game_id": None,
        "tracking": False,
        "previous_count": None,
        "previous_period": None,
        "warning_message": "STATUS: OK",
        "warning_type": "ok",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ------------------ DATA ------------------ #
def fetch_json(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()


def load_live_games():
    data = fetch_json(SCOREBOARD_URL)
    games = []

    for day in data.get("gamesByDate", []):
        for game in day.get("games", []):
            if game.get("gameState") in {"LIVE", "CRIT"}:
                away = game["awayTeam"]["abbrev"]
                home = game["homeTeam"]["abbrev"]
                gid = game["id"]
                label = f"{away} @ {home} ({gid})"

                games.append({
                    "label": label,
                    "id": gid
                })
    return games


def parse_faceoffs(plays):
    faceoffs = []

    for play in plays:
        if str(play.get("typeDescKey", "")).lower() == "faceoff":
            team = (
                play.get("teamAbbrev", {}).get("default")
                or play.get("team", {}).get("abbrev")
                or "UNK"
            )

            faceoffs.append({
                "event_id": play.get("eventId"),
                "period": play.get("periodDescriptor", {}).get("number"),
                "time": play.get("timeInPeriod"),
                "team": team
            })

    # dedupe
    seen = {}
    for f in faceoffs:
        seen[f["event_id"]] = f

    return list(seen.values())


def get_state(game_id):
    data = fetch_json(PBP_URL.format(game_id=game_id))
    plays = data.get("plays", [])

    faceoffs = parse_faceoffs(plays)

    # split by period
    by_period = {}
    for f in faceoffs:
        p = f["period"]
        by_period[p] = by_period.get(p, 0) + 1

    current_period = faceoffs[-1]["period"] if faceoffs else 1

    current_period_faceoffs = [
        f for f in faceoffs if f["period"] == current_period
    ]

    last_faceoff = faceoffs[-1] if faceoffs else None

    return {
        "all": faceoffs,
        "by_period": by_period,
        "current_period": current_period,
        "current_list": current_period_faceoffs,
        "current_count": len(current_period_faceoffs),
        "total": len(faceoffs),
        "last": last_faceoff
    }


# ------------------ UI ------------------ #
def warning_box(msg, alert):
    if alert:
        st.markdown(
            f"""
            <div style="
                padding:16px;
                font-size:28px;
                font-weight:700;
                background:#3a1600;
                color:#ffd966;
                border:2px solid #ff9900;
                border-radius:10px;
                margin-bottom:16px;">
                {msg}
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="
                padding:16px;
                font-size:28px;
                font-weight:700;
                background:#132117;
                color:#66ff99;
                border:2px solid #2e6b45;
                border-radius:10px;
                margin-bottom:16px;">
                {msg}
            </div>
            """,
            unsafe_allow_html=True,
        )


# ------------------ APP ------------------ #
init_state()

st.title("NHL Faceoff Counter")

col1, col2 = st.columns(2)

# Load games
with col1:
    if st.button("Load Live Games", use_container_width=True):
        try:
            games = load_live_games()
            st.session_state.games = games

            if games:
                st.session_state.selected_game_label = games[0]["label"]
                st.session_state.selected_game_id = games[0]["id"]
                st.success(f"{len(games)} game(s) loaded")
            else:
                st.info("No live games found.")

        except Exception as e:
            st.error(str(e))

# Select game
labels = [g["label"] for g in st.session_state.games]

selected = st.selectbox(
    "Games",
    options=labels,
    index=labels.index(st.session_state.selected_game_label)
    if st.session_state.selected_game_label in labels else 0
)

if selected:
    for g in st.session_state.games:
        if g["label"] == selected:
            st.session_state.selected_game_id = g["id"]

# Track
with col2:
    if st.button("Track Selected Game", use_container_width=True):
        st.session_state.tracking = True
        st.session_state.previous_count = None
        st.session_state.previous_period = None


# ------------------ LIVE ------------------ #
if st.session_state.tracking:

    st_autorefresh(interval=REFRESH_MS, key="refresh")

    try:
        state = get_state(st.session_state.selected_game_id)

        current_count = state["current_count"]
        current_period = state["current_period"]

        prev_count = st.session_state.previous_count
        prev_period = st.session_state.previous_period

        # ----- WARNINGS ----- #
        if prev_period == current_period:
            if prev_count is not None:
                if current_count < prev_count:
                    msg = f"⚠ COUNT DECREASE: {prev_count} → {current_count}"
                    alert = True
                elif current_count - prev_count > 1:
                    msg = f"⚠ MULTIPLE FACEOFFS ADDED: +{current_count - prev_count}"
                    alert = True
                else:
                    msg = "STATUS: OK"
                    alert = False
            else:
                msg = "STATUS: OK"
                alert = False
        else:
            # new period → reset, no warning
            msg = f"Period {current_period} started"
            alert = False

        st.session_state.previous_count = current_count
        st.session_state.previous_period = current_period

        warning_box(msg, alert)

        # ----- MAIN COUNTER ----- #
        st.markdown(
            f"""
            <div style="font-size:80px; font-weight:800;">
                {current_count}
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ----- SUMMARY ----- #
        by_period = state["by_period"]

        st.markdown(
            f"""
            **Current Period:** P{current_period}  
            **P1:** {by_period.get(1,0)} | **P2:** {by_period.get(2,0)} | **P3:** {by_period.get(3,0)}  
            **Total (game):** {state["total"]}
            """
        )

        # ----- LAST FACEOFF ----- #
        if state["last"]:
            lf = state["last"]
            st.markdown(
                f"""
                **Last Faceoff:** P{lf['period']} {lf['time']} | Winner: {lf['team']} | Event {lf['event_id']}
                """
            )

        # ----- AUDIT LIST (CURRENT PERIOD ONLY) ----- #
        st.subheader(f"Period {current_period} Faceoffs")

        lines = [
            f"{i+1}. {f['time']} | {f['team']} | Event {f['event_id']}"
            for i, f in enumerate(state["current_list"])
        ]

        st.code("\n".join(lines) if lines else "No faceoffs yet.")

    except Exception as e:
        st.error(f"Error: {e}")

else:
    warning_box("STATUS: OK", False)
    st.info("Load games and click Track Selected Game.")
