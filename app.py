import io
import re
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image,
    KeepTogether
)

st.set_page_config(page_title="Ascent PDP Report Generator", page_icon="⚾", layout="wide")

GOLD = "#866D3B"
GREEN = "#00C781"
DARK = "#0E0E0F"
LIGHT = "#F3F3F3"

st.markdown(
    f"""
    <style>
      .stApp {{ background: #0e0e0f; color: white; }}
      [data-testid="stSidebar"] {{ background: #161617; }}
      h1,h2,h3 {{ color: white; }}
      .hero {{padding:26px 28px;border:1px solid #2b2b2d;border-radius:18px;
             background:linear-gradient(135deg,#111,#1b1b1c);margin-bottom:18px}}
      .hero small {{color:#bdbdbd;letter-spacing:.12em;text-transform:uppercase}}
      .gold {{color:{GOLD};}}
      .pill {{display:inline-block;padding:5px 10px;border-radius:999px;background:#202022;
              border:1px solid #333;margin-right:6px;font-size:.85rem}}
      div[data-testid="stMetric"] {{background:#171719;border:1px solid #2a2a2c;padding:12px;border-radius:12px}}
      .stButton>button {{border-radius:10px;font-weight:700;}}
    </style>
    """,
    unsafe_allow_html=True,
)

ALIASES = {
    "date": ["date", "test date", "session date", "sessiondate", "timestamp"],
    "athlete": ["athlete", "player", "name", "player name", "athlete name"],
    "avg_bat_speed": ["avg bat speed", "average bat speed", "bat speed", "batspeed", "avgbatspeed"],
    "time_to_contact": ["time to contact", "contact time", "ttc", "timetocontact"],
    "avg_exit_velo": ["avg exit velo", "average exit velocity", "avg exit velocity", "exit velocity", "average ev"],
    "max_exit_velo": ["max exit velo", "max exit velocity", "peak exit velo", "max ev"],
    "pitch_type": ["pitch type", "pitchtype", "tagged pitch type", "autopitchtype"],
    "velo": ["rel speed", "release speed", "velocity", "velo", "pitch velocity", "relspeed"],
    "ivb": ["induced vert break", "induced vertical break", "ivb"],
    "hb": ["horz break", "horizontal break", "hb"],
    "horz_rel": ["rel side", "horizontal release", "horz rel", "release side"],
    "vert_rel": ["rel height", "vertical release", "vert rel", "release height"],
    "spin": ["spin rate", "spinrate", "spin"],
    "extension": ["extension", "release extension"],
    "plate_x": ["plate loc side", "plate x", "platelocside", "horizontal location"],
    "plate_z": ["plate loc height", "plate z", "platelocheight", "vertical location"],
    "strike": ["strike", "is strike", "in zone", "zone", "called strike"],
    "stuff_plus": ["stuff+", "stuff plus", "stuffplus"],
}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).strip().lower()).strip()


def find_col(df, key):
    normalized = {norm(c): c for c in df.columns}
    for alias in ALIASES.get(key, []):
        a = norm(alias)
        if a in normalized:
            return normalized[a]
    # fuzzy contains fallback
    for c_norm, c in normalized.items():
        for alias in ALIASES.get(key, []):
            a = norm(alias)
            if a and (a in c_norm or c_norm in a):
                return c
    return None


def read_upload(uploaded):
    if uploaded is None:
        return None
    name = uploaded.name.lower()
    raw = uploaded.getvalue()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(raw))
        if name.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(raw))
    except Exception as e:
        st.warning(f"Could not read {uploaded.name}: {e}")
    return None


def numeric_series(df, col):
    if not col or col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce").dropna()


