import os
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import streamlit as st

# ─── Config ──────────────────────────────────────────────────────────────────
PG_DSN = os.getenv(
    "PG_DSN",
    "host=postgres port=5432 dbname=posture user=postgres password=postgres"
)
REFRESH_INTERVAL = 1 

# ─── Page setup ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ergonomic Posture Monitor",
    page_icon="AM",
    layout="wide",
)

# ─── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .main { background: #0d0f14; }

    .metric-card {
        background: linear-gradient(135deg, #1a1d26, #22263a);
        border: 1px solid #2e3250;
        border-radius: 16px;
        padding: 24px 20px;
        text-align: center;
        box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    }
    .metric-label {
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #7a82a6;
        margin-bottom: 8px;
    }
    .metric-value {
        font-size: 2.4rem;
        font-weight: 700;
        color: #e8eaf6;
    }
    .metric-sub {
        font-size: 0.82rem;
        color: #5c6281;
        margin-top: 4px;
    }

    .status-good  { color: #4ade80; }
    .status-bad   { color: #f87171; }
    .status-idle  { color: #facc15; }

    .section-title {
        font-size: 1.05rem;
        font-weight: 600;
        color: #8b92c4;
        letter-spacing: 0.05em;
        margin-bottom: 12px;
        text-transform: uppercase;
    }
    .header-brand {
        font-size: 1.9rem;
        font-weight: 700;
        background: linear-gradient(90deg, #818cf8, #a78bfa, #38bdf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .header-sub {
        color: #5c6281;
        font-size: 0.9rem;
        margin-top: -4px;
    }
</style>
""", unsafe_allow_html=True)


# ─── DB helpers ──────────────────────────────────────────────────────────────
@st.cache_resource
def get_conn():
    """Create a persistent DB connection (cached across reruns)."""
    retries = 20
    for _ in range(retries):
        try:
            return psycopg2.connect(PG_DSN)
        except psycopg2.OperationalError:
            time.sleep(3)
    st.error("Cannot connect to PostgreSQL. Is the DB running?")
    st.stop()


def fetch_latest(conn, limit: int = 300) -> pd.DataFrame:
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT ingested_at, posture_state, current_activity,
                       neck_angle, good_posture_percent,
                       total_tracked_seconds, total_good_posture_seconds,
                       total_bad_posture_seconds, presence
                FROM posture_events
                ORDER BY id DESC
                LIMIT {limit}
            """)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            conn.commit()
        df = pd.DataFrame(rows, columns=cols)
        df = df[::-1].reset_index(drop=True)
        return df
    except Exception:
        conn.rollback()
        return pd.DataFrame()


def fetch_summary(conn) -> dict:
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_frames,
                    MAX(total_tracked_seconds) as tracked_secs,
                    MAX(total_good_posture_seconds) as good_secs,
                    MAX(total_bad_posture_seconds) as bad_secs,
                    MAX(good_posture_percent) as good_pct
                FROM posture_events
            """)
            row = cur.fetchone()
            conn.commit()
        if row and row[0]:
            return {
                "total_frames": row[0],
                "tracked_secs": row[1] or 0,
                "good_secs"   : row[2] or 0,
                "bad_secs"    : row[3] or 0,
                "good_pct"    : row[4] or 0,
            }
    except Exception:
        conn.rollback()
    return {"total_frames": 0, "tracked_secs": 0, "good_secs": 0, "bad_secs": 0, "good_pct": 0}


# ─── Dashboard ───────────────────────────────────────────────────────────────
def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


conn = get_conn()

# Header
st.markdown('<div class="header-brand">Ergonomic Posture Monitor</div>', unsafe_allow_html=True)
st.markdown("---")

placeholder = st.empty()

while True:
    summary = fetch_summary(conn)
    df      = fetch_latest(conn, limit=300)

    with placeholder.container():
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Session Duration</div>
                <div class="metric-value">{format_duration(summary['tracked_secs'])}</div>
                <div class="metric-sub">{summary['total_frames']:,} frames processed</div>
            </div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Good Posture</div>
                <div class="metric-value status-good">{summary['good_pct']:.1f}%</div>
                <div class="metric-sub">{format_duration(summary['good_secs'])}</div>
            </div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Slouching Time</div>
                <div class="metric-value status-bad">{format_duration(summary['bad_secs'])}</div>
                <div class="metric-sub">{100 - summary['good_pct']:.1f}% of tracked time</div>
            </div>""", unsafe_allow_html=True)
        with c4:
            if not df.empty:
                last = df.iloc[-1]
                cur_posture  = last["posture_state"]
                cur_activity = last["current_activity"]
                color_cls    = "status-good" if cur_posture == "UPRIGHT" else "status-bad"
            else:
                cur_posture = "—"; cur_activity = "—"; color_cls = "status-idle"
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-label">Current Status</div>
                <div class="metric-value {color_cls}">{cur_posture}</div>
                <div class="metric-sub">{cur_activity}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("&nbsp;", unsafe_allow_html=True)

        if not df.empty:
            col_left, col_right = st.columns([3, 2])

            # ── Neck Angle Time-Series ────────────────────────────────────────
            with col_left:
                st.markdown('<div class="section-title">Neck Angle Over Time</div>', unsafe_allow_html=True)
                fig_angle = go.Figure()
                fig_angle.add_hline(
                    y=155, line_dash="dash", line_color="#4ade80",
                    annotation_text="Upright threshold", annotation_position="top left"
                )
                fig_angle.add_trace(go.Scatter(
                    x=df["ingested_at"],
                    y=df["neck_angle"],
                    mode="lines",
                    fill="tozeroy",
                    line=dict(color="#818cf8", width=2),
                    fillcolor="rgba(129, 140, 248, 0.15)",
                    name="Neck Angle (°)",
                ))
                fig_angle.update_layout(
                    paper_bgcolor="#0d0f14", plot_bgcolor="#10121a",
                    font_color="#9ca3af",
                    margin=dict(l=0, r=0, t=8, b=0),
                    height=280,
                    yaxis=dict(title="Degrees", gridcolor="#1f2937"),
                    xaxis=dict(gridcolor="#1f2937"),
                    showlegend=False,
                )
                st.plotly_chart(fig_angle, use_container_width=True)

            # ── Posture Distribution Donut ────────────────────────────────────
            with col_right:
                st.markdown('<div class="section-title">🥧 Posture Distribution</div>', unsafe_allow_html=True)
                posture_counts = df["posture_state"].value_counts().reset_index()
                posture_counts.columns = ["state", "count"]
                COLOR_MAP = {
                    "UPRIGHT"   : "#4ade80",
                    "SLOUCHING" : "#f87171",
                    "UNKNOWN"   : "#6b7280",
                }
                colors = [COLOR_MAP.get(s, "#6b7280") for s in posture_counts["state"]]
                fig_donut = go.Figure(go.Pie(
                    labels=posture_counts["state"],
                    values=posture_counts["count"],
                    hole=0.55,
                    marker_colors=colors,
                    textfont_size=13,
                ))
                fig_donut.update_layout(
                    paper_bgcolor="#0d0f14",
                    font_color="#9ca3af",
                    margin=dict(l=0, r=0, t=8, b=0),
                    height=280,
                    legend=dict(orientation="h", yanchor="bottom", y=-0.15),
                )
                st.plotly_chart(fig_donut, use_container_width=True)

            # ── Activity timeline bar ─────────────────────────────────────────
            st.markdown('<div class="section-title">🏃 Activity Timeline (last 300 frames)</div>', unsafe_allow_html=True)
            activity_counts = df["current_activity"].value_counts().reset_index()
            activity_counts.columns = ["activity", "frames"]
            ACT_COLORS = {"TYPING": "#38bdf8", "RESTING": "#a78bfa", "STRETCHING": "#fb923c", "AWAY": "#6b7280"}
            fig_act = px.bar(
                activity_counts, x="activity", y="frames",
                color="activity",
                color_discrete_map=ACT_COLORS,
            )
            fig_act.update_layout(
                paper_bgcolor="#0d0f14", plot_bgcolor="#10121a",
                font_color="#9ca3af",
                margin=dict(l=0, r=0, t=8, b=0),
                height=220,
                showlegend=False,
                xaxis=dict(title="", gridcolor="#1f2937"),
                yaxis=dict(title="Frames", gridcolor="#1f2937"),
            )
            st.plotly_chart(fig_act, use_container_width=True)

        else:
            st.info("Waiting for data from the CV pipeline… Make sure the cv-service is running.")

    time.sleep(REFRESH_INTERVAL)
    st.rerun()
