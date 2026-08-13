
import io
import json
from datetime import date, timedelta

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage

from connectors.hawkin import HawkinConnector
from connectors.trackman import TrackManConnector
from connectors.hittrax import HitTraxConnector
from connectors.blast import BlastConnector


st.set_page_config(page_title="Ascent PDP Reports", page_icon="⚾", layout="wide")
st.title("ASCENT ATHLETE — PDP REPORTS")
st.caption("Search an athlete, choose the PDP package window, pull connected testing data, and generate the final report.")

GOLD = "#866D3B"

def secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

@st.cache_resource
def make_connectors():
    return {
        "Hawkin": HawkinConnector(
            refresh_token=secret("HAWKIN_REFRESH_TOKEN"),
            base_url=secret("HAWKIN_BASE_URL", "https://cloud.hawkindynamics.com"),
        ),
        "TrackMan": TrackManConnector(
            token_url=secret("TRACKMAN_TOKEN_URL"),
            data_url=secret("TRACKMAN_DATA_URL"),
            client_id=secret("TRACKMAN_CLIENT_ID"),
            client_secret=secret("TRACKMAN_CLIENT_SECRET"),
            username=secret("TRACKMAN_USERNAME"),
            password=secret("TRACKMAN_PASSWORD"),
        ),
        "HitTrax": HitTraxConnector(
            api_base=secret("HITTRAX_API_BASE"),
            api_key=secret("HITTRAX_API_KEY"),
        ),
        "Blast": BlastConnector(
            api_base=secret("BLAST_API_BASE"),
            api_key=secret("BLAST_API_KEY"),
        ),
    }

connectors = make_connectors()

def make_chart(title, beginning, final, ylabel):
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar(["Beginning", "Final"], [beginning, final])
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf

def build_pdf(name, start_date, end_date, metrics, summary, sources):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    gold = colors.HexColor(GOLD)

    title = ParagraphStyle("title", parent=styles["Title"], fontName="Helvetica-Bold",
                           fontSize=22, leading=26, textColor=colors.HexColor("#111111"), spaceAfter=8)
    heading = ParagraphStyle("heading", parent=styles["Heading2"], fontName="Helvetica-Bold",
                             fontSize=14, textColor=gold, spaceBefore=10, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=10.5, leading=14)

    story = [
        Paragraph("ASCENT ATHLETE", title),
        Paragraph("FINAL PDP REPORT", title),
        Spacer(1, 0.1 * inch),
        Paragraph(name.upper(), ParagraphStyle("athlete", parent=title, textColor=gold)),
        Paragraph(f"{start_date.strftime('%b %d, %Y')} — {end_date.strftime('%b %d, %Y')}", body),
        Spacer(1, 0.25 * inch),
        Paragraph("PROGRAM SUMMARY", heading),
        Paragraph(summary, body),
        Spacer(1, 0.2 * inch),
        Paragraph("DATA SOURCES", heading),
        Paragraph(", ".join(sources) if sources else "Manual review", body),
        Spacer(1, 0.25 * inch),
        Paragraph("TESTING RESULTS", heading),
    ]

    rows = [["Metric", "Beginning", "Final", "Change"]]
    for metric in metrics:
        if metric["beginning"] is None or metric["final"] is None:
            continue
        b, f = metric["beginning"], metric["final"]
        d = f - b
        suffix = metric.get("suffix", "")
        decimals = metric.get("decimals", 1)
        sign = "+" if d > 0 else ""
        rows.append([
            metric["label"],
            f"{b:.{decimals}f}{suffix}",
            f"{f:.{decimals}f}{suffix}",
            f"{sign}{d:.{decimals}f}{suffix}",
        ])

    if len(rows) == 1:
        rows.append(["No mapped metrics yet", "—", "—", "—"])

    table = Table(rows, colWidths=[2.2*inch, 1.2*inch, 1.2*inch, 1.4*inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), gold),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#D8D8D8")),
        ("ALIGN", (1,0), (-1,-1), "CENTER"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("TOPPADDING", (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
    ]))
    story.append(table)

    chart_candidates = [m for m in metrics if m["beginning"] is not None and m["final"] is not None][:2]
    if chart_candidates:
        story += [Spacer(1, .3*inch), Paragraph("PROGRESSION", heading)]
        for m in chart_candidates:
            chart = make_chart(m["label"], m["beginning"], m["final"], m.get("suffix","").strip())
            story.append(RLImage(chart, width=6.2*inch, height=3.1*inch))
            story.append(Spacer(1, .1*inch))

    story += [
        Spacer(1, .2*inch),
        Paragraph("COACH REVIEW", heading),
        Paragraph("Review automatically populated metrics before sending the final athlete report.", body)
    ]
    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