def infer_hitting(df):
    out = {}
    if df is None or df.empty:
        return out
    dcol = find_col(df, "date")
    if dcol:
        dts = pd.to_datetime(df[dcol], errors="coerce")
        df = df.assign(_date=dts).sort_values("_date")
    for key in ["avg_bat_speed", "time_to_contact", "avg_exit_velo", "max_exit_velo"]:
        col = find_col(df, key)
        vals = numeric_series(df, col)
        if len(vals):
            # if repeated swing-level data, split earliest/latest dates when available
            if "_date" in df.columns and df["_date"].notna().any():
                dated = df.loc[df["_date"].notna()].copy()
                first_d, last_d = dated["_date"].min(), dated["_date"].max()
                first_vals = pd.to_numeric(dated.loc[dated["_date"] == first_d, col], errors="coerce").dropna()
                last_vals = pd.to_numeric(dated.loc[dated["_date"] == last_d, col], errors="coerce").dropna()
                if len(first_vals) and len(last_vals):
                    agg = "max" if key == "max_exit_velo" else "mean"
                    out[key] = (getattr(first_vals, agg)(), getattr(last_vals, agg)())
                    out["start_date"] = first_d.date()
                    out["end_date"] = last_d.date()
                    continue
            out[key] = (float(vals.iloc[0]), float(vals.iloc[-1]))
    return out


def strike_flag(series):
    def one(v):
        if pd.isna(v): return np.nan
        if isinstance(v, (int, float, np.integer, np.floating)):
            return float(v > 0)
        s = str(v).strip().lower()
        yes = ["1", "true", "yes", "y", "strike", "in zone", "inzone", "called strike", "swinging strike"]
        no = ["0", "false", "no", "n", "ball", "out of zone", "outzone"]
        if s in yes: return 1.0
        if s in no: return 0.0
        if "strike" in s: return 1.0
        if "ball" in s: return 0.0
        return np.nan
    return series.map(one)


def summarize_trackman(df):
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    pt = find_col(df, "pitch_type")
    velo = find_col(df, "velo")
    if not pt or not velo:
        return pd.DataFrame(), pd.DataFrame()
    work = df.copy()
    work[pt] = work[pt].astype(str).str.strip()
    dcol = find_col(work, "date")
    if dcol:
        work["_date"] = pd.to_datetime(work[dcol], errors="coerce").dt.date
    else:
        work["_date"] = pd.NaT
    metric_cols = {k: find_col(work, k) for k in ["ivb", "hb", "horz_rel", "vert_rel", "spin", "extension", "stuff_plus"]}
    rows = []
    total = len(work)
    for pitch, g in work.groupby(pt, dropna=False):
        vs = pd.to_numeric(g[velo], errors="coerce").dropna()
        if not len(vs):
            continue
        row = {
            "Pitch Type": str(pitch), "Count": len(g), "Pitch %": round(100 * len(g) / total, 1),
            "Max Velo": round(vs.max(), 1), "Avg Velo": round(vs.mean(), 1),
        }
        labels = {"ivb":"IVB","hb":"HB","horz_rel":"Horz Rel","vert_rel":"Vert Rel","spin":"Spin","extension":"Extension","stuff_plus":"Stuff+"}
        for k, c in metric_cols.items():
            vals = numeric_series(g, c)
            row[labels[k]] = round(vals.mean(), 1) if len(vals) else np.nan
        rows.append(row)
    summary = pd.DataFrame(rows)

    # progression: date, fastball average velo, strike percentage
    prog_rows = []
    if "_date" in work.columns and work["_date"].notna().any():
        strike_col = find_col(work, "strike")
        plate_x, plate_z = find_col(work, "plate_x"), find_col(work, "plate_z")
        for d, g in work.dropna(subset=["_date"]).groupby("_date"):
            fb = g[g[pt].str.lower().str.contains("fast", na=False)]
            vel_vals = numeric_series(fb if len(fb) else g, velo)
            strike_pct = np.nan
            if strike_col:
                sf = strike_flag(g[strike_col]).dropna()
                if len(sf): strike_pct = sf.mean() * 100
            elif plate_x and plate_z:
                x = pd.to_numeric(g[plate_x], errors="coerce")
                z = pd.to_numeric(g[plate_z], errors="coerce")
                ok = x.notna() & z.notna()
                if ok.any():
                    # standard-ish zone approximation; editable logic later
                    strike_pct = (((x[ok].abs() <= 0.83) & (z[ok].between(1.5, 3.5))).mean() * 100)
            prog_rows.append({"Date": d, "Fastball Velo": vel_vals.mean() if len(vel_vals) else np.nan, "Strike %": strike_pct})
    return summary, pd.DataFrame(prog_rows).sort_values("Date") if prog_rows else pd.DataFrame()


