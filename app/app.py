import streamlit as st
import boto3
import uuid
import hashlib
import random
import os
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError, NoCredentialsError
import pandas as pd
import plotly.graph_objects as go

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SWIFT GPI Tracker",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Config ─────────────────────────────────────────────────────────────────────
AWS_REGION     = os.environ.get("AWS_REGION", "us-east-1")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "GpiTrackerRequests")

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
:root{--blue:#003399;--blue2:#0052cc;--cyan:#00b4d8;--gold:#FFB300;
  --bg:#0a0e1a;--card:#0f1629;--border:#1e2d4a;--txt:#e8f0fe;--txt2:#8fa3c0;
  --green:#00C851;--amber:#FFB300;--red:#FF4444;}
.stApp{background:linear-gradient(135deg,#0a0e1a 0%,#0d1526 50%,#0a1020 100%);font-family:'Inter',sans-serif;}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#050a15 0%,#0a0e1a 100%);border-right:1px solid #1e2d4a;}
h1,h2,h3{font-family:'Inter',sans-serif;color:#e8f0fe !important;}
.hero{background:linear-gradient(135deg,#003399 0%,#0052cc 50%,#00b4d8 100%);border-radius:16px;padding:40px;margin-bottom:24px;}
.hero h1{font-size:38px;font-weight:800;color:#fff;margin:0;}
.hero p{color:rgba(255,255,255,0.8);margin-top:8px;font-size:16px;}
.kpi{background:linear-gradient(135deg,#0f1629,#111e35);border:1px solid #1e2d4a;border-radius:12px;
  padding:24px;text-align:center;position:relative;overflow:hidden;transition:all .3s;}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#003399,#00b4d8);}
.kpi:hover{border-color:#0052cc;transform:translateY(-2px);box-shadow:0 8px 32px rgba(0,51,153,.3);}
.kpi-label{color:#8fa3c0;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px;}
.kpi-value{color:#e8f0fe;font-size:36px;font-weight:800;margin:8px 0;}
.badge-acsc{background:rgba(0,200,81,.15);color:#00C851;border:1px solid rgba(0,200,81,.3);padding:3px 12px;border-radius:20px;font-size:12px;font-weight:600;}
.badge-acsp{background:rgba(255,179,0,.15);color:#FFB300;border:1px solid rgba(255,179,0,.3);padding:3px 12px;border-radius:20px;font-size:12px;font-weight:600;}
.badge-accc{background:rgba(0,179,119,.15);color:#00b377;border:1px solid rgba(0,179,119,.3);padding:3px 12px;border-radius:20px;font-size:12px;font-weight:600;}
.badge-rjct{background:rgba(255,68,68,.15);color:#FF4444;border:1px solid rgba(255,68,68,.3);padding:3px 12px;border-radius:20px;font-size:12px;font-weight:600;}
.uetr-box{font-family:'JetBrains Mono',monospace;background:rgba(0,51,153,.1);border:1px solid rgba(0,180,216,.3);
  border-radius:8px;padding:12px 16px;color:#00b4d8;font-size:14px;letter-spacing:1px;word-break:break-all;}
.card{background:#0f1629;border:1px solid #1e2d4a;border-radius:12px;padding:20px;margin-bottom:16px;}
.hop{display:flex;align-items:center;gap:8px;padding:12px 16px;background:#0f1629;border:1px solid #1e2d4a;border-radius:8px;margin-bottom:8px;}
.hop-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
.hop-info{flex:1;}
.hop-bic{color:#00b4d8;font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:500;}
.hop-name{color:#8fa3c0;font-size:12px;}
.hop-time{color:#e8f0fe;font-size:12px;}
.hop-status{font-size:11px;font-weight:600;}
.stTextInput>div>div>input,.stSelectbox>div>div{background:#0f1629 !important;border:1px solid #1e2d4a !important;color:#e8f0fe !important;border-radius:8px !important;}
.stTextInput>div>div>input[placeholder]{color:#8fa3c0 !important;}
.stButton>button{background:linear-gradient(135deg,#003399,#0052cc) !important;color:#fff !important;border:none !important;
  border-radius:8px !important;font-weight:600 !important;font-size:15px !important;padding:10px 28px !important;transition:all .3s !important;}
.stButton>button:hover{background:linear-gradient(135deg,#0052cc,#0077b6) !important;box-shadow:0 4px 20px rgba(0,51,153,.5) !important;}
.sidebar-logo{font-size:22px;font-weight:800;color:#00b4d8;letter-spacing:2px;margin-bottom:4px;}
.sidebar-sub{font-size:11px;color:#8fa3c0;letter-spacing:3px;text-transform:uppercase;}
</style>
""", unsafe_allow_html=True)

# ── Reference data ─────────────────────────────────────────────────────────────
BANKS = [
    ("CHASUS33", "JPMorgan Chase, New York"),
    ("CITIUS33", "Citibank, New York"),
    ("BOFAUS3N", "Bank of America, Charlotte"),
    ("WFBIUS6S", "Wells Fargo, San Francisco"),
    ("DEUTDEDB", "Deutsche Bank, Frankfurt"),
    ("BNPAFRPP", "BNP Paribas, Paris"),
    ("HSBCGB2L", "HSBC, London"),
    ("BARCLB22", "Barclays, London"),
    ("UBSWCHZH", "UBS, Zurich"),
    ("SCBLSGSG", "Standard Chartered, Singapore"),
    ("MUFGJPJT", "MUFG Bank, Tokyo"),
    ("RBOSGB2L", "Royal Bank of Scotland, London"),
]
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "SGD", "AED", "CNY"]
STATUSES   = ["ACSC", "ACSP", "ACCC", "RJCT"]
G_CODES    = {
    "G000": "Processed & forwarded to next GPI bank",
    "G001": "Forwarded to non-GPI member bank",
    "G002": "Settlement will not occur same business day",
    "G003": "Pending — awaiting compliance documents",
    "G004": "Pending — awaiting beneficiary clarification",
}
STATUS_LABEL = {
    "ACSC": "Settlement Completed",
    "ACCC": "Credit Confirmed",
    "ACSP": "Settlement in Progress",
    "RJCT": "Rejected",
}
STATUS_COLOR = {
    "ACSC": "#00C851", "ACCC": "#00b377", "ACSP": "#FFB300", "RJCT": "#FF4444",
}

# ── DynamoDB helpers ───────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_dynamo():
    try:
        session = boto3.Session(region_name=AWS_REGION)
        client  = session.resource("dynamodb")
        table   = client.Table(DYNAMODB_TABLE)
        table.load()
        return table
    except Exception:
        return None

def db_put(record: dict):
    table = get_dynamo()
    if table is None:
        return False
    try:
        table.put_item(Item=record)
        return True
    except ClientError:
        return False

def db_get(uetr: str):
    table = get_dynamo()
    if table is None:
        return []
    try:
        resp = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("uetr").eq(uetr)
        )
        return resp.get("Items", [])
    except ClientError:
        return []

def db_scan_recent(limit=20):
    table = get_dynamo()
    if table is None:
        return []
    try:
        resp = table.scan(Limit=limit)
        items = resp.get("Items", [])
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return items[:limit]
    except ClientError:
        return []

# ── Simulation engine ──────────────────────────────────────────────────────────
def simulate_payment(uetr: str) -> dict:
    seed = int(hashlib.md5(uetr.encode()).hexdigest(), 16)
    rng  = random.Random(seed)
    banks     = rng.sample(BANKS, k=rng.randint(2, 4))
    status    = rng.choices(STATUSES, weights=[40, 35, 15, 10])[0]
    currency  = rng.choice(CURRENCIES)
    amount    = round(rng.uniform(1_000, 5_000_000), 2)
    base_time = datetime.now(timezone.utc) - timedelta(hours=rng.randint(1, 72))
    hops = []
    for i, (bic, name) in enumerate(banks):
        hop_time = base_time + timedelta(minutes=rng.randint(2, 90) * i)
        if i < len(banks) - 1:
            hop_status, hop_gcode = "ACSP", rng.choice(list(G_CODES.keys()))
        else:
            hop_status = status
            hop_gcode  = "G000" if status != "RJCT" else "G004"
        hops.append({
            "bic":    bic,
            "name":   name,
            "time":   hop_time.strftime("%Y-%m-%d %H:%M UTC"),
            "status": hop_status,
            "gcode":  hop_gcode,
        })
    beneficiaries = [
        "Acme Corp Ltd", "Global Trade Inc", "Nexus Financial",
        "Euro Commerce GmbH", "Pacific Holdings", "Alpha Ventures",
    ]
    return {
        "uetr":             uetr,
        "sending_bic":      banks[0][0],
        "sending_name":     banks[0][1],
        "receiving_bic":    banks[-1][0],
        "receiving_name":   banks[-1][1],
        "amount":           f"{amount:,.2f}",
        "currency":         currency,
        "status":           status,
        "beneficiary_name": rng.choice(beneficiaries),
        "hops":             hops,
        "timestamp":        base_time.isoformat(),
    }

# ── Badge helper ───────────────────────────────────────────────────────────────
def badge(status: str) -> str:
    cls = f"badge-{status.lower()}"
    return f'<span class="{cls}">{status} — {STATUS_LABEL.get(status, status)}</span>'

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="sidebar-logo">⚡ SWIFT</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-sub">GPI Tracker · UETR</div>', unsafe_allow_html=True)
    st.divider()
    page = st.radio(
        "Navigation",
        ["🏠 Dashboard", "🔍 Track Payment", "➕ New Payment"],
        label_visibility="collapsed",
    )
    st.divider()
    db_ok = get_dynamo() is not None
    status_color = "🟢" if db_ok else "🟡"
    st.caption(f"{status_color} DynamoDB: {'Connected' if db_ok else 'Demo Mode'}")
    st.caption(f"Region: {AWS_REGION}")
    st.caption(f"Table:  {DYNAMODB_TABLE}")

# ── DASHBOARD ──────────────────────────────────────────────────────────────────
if page == "🏠 Dashboard":
    st.markdown("""
    <div class="hero">
      <h1>SWIFT GPI Payment Tracker</h1>
      <p>Real-time UETR tracking across the global correspondent banking network</p>
    </div>
    """, unsafe_allow_html=True)

    items = db_scan_recent(50)

    # Seed demo data if DB empty/offline
    if not items:
        demo_uetrs = [str(uuid.uuid4()) for _ in range(12)]
        items = [simulate_payment(u) for u in demo_uetrs]

    total     = len(items)
    completed = sum(1 for i in items if i.get("status") in ("ACSC", "ACCC"))
    transit   = sum(1 for i in items if i.get("status") == "ACSP")
    rejected  = sum(1 for i in items if i.get("status") == "RJCT")

    c1, c2, c3, c4 = st.columns(4)
    for col, label, val, color in [
        (c1, "Total Payments",  total,     "#00b4d8"),
        (c2, "Completed",       completed, "#00C851"),
        (c3, "In Transit",      transit,   "#FFB300"),
        (c4, "Rejected",        rejected,  "#FF4444"),
    ]:
        col.markdown(f"""
        <div class="kpi">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value" style="color:{color}">{val}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_chart, col_table = st.columns([1, 2])

    with col_chart:
        st.subheader("Status Distribution")
        labels = ["Completed", "In Transit", "Rejected"]
        values = [completed, transit, rejected]
        colors = ["#00C851", "#FFB300", "#FF4444"]
        fig = go.Figure(go.Pie(
            labels=labels, values=values,
            hole=0.6,
            marker=dict(colors=colors, line=dict(color="#0a0e1a", width=3)),
            textinfo="percent",
            hovertemplate="<b>%{label}</b><br>Count: %{value}<extra></extra>",
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#e8f0fe", family="Inter"),
            showlegend=True,
            legend=dict(font=dict(color="#8fa3c0")),
            margin=dict(t=20, b=20, l=20, r=20),
            height=280,
        )
        fig.add_annotation(text=f"<b>{total}</b><br>Total",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=18, color="#e8f0fe"))
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.subheader("Recent Payments")
        rows = []
        for item in items[:15]:
            s = item.get("status", "ACSP")
            rows.append({
                "UETR":        item.get("uetr", "")[:18] + "…",
                "Sending BIC": item.get("sending_bic", "—"),
                "Receiving":   item.get("receiving_bic", "—"),
                "Amount":      f"{item.get('currency','USD')} {item.get('amount','—')}",
                "Status":      f"{s} — {STATUS_LABEL.get(s,s)}",
                "Time":        item.get("timestamp", "")[:19].replace("T"," "),
            })
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True,
                height=300,
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="medium"),
                })

# ── TRACK PAYMENT ──────────────────────────────────────────────────────────────
elif page == "🔍 Track Payment":
    st.title("Track a Payment")
    st.caption("Enter a UETR (Unique End-to-End Transaction Reference) to view its journey")

    col_in, col_btn = st.columns([4, 1])
    with col_in:
        uetr_input = st.text_input(
            "UETR",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            label_visibility="collapsed",
        )
    with col_btn:
        track_btn = st.button("🔍 Track", use_container_width=True)

    # Quick demo button
    if st.button("⚡ Generate Demo UETR", type="secondary"):
        st.session_state["demo_uetr"] = str(uuid.uuid4())
    if "demo_uetr" in st.session_state:
        st.code(st.session_state["demo_uetr"], language=None)

    if track_btn and uetr_input:
        uetr = uetr_input.strip()
        try:
            uuid.UUID(uetr)
        except ValueError:
            st.error("❌ Invalid UETR format. Must be a valid UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)")
            st.stop()

        with st.spinner("Fetching payment status…"):
            db_items = db_get(uetr)
            payment  = db_items[0] if db_items else simulate_payment(uetr)
            if db_items:
                st.success("✅ Found in tracking database")
            else:
                st.info("ℹ️ Simulated result (UETR not in database)")

        status  = payment.get("status", "ACSP")
        hops    = payment.get("hops", [])

        # ── Header card ──────────────────────────────────────────────────────
        st.markdown(f"""
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
            <div>
              <div style="color:#8fa3c0;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;">UETR</div>
              <div class="uetr-box">{uetr}</div>
            </div>
            <div style="text-align:right">
              <div style="color:#8fa3c0;font-size:12px;margin-bottom:4px;">Current Status</div>
              {badge(status)}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Payment details ───────────────────────────────────────────────────
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("Sending Bank",   payment.get("sending_bic", "—"))
        col_b.metric("Receiving Bank", payment.get("receiving_bic", "—"))
        col_c.metric("Amount",         f"{payment.get('currency','USD')} {payment.get('amount','—')}")
        col_d.metric("Beneficiary",    payment.get("beneficiary_name", "—"))

        # ── Journey timeline ──────────────────────────────────────────────────
        st.subheader("Payment Journey")
        if not hops:
            hops = simulate_payment(uetr).get("hops", [])

        for i, hop in enumerate(hops):
            is_last = i == len(hops) - 1
            color   = STATUS_COLOR.get(hop["status"], "#8fa3c0")
            g       = G_CODES.get(hop.get("gcode","G000"), "")
            st.markdown(f"""
            <div class="hop">
              <div class="hop-dot" style="background:{color};box-shadow:0 0 8px {color};"></div>
              <div class="hop-info">
                <div class="hop-bic">{hop['bic']}</div>
                <div class="hop-name">{hop['name']}</div>
                <div style="font-size:11px;color:#8fa3c0;margin-top:2px;">{g}</div>
              </div>
              <div style="text-align:right">
                <div class="hop-time">{hop['time']}</div>
                <div class="hop-status" style="color:{color}">{hop['status']} {hop.get('gcode','')}</div>
                {"<div style='font-size:10px;color:#8fa3c0'>🏁 Final destination</div>" if is_last else ""}
              </div>
            </div>
            """, unsafe_allow_html=True)

        # ── Store lookup to DynamoDB ──────────────────────────────────────────
        if not db_items:
            record = {
                "uetr":             uetr,
                "timestamp":        datetime.now(timezone.utc).isoformat(),
                "sending_bic":      payment.get("sending_bic", ""),
                "receiving_bic":    payment.get("receiving_bic", ""),
                "amount":           str(payment.get("amount", "")),
                "currency":         payment.get("currency", ""),
                "status":           payment.get("status", ""),
                "beneficiary_name": payment.get("beneficiary_name", ""),
                "ttl":              int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp()),
            }
            db_put(record)

# ── NEW PAYMENT ────────────────────────────────────────────────────────────────
elif page == "➕ New Payment":
    st.title("Submit New Payment")
    st.caption("Create a new GPI payment tracking entry")

    with st.form("new_payment_form"):
        col1, col2 = st.columns(2)
        with col1:
            sending_bic  = st.selectbox("Sending Bank BIC",
                [f"{b[0]} — {b[1]}" for b in BANKS])
            amount       = st.number_input("Amount", min_value=0.01,
                value=10_000.00, step=100.0, format="%.2f")
            beneficiary  = st.text_input("Beneficiary Name",
                placeholder="Acme Corporation Ltd")
        with col2:
            receiving_bic = st.selectbox("Receiving Bank BIC",
                [f"{b[0]} — {b[1]}" for b in BANKS], index=4)
            currency     = st.selectbox("Currency", CURRENCIES)
            uetr_auto    = st.text_input("UETR (auto-generated)",
                value=str(uuid.uuid4()), disabled=True)

        submitted = st.form_submit_button("🚀 Submit Payment", use_container_width=True)

    if submitted:
        s_bic = sending_bic.split(" — ")[0]
        r_bic = receiving_bic.split(" — ")[0]

        if s_bic == r_bic:
            st.error("Sending and receiving banks must be different.")
        elif not beneficiary.strip():
            st.error("Beneficiary name is required.")
        else:
            record = {
                "uetr":             uetr_auto,
                "timestamp":        datetime.now(timezone.utc).isoformat(),
                "sending_bic":      s_bic,
                "receiving_bic":    r_bic,
                "amount":           f"{amount:,.2f}",
                "currency":         currency,
                "status":           "ACSP",
                "beneficiary_name": beneficiary.strip(),
                "ttl":              int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp()),
            }
            saved = db_put(record)
            st.success("✅ Payment submitted successfully!")
            st.markdown(f"""
            <div class="card">
              <div style="color:#8fa3c0;font-size:12px;margin-bottom:6px;">Generated UETR</div>
              <div class="uetr-box">{uetr_auto}</div>
              <div style="margin-top:12px;color:#e8f0fe;font-size:14px;">
                <b>{s_bic}</b> → <b>{r_bic}</b> &nbsp;|&nbsp;
                {currency} {amount:,.2f} &nbsp;|&nbsp;
                Beneficiary: <b>{beneficiary}</b>
              </div>
              <div style="margin-top:8px;">
                {badge("ACSP")}
                {"&nbsp;<span style='color:#00C851;font-size:12px'>✓ Saved to DynamoDB</span>" if saved else ""}
              </div>
            </div>
            """, unsafe_allow_html=True)
            st.info("Use the **Track Payment** page with this UETR to follow its journey.")