# ------------------------
# Connection status
# ------------------------
st.subheader("Connections")
status_cols = st.columns(4)
for col, (name, conn) in zip(status_cols, connectors.items()):
    with col:
        connected, detail = conn.configured()
        st.metric(name, "Ready" if connected else "Needs access")
        st.caption(detail)

st.divider()

# ------------------------
# Athlete / package
# ------------------------
left, right = st.columns([2,1])
with left:
    athlete_query = st.text_input("Athlete name", placeholder="Search athlete name")
with right:
    package_weeks = st.selectbox("PDP package length", [4, 6, 8, 10, 12, 16], index=2)

end_date = st.date_input("Package end date", date.today())
start_date = end_date - timedelta(weeks=int(package_weeks))
st.caption(f"Package window: {start_date.strftime('%b %d, %Y')} → {end_date.strftime('%b %d, %Y')}")

if "pulled" not in st.session_state:
    st.session_state.pulled = None

if st.button("PULL ATHLETE DATA", type="primary", use_container_width=True):
    if not athlete_query.strip():
        st.error("Enter an athlete name first.")
    else:
        bundle = {"athlete": athlete_query.strip(), "sources": {}, "errors": []}
        for name, conn in connectors.items():
            configured, _ = conn.configured()
            if not configured:
                continue
            try:
                bundle["sources"][name] = conn.fetch_athlete_window(
                    athlete_query.strip(), start_date, end_date
                )
            except Exception as exc:
                bundle["errors"].append(f"{name}: {exc}")
        st.session_state.pulled = bundle

bundle = st.session_state.pulled

if bundle:
    for err in bundle["errors"]:
        st.warning(err)

    st.subheader("Matched Data")
    source_tabs = st.tabs(list(bundle["sources"].keys()) or ["No connected sources"])
    if bundle["sources"]:
        for tab, (source_name, payload) in zip(source_tabs, bundle["sources"].items()):
            with tab:
                st.success(f"{source_name} data pulled")
                st.json(payload, expanded=False)
    else:
        with source_tabs[0]:
            st.info("No live sources are configured yet. Add credentials in Streamlit Secrets.")

    # Build common metric structure from normalized connector outputs
    normalized = {}
    sources_used = []
    for source_name, payload in bundle["sources"].items():
        sources_used.append(source_name)
        for key, value in payload.get("metrics", {}).items():
            normalized[key] = value

    metric_defs = [
        ("Bat Speed", "bat_speed", " mph", 1),
        ("Exit Velocity", "exit_velocity", " mph", 1),
        ("Time to Contact", "time_to_contact", " sec", 2),
        ("Throwing Velocity", "pitch_velocity", " mph", 1),
        ("Strike %", "strike_pct", "%", 1),
        ("Peak Propulsion Force", "peak_propulsion_force", "", 0),
        ("Jump Height", "jump_height", " m", 3),
    ]

    rows = []
    for label, key, suffix, decimals in metric_defs:
        pair = normalized.get(key, {})
        rows.append({
            "label": label,
            "beginning": pair.get("beginning"),
            "final": pair.get("final"),
            "suffix": suffix,
            "decimals": decimals,
        })

    st.subheader("Report Metrics")
    df = pd.DataFrame([
        {
            "Metric": r["label"],
            "Beginning": r["beginning"],
            "Final": r["final"],
            "Change": None if r["beginning"] is None or r["final"] is None else r["final"] - r["beginning"],
        }
        for r in rows
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    improvements = []
    for r in rows:
        if r["beginning"] is not None and r["final"] is not None:
            d = r["final"] - r["beginning"]
            if r["label"] == "Time to Contact":
                if d < 0:
                    improvements.append(f"{r['label']} improved by {abs(d):.{r['decimals']}f}{r['suffix']}")
            elif d > 0:
                improvements.append(f"{r['label']} improved by {d:.{r['decimals']}f}{r['suffix']}")
    summary_default = (
        f"{bundle['athlete']} completed a {package_weeks}-week PDP package. "
        + ("; ".join(improvements) + "." if improvements else "Review the connected testing data below for beginning-to-final changes.")
    )
    summary = st.text_area("Coach summary", summary_default, height=120)

    pdf = build_pdf(bundle["athlete"], start_date, end_date, rows, summary, sources_used)
    filename = "_".join(bundle["athlete"].split()) + "_Final_PDP_Report.pdf"
    st.download_button(
        "GENERATE / DOWNLOAD FINAL PDP REPORT",
        data=pdf,
        file_name=filename,
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )

st.divider()
with st.expander("Admin setup — what credentials are still needed?"):
    st.markdown("""
**Hawkin Dynamics:** add the organization refresh token in Streamlit Secrets.

**TrackMan:** add the credentials and production API URLs supplied by TrackMan after Data API access is enabled.

**HitTrax:** add an API base URL and API key if HitTrax grants your facility programmatic access.

**Blast Motion:** add an API base URL and API key if Blast grants your facility programmatic access.

Do not put passwords or API keys directly in GitHub.
""")
