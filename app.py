import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

SCOREBOARD_URL = "https://api-web.nhle.com/v1/scoreboard/now"
PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
REFRESH_MS = 3000


st.set_page_config(page_title="NHL Faceoff Counter", layout="centered")


def init_state():
    defaults = {
        "games": [],
        "selected_game_label": None,
        "selected_game_id": None,
        "tracking": False,
        "previous_count": None,
        "warning_message": "STATUS: OK",
        "warning_type": "ok",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def fetch_json(url: str) -> dict:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def load_live_games():
    data = fetch_json(SCOREBOARD_URL)
    games = []

    for day in data.get("gamesByDate", []):
        for game in day.get("games", []):
            state = game.get("gameState")
            if state in {"LIVE", "CRIT"}:
                away = game.get("awayTeam", {}).get("abbrev", "AWAY")
                home = game.get("homeTeam", {}).get("abbrev", "HOME")
                game_id = game.get("id")
                label = f"{away} @ {home} ({game_id})"
                games.append(
                    {
                        "label": label,
                        "id": game_id,
                        "away": away,
                        "home": home,
                    }
                )

    return games


def parse_faceoffs(plays: list[dict]) -> list[dict]:
    faceoffs = []

    for play in plays or []:
        play_type = str(play.get("typeDescKey", "")).lower()

        if play_type == "faceoff":
            winner = (
                play.get("teamAbbrev", {}).get("default")
                or play.get("team", {}).get("abbrev")
                or "UNK"
            )

            faceoffs.append(
                {
                    "event_id": play.get("eventId"),
                    "period": play.get("periodDescriptor", {}).get("number"),
                    "time_in_period": play.get("timeInPeriod", ""),
                    "winner": winner,
                }
            )

    return faceoffs


def get_faceoff_state(game_id: int) -> dict:
    data = fetch_json(PBP_URL.format(game_id=game_id))
    plays = data.get("plays", [])

    raw_faceoffs = parse_faceoffs(plays)

    deduped = {}
    for faceoff in raw_faceoffs:
        deduped[faceoff["event_id"]] = faceoff

    unique_faceoffs = list(deduped.values())

    by_period = {}
    for faceoff in unique_faceoffs:
        period = faceoff["period"]
        by_period[period] = by_period.get(period, 0) + 1

    last_faceoff = unique_faceoffs[-1] if unique_faceoffs else None

    return {
        "total": len(unique_faceoffs),
        "by_period": by_period,
        "last_faceoff": last_faceoff,
        "faceoffs": unique_faceoffs,
    }


def warning_box(message: str, warning_type: str):
    if warning_type == "alert":
        st.markdown(
            f"""
            <div style="
                margin-top: 10px;
                margin-bottom: 18px;
                padding: 16px;
                border-radius: 10px;
                font-size: 28px;
                font-weight: 700;
                background-color: #3a1600;
                color: #ffd966;
                border: 2px solid #ff9900;
            ">
                {message}
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div style="
                margin-top: 10px;
                margin-bottom: 18px;
                padding: 16px;
                border-radius: 10px;
                font-size: 28px;
                font-weight: 700;
                background-color: #132117;
                color: #66ff99;
                border: 2px solid #2e6b45;
            ">
                {message}
            </div>
            """,
            unsafe_allow_html=True,
        )


init_state()

st.title("NHL Faceoff Counter")

col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Load Live Games", use_container_width=True):
        try:
            games = load_live_games()
            st.session_state.games = games

            if not games:
                st.session_state.selected_game_label = None
                st.session_state.selected_game_id = None
                st.session_state.tracking = False
                st.info("No live games found.")
            else:
                labels = [g["label"] for g in games]
                if st.session_state.selected_game_label not in labels:
                    st.session_state.selected_game_label = labels[0]
                    st.session_state.selected_game_id = games[0]["id"]
                st.success(f"Loaded {len(games)} live game(s).")
        except Exception as e:
            st.error(f"Error loading games: {e}")

game_labels = [g["label"] for g in st.session_state.games]

selected_label = st.selectbox(
    "Live games",
    options=game_labels,
    index=game_labels.index(st.session_state.selected_game_label)
    if st.session_state.selected_game_label in game_labels
    else None,
    placeholder="Load live games first",
    label_visibility="collapsed",
)

if selected_label:
    st.session_state.selected_game_label = selected_label
    for game in st.session_state.games:
        if game["label"] == selected_label:
            st.session_state.selected_game_id = game["id"]
            break

with col2:
    if st.button("Track Selected Game", use_container_width=True):
        if st.session_state.selected_game_id is None:
            st.warning("Load live games and select one first.")
        else:
            st.session_state.tracking = True
            st.session_state.previous_count = None
            st.session_state.warning_message = "STATUS: OK"
            st.session_state.warning_type = "ok"

if st.session_state.tracking:
    st_autorefresh(interval=REFRESH_MS, key="faceoff_refresh")

    try:
        state = get_faceoff_state(st.session_state.selected_game_id)
        new_count = state["total"]
        previous_count = st.session_state.previous_count

        if previous_count is not None:
            if new_count < previous_count:
                st.session_state.warning_message = (
                    f"⚠ COUNT DECREASE: {previous_count} → {new_count}"
                )
                st.session_state.warning_type = "alert"
            elif (new_count - previous_count) > 1:
                st.session_state.warning_message = (
                    f"⚠ MULTIPLE FACEOFFS ADDED: +{new_count - previous_count}"
                )
                st.session_state.warning_type = "alert"
            else:
                st.session_state.warning_message = "STATUS: OK"
                st.session_state.warning_type = "ok"
        else:
            st.session_state.warning_message = "STATUS: OK"
            st.session_state.warning_type = "ok"

        st.session_state.previous_count = new_count

        warning_box(
            st.session_state.warning_message,
            st.session_state.warning_type,
        )

        st.markdown(
            f"""
            <div style="
                font-size: 80px;
                font-weight: 800;
                margin-top: 8px;
                margin-bottom: 8px;
                line-height: 1;
            ">
                {new_count}
            </div>
            """,
            unsafe_allow_html=True,
        )

        by_period = state["by_period"]
        last_faceoff = state["last_faceoff"]

        ot_count = sum(
            count for period, count in by_period.items()
            if isinstance(period, int) and period > 3
        )

        st.markdown(
            f"""
            **Game ID:** {st.session_state.selected_game_id}  
            **P1:** {by_period.get(1, 0)} | **P2:** {by_period.get(2, 0)} | **P3:** {by_period.get(3, 0)} | **OT:** {ot_count}
            """
        )

        if last_faceoff:
            st.markdown(
                f"""
                **Last faceoff:** P{last_faceoff['period']} {last_faceoff['time_in_period']}  
                **Winner:** {last_faceoff['winner']}  
                **Event ID:** {last_faceoff['event_id']}
                """
            )
        else:
            st.markdown("**Last faceoff:** none")

        st.subheader("Audit List")

        if state["faceoffs"]:
            audit_lines = [
                f"{idx}. P{f['period']} {f['time_in_period']} | Winner: {f['winner']} | Event {f['event_id']}"
                for idx, f in enumerate(state["faceoffs"], start=1)
            ]
            st.code("\n".join(audit_lines), language=None)
        else:
            st.code("No faceoffs yet.", language=None)

    except Exception as e:
        st.error(f"Refresh error: {e}")
else:
    warning_box("STATUS: OK", "ok")