def fmt_change(a, b, lower_better=False, unit=""):
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return "—"
    delta = b - a
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.2f}{unit}" if abs(delta) < 1 else f"{sign}{delta:.1f}{unit}"


def make_line_chart(df, y, title, ylabel):
    if df is None or df.empty or y not in df or df[y].dropna().empty:
        return None
    plotdf = df.dropna(subset=[y]).copy()
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.plot(pd.to_datetime(plotdf["Date"]), plotdf[y], marker="o", linewidth=2)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=.22)
    fig.autofmt_xdate(rotation=35)
    fig.tight_layout()
    bio = io.BytesIO()
    fig.savefig(bio, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    bio.seek(0)
    return bio


def generate_summary(name, metrics):
    statements = []
    labels = {
        "avg_bat_speed": ("average bat speed", " mph", False),
        "time_to_contact": ("time to contact", " sec", True),
        "avg_exit_velo": ("average exit velocity", " mph", False),
        "max_exit_velo": ("max exit velocity", " mph", False),
    }
    for k, (label, unit, lower) in labels.items():
        if k in metrics:
            a,b = metrics[k]
            delta = b-a
            improved = delta < 0 if lower else delta > 0
            if abs(delta) > 1e-9:
                direction = "improved" if improved else "changed"
                statements.append(f"{label} {direction} from {a:.2f} to {b:.2f}{unit}".replace(".00", ""))
    if not statements:
        return "Add coach notes here before exporting the final report."
    lead = f"{name} showed measurable change across the PDP testing window. "
    return lead + "; ".join(statements[:4]).capitalize() + ". Coach review is recommended before sending."


def build_pdf(name, grad_year, positions, start_date, end_date, metrics, notes, pitch_summary, progression, include_defs=True):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontSize=42, leading=46, alignment=TA_CENTER, textColor=colors.white))
    styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontSize=19, leading=24, alignment=TA_CENTER, textColor=colors.white))
    styles.add(ParagraphStyle(name="GoldH", parent=styles["Heading1"], fontSize=24, leading=28, textColor=colors.HexColor(GOLD), spaceAfter=14))
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=9.5, leading=13))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontSize=17, leading=21, textColor=colors.HexColor(GOLD), spaceBefore=8, spaceAfter=8))

    story = []

    # Cover card (dark table creates branded page without external font/assets)
    cover = Table([[Paragraph("ASCENT<br/><font size=22>ATHLETE</font>", styles["CoverTitle"])],
                   [Spacer(1, 1.2*inch)],
                   [Paragraph(name, styles["CoverSub"])],
                   [Paragraph(f"FINAL PDP REPORT &nbsp; • &nbsp; {start_date.strftime('%m/%d/%Y')} – {end_date.strftime('%m/%d/%Y')}", styles["CoverSub"])],
                   [Spacer(1, 2.5*inch)]], colWidths=[7.1*inch])
    cover.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor(DARK)),
        ("BOX",(0,0),(-1,-1),1.5,colors.HexColor(GOLD)),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),32),
        ("BOTTOMPADDING",(0,0),(-1,-1),32),
    ]))
    story += [cover, PageBreak()]

    # athlete snapshot
    story += [Paragraph("ATHLETE SNAPSHOT", styles["GoldH"])]
    meta = [["Athlete", name], ["Graduation Year", grad_year or "—"], ["Position(s)", positions or "—"], ["PDP Window", f"{start_date:%m/%d/%Y} – {end_date:%m/%d/%Y}"]]
    mt = Table(meta, colWidths=[1.75*inch, 4.8*inch], hAlign="LEFT")
    mt.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),colors.HexColor("#ECECEC")),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.6,colors.HexColor("#CCCCCC")),("PADDING",(0,0),(-1,-1),8)]))
    story += [mt, Spacer(1,18)]

    if metrics:
        story += [Paragraph("HITTING REPORT", styles["GoldH"])]
        headers = ["Metric", "Beginning", "Final", "Overall Change"]
        data = [headers]
        metric_defs = [
            ("Average Bat Speed", "avg_bat_speed", " mph", False),
            ("Time to Contact", "time_to_contact", " sec", True),
            ("Average Exit Velocity", "avg_exit_velo", " mph", False),
            ("Max Exit Velocity", "max_exit_velo", " mph", False),
        ]
        for label,k,unit,lower in metric_defs:
            if k in metrics:
                a,b = metrics[k]
                data.append([label, f"{a:.2f}{unit}".replace(".00", ""), f"{b:.2f}{unit}".replace(".00", ""), fmt_change(a,b,lower,unit)])
        ht = Table(data, colWidths=[2.0*inch,1.5*inch,1.5*inch,1.7*inch], repeatRows=1)
        ht.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor(DARK)),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.7,colors.HexColor("#BDBDBD")),
            ("ALIGN",(1,1),(-1,-1),"CENTER"),("PADDING",(0,0),(-1,-1),7),
        ]))
        story += [ht, Spacer(1,14), Paragraph("Coach Notes", styles["Section"]), Paragraph(notes or "—", styles["Small"]), PageBreak()]

    if pitch_summary is not None and not pitch_summary.empty:
        story += [Paragraph("PITCHING SUMMARY", styles["GoldH"])]
        cols = [c for c in ["Pitch Type","Count","Pitch %","Max Velo","Avg Velo","IVB","HB","Horz Rel","Vert Rel","Spin","Extension","Stuff+"] if c in pitch_summary.columns]
        pdat = [cols] + [[("—" if pd.isna(row[c]) else row[c]) for c in cols] for _,row in pitch_summary.iterrows()]
        widths = [1.0*inch] + [0.56*inch]*(len(cols)-1)
        ptbl = Table(pdat, colWidths=widths, repeatRows=1)
        ptbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor(GOLD)),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.2),
            ("GRID",(0,0),(-1,-1),.5,colors.HexColor("#BDBDBD")),("ALIGN",(1,1),(-1,-1),"CENTER"),
            ("PADDING",(0,0),(-1,-1),4),
        ]))
        story += [ptbl, Spacer(1,18)]
        if progression is not None and not progression.empty:
            c1 = make_line_chart(progression, "Fastball Velo", f"{name} – Fastball Velocity Progression", "Average Velo (mph)")
            c2 = make_line_chart(progression, "Strike %", f"{name} – Strike Percentage Progression", "Strike %")
            if c1:
                story += [Paragraph("Velocity Progression", styles["Section"]), Image(c1, width=6.6*inch, height=2.65*inch)]
            if c2:
                story += [Spacer(1,8), Paragraph("Strike Zone Progression", styles["Section"]), Image(c2, width=6.6*inch, height=2.65*inch)]
        story += [PageBreak()]

    if include_defs:
        defs = [
            ("Average Bat Speed", "How fast the barrel is traveling at contact. More bat speed can support harder contact when paired with quality swing decisions and contact."),
            ("Time to Contact", "The time from swing initiation to contact. Lower time can indicate a more efficient move to the ball and additional decision time."),
            ("Average Exit Velocity", "The average velocity of balls hit during the test. Higher averages can indicate more consistent quality contact."),
            ("Max Exit Velocity", "The hardest-hit ball of the test. This reflects top-end bat speed, contact quality, and force production."),
            ("Velocity", "How hard a pitch is thrown. Velocity is interpreted alongside movement, command, and athlete readiness."),
            ("Shapes", "How a pitch moves vertically and horizontally. Pitch shape is evaluated together with velocity and release characteristics."),
            ("Control", "How consistently pitches are located in or around the intended strike zone."),
            ("CMJ", "Countermovement jump, used to assess lower-body force and power qualities."),
            ("RSI", "Reactive Strength Index, used to assess how efficiently an athlete produces force in an explosive setting."),
            ("ISO Mid Thigh Pull", "A force-production test performed against an immovable bar to assess total force output."),
        ]
        story += [Paragraph("METRIC DEFINITIONS", styles["GoldH"])]
        for title, desc in defs:
            story += [Paragraph(f"<b>{title}:</b> {desc}", styles["Small"]), Spacer(1,7)]

    doc.build(story)
    buf.seek(0)
    return buf


def sample_trackman():
    rows = []
    rng = np.random.default_rng(7)
    sessions = [("2026-03-02",71.2,.25),("2026-03-06",68.0,.17),("2026-03-12",65.9,.40)]
    for d, fbv, strike_rate in sessions:
        for pitch, n, velo0, ivb0, hb0 in [("Fastball",7,fbv,19.8,8.4),("Slider",4,60.9,-2.0,-3.1),("ChangeUp",2,66.1,14.6,10.0)]:
            for _ in range(n):
                rows.append({
                    "Date": d, "Pitch Type": pitch, "Velocity": rng.normal(velo0,1.0),
                    "IVB": rng.normal(ivb0,1.2), "HB": rng.normal(hb0,1.0),
                    "Horz Rel": rng.normal(.9 if pitch!="Slider" else 1.6,.15), "Vert Rel": rng.normal(5.9,.12),
                    "Spin Rate": rng.normal(1773 if pitch=="Fastball" else 1550,80), "Extension": rng.normal(5.0,.12),
                    "Stuff+": rng.normal(73 if pitch=="Fastball" else 60,3), "Strike": 1 if rng.random() < strike_rate else 0,
                })
    return pd.DataFrame(rows)


# ---------------- UI ----------------
st.markdown(f"""<div class='hero'><small>Ascent Athlete • Internal Tool</small><h1>PDP Report Generator</h1>
<p>Upload athlete testing exports, review the auto-matched metrics, and generate one finished PDF.</p>
<span class='pill'>TrackMan</span><span class='pill'>Blast</span><span class='pill'>HitTrax</span><span class='pill'>Sports Performance</span></div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Athlete")
    athlete_name = st.text_input("Athlete name", "Dylan Jester")
    grad_year = st.text_input("Graduation year", "")
    positions = st.text_input("Position(s)", "")
    c1,c2 = st.columns(2)
    with c1: start_date = st.date_input("Start", date(2025,12,10))
    with c2: end_date = st.date_input("End", date(2026,3,13))
    include_defs = st.checkbox("Include definitions page", True)
    st.caption("V1 processes uploaded files in the active app session. Add a database/login later if you want athlete history.")

upload_tab, review_tab, export_tab = st.tabs(["1 · Upload Data", "2 · Review", "3 · Generate PDF"])

with upload_tab:
    st.subheader("Drop in the raw exports")
    st.write("CSV or Excel works best. The app tries to recognize common column names automatically.")
    u1,u2,u3 = st.columns(3)
    with u1:
        hitting_file = st.file_uploader("Blast / HitTrax", type=["csv","xlsx","xls"], key="hitting")
    with u2:
        trackman_file = st.file_uploader("TrackMan", type=["csv","xlsx","xls"], key="trackman")
    with u3:
        performance_file = st.file_uploader("Sports Performance", type=["csv","xlsx","xls"], key="perf")

    if st.button("Load sample athlete data"):
        st.session_state["sample_mode"] = True
        st.success("Sample data loaded. Go to Review.")

hdf = read_upload(hitting_file)
tdf = read_upload(trackman_file)
pdf_perf = read_upload(performance_file)

sample_mode = st.session_state.get("sample_mode", False)
if sample_mode and hdf is None:
    hdf = pd.DataFrame([
        {"Test Date":"2025-12-10","Avg Bat Speed":53.1,"Time to Contact":.14,"Avg Exit Velo":62.4,"Max Exit Velo":74.5},
        {"Test Date":"2026-03-13","Avg Bat Speed":57.9,"Time to Contact":.15,"Avg Exit Velo":70.0,"Max Exit Velo":80.0},
    ])
if sample_mode and tdf is None:
    tdf = sample_trackman()

inferred = infer_hitting(hdf)
pitch_summary, progression = summarize_trackman(tdf)

with review_tab:
    st.subheader("Review what the app found")
    if hdf is not None:
        with st.expander("Preview hitting source", expanded=False):
            st.dataframe(hdf.head(25), use_container_width=True)
    if tdf is not None:
        with st.expander("Preview TrackMan source", expanded=False):
            st.dataframe(tdf.head(25), use_container_width=True)

    st.markdown("### Hitting metrics")
    metric_specs = [
        ("avg_bat_speed","Average Bat Speed",53.1,57.9,.1),
        ("time_to_contact","Time to Contact",.14,.15,.01),
        ("avg_exit_velo","Average Exit Velocity",62.4,70.0,.1),
        ("max_exit_velo","Max Exit Velocity",74.5,80.0,.1),
    ]
    final_metrics = {}
    for key,label,default_a,default_b,step in metric_specs:
        ia,ib = inferred.get(key,(default_a,default_b))
        x,y = st.columns([2,2])
        with x:
            a = st.number_input(f"{label} · beginning", value=float(ia), step=step, key=f"{key}_a")
        with y:
            b = st.number_input(f"{label} · final", value=float(ib), step=step, key=f"{key}_b")
        final_metrics[key] = (a,b)

    m1,m2,m3,m4 = st.columns(4)
    metrics_cards = [
        (m1,"Bat Speed",final_metrics["avg_bat_speed"]," mph",False),
        (m2,"Time to Contact",final_metrics["time_to_contact"]," sec",True),
        (m3,"Avg Exit Velo",final_metrics["avg_exit_velo"]," mph",False),
        (m4,"Max Exit Velo",final_metrics["max_exit_velo"]," mph",False),
    ]
    for col,label,(a,b),unit,lower in metrics_cards:
        with col:
            st.metric(label, f"{b:g}{unit}", f"{(b-a):+.2f}{unit}")

    st.markdown("### Pitching")
    if pitch_summary.empty:
        st.info("No recognizable TrackMan pitch table yet. Upload the raw TrackMan CSV/Excel and V1 will attempt to map it.")
    else:
        st.dataframe(pitch_summary, use_container_width=True, hide_index=True)
        if not progression.empty:
            pc1,pc2 = st.columns(2)
            with pc1:
                p = progression.dropna(subset=["Fastball Velo"]).set_index("Date")["Fastball Velo"]
                if len(p): st.line_chart(p)
            with pc2:
                p = progression.dropna(subset=["Strike %"]).set_index("Date")["Strike %"]
                if len(p): st.line_chart(p)

    suggested = generate_summary(athlete_name, final_metrics)
    notes = st.text_area("Coach notes / athlete summary", value=suggested, height=130)
    st.session_state["final_metrics"] = final_metrics
    st.session_state["notes"] = notes
    st.session_state["pitch_summary"] = pitch_summary
    st.session_state["progression"] = progression

with export_tab:
    st.subheader("Generate the final report")
    st.write("The PDF uses the reviewed values above. You can regenerate it instantly after any change.")
    metrics_for_pdf = st.session_state.get("final_metrics", final_metrics)
    notes_for_pdf = st.session_state.get("notes", generate_summary(athlete_name, metrics_for_pdf))
    ps_for_pdf = st.session_state.get("pitch_summary", pitch_summary)
    prog_for_pdf = st.session_state.get("progression", progression)

    pdf_bytes = build_pdf(
        athlete_name, grad_year, positions, start_date, end_date,
        metrics_for_pdf, notes_for_pdf, ps_for_pdf, prog_for_pdf, include_defs
    ).getvalue()
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", athlete_name).strip("_") or "Athlete"
    fname = f"{safe}_Final_PDP_Report.pdf"
    st.download_button("⬇ Download Final PDP Report", data=pdf_bytes, file_name=fname, mime="application/pdf", use_container_width=True)
    st.success("Ready to export. Once we map your exact raw exports, the Review step can become almost completely hands-off.")
