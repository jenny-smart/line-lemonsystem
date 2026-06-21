import html
from datetime import datetime
from zoneinfo import ZoneInfo

import libsql_client
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Lemon LINE 客服中心", page_icon="🍋", layout="wide")

TAIPEI = ZoneInfo("Asia/Taipei")
STATUS = ["未處理", "處理中", "待客戶回覆", "已完成"]
STAFF = ["未指派", "楊淑慧", "曾寶彤", "梁怡潔", "蔡燕萍", "蕭鵬翔", "張齊恩", "沈宛如", "陳頡維", "簡伯宏"]
AREAS = ["未填", "台北", "新北", "桃園", "新竹", "台中", "高雄", "其他"]
SERVICES = ["居家清潔", "空屋清潔", "大掃除", "裝潢細清", "辦公室清潔", "其他"]

st.markdown("""
<style>
.block-container{padding-top:1.2rem;max-width:1480px}.hero{background:linear-gradient(135deg,#fff7cc,#fff,#eef6ff);border:1px solid #f4e6a6;border-radius:22px;padding:24px 28px;margin-bottom:18px;box-shadow:0 12px 30px rgba(15,23,42,.06)}.hero h1{margin:0;font-size:34px}.hero p{margin:.4rem 0 0;color:#667085}.card{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;box-shadow:0 8px 24px rgba(15,23,42,.045)}.metric{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;min-height:112px;box-shadow:0 8px 24px rgba(15,23,42,.045)}.metric .label{font-size:13px;color:#667085}.metric .value{font-size:34px;font-weight:800;color:#111827;line-height:1.1;margin-top:8px}.metric .sub{font-size:12px;color:#667085;margin-top:8px}.title{font-size:18px;font-weight:800;margin:0 0 12px}.tag{display:inline-block;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700;margin-right:5px;background:#f3f4f6;color:#374151}.red{background:#fee2e2;color:#991b1b}.yellow{background:#fef3c7;color:#92400e}.blue{background:#dbeafe;color:#1e40af}.green{background:#dcfce7;color:#166534}.muted{color:#667085;font-size:12px}.cust{border:1px solid #e5e7eb;border-radius:14px;padding:12px;margin-bottom:10px;background:#fff}.bubble-c,.bubble-s{border-radius:16px;padding:12px 14px;line-height:1.55;margin-bottom:12px}.bubble-c{background:#f3f7ff;border:1px solid #dbeafe}.bubble-s{background:#f0fdf4;border:1px solid #bbf7d0}.meta{font-size:12px;color:#667085;margin-bottom:4px}.quick{background:#fafafa;border:1px dashed #d1d5db;border-radius:14px;padding:12px;margin-bottom:10px}section[data-testid="stSidebar"]{background:#111827}section[data-testid="stSidebar"] *{color:#f9fafb!important}
</style>
""", unsafe_allow_html=True)


def h(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return html.escape(str(x)).replace("\n", "<br>")


def metric(label, value, sub=""):
    st.markdown(f'<div class="metric"><div class="label">{h(label)}</div><div class="value">{h(value)}</div><div class="sub">{h(sub)}</div></div>', unsafe_allow_html=True)


@st.cache_resource
def get_client():
    return libsql_client.create_client_sync(
        url=st.secrets["TURSO_DATABASE_URL"].replace("libsql://", "https://"),
        auth_token=st.secrets["TURSO_AUTH_TOKEN"],
    )


def sql(q, params=None):
    return get_client().execute(q, params or [])


def table_exists(name):
    rs = sql("SELECT name FROM sqlite_master WHERE type='table' AND name=?", [name])
    return len(rs.rows) > 0


def cols(table):
    try:
        return {r[1] for r in sql(f"PRAGMA table_info({table})").rows}
    except Exception:
        return set()


def add_col(table, name, definition):
    if name not in cols(table):
        sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def ensure_schema():
    sql("""CREATE TABLE IF NOT EXISTS line_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,line_user_id TEXT NOT NULL,display_name TEXT,message_text TEXT,message_type TEXT,received_at TEXT DEFAULT (datetime('now')),handled_by TEXT,status TEXT DEFAULT '未處理',note TEXT)""")
    sql("""CREATE TABLE IF NOT EXISTS customers(line_user_id TEXT PRIMARY KEY,custom_name TEXT,phone TEXT,area TEXT,address TEXT,vip INTEGER DEFAULT 0,note TEXT,owner TEXT,updated_at TEXT DEFAULT (datetime('now')))""")
    sql("""CREATE TABLE IF NOT EXISTS replies(id INTEGER PRIMARY KEY AUTOINCREMENT,line_user_id TEXT NOT NULL,reply_text TEXT,replied_by TEXT,replied_at TEXT DEFAULT (datetime('now')))""")
    sql("""CREATE TABLE IF NOT EXISTS service_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,line_user_id TEXT NOT NULL,customer_name TEXT,phone TEXT,area TEXT,service_type TEXT,preferred_date TEXT,preferred_time TEXT,address TEXT,note TEXT,status TEXT DEFAULT '新需求',created_by TEXT,created_at TEXT DEFAULT (datetime('now')))""")
    sql("""CREATE TABLE IF NOT EXISTS quick_replies(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,title TEXT,body TEXT,updated_at TEXT DEFAULT (datetime('now')))""")
    for name, definition in {"handled_by":"TEXT", "note":"TEXT"}.items():
        add_col("line_messages", name, definition)
    for name, definition in {"phone":"TEXT", "area":"TEXT", "address":"TEXT", "vip":"INTEGER DEFAULT 0", "owner":"TEXT"}.items():
        add_col("customers", name, definition)
    if read_table("quick_replies").empty:
        seeds = [
            ("報價", "居家清潔報價", "您好，居家清潔會依坪數、清潔範圍與髒污程度報價。您可以先提供地區、坪數、想清潔的項目，我們協助您估價。"),
            ("時段", "詢問可約時段", "您好，請問您方便的日期與時段是上午、下午或晚上呢？我們會協助查詢可安排時間。"),
            ("改期", "改期說明", "可以的，請提供原訂服務日期與希望改到的時間，我們協助您確認清潔人員檔期。"),
            ("發票", "發票資訊", "可以開立電子發票，請提供統編、抬頭與收件信箱，我們會協助處理。"),
            ("VIP", "VIP 客戶回覆", "謝謝您長期支持檸檬家事，我們會協助優先確認可安排時段。"),
        ]
        for s in seeds:
            sql("INSERT INTO quick_replies(category,title,body) VALUES(?,?,?)", list(s))


@st.cache_data(ttl=30, show_spinner=False)
def read_table(name, order=""):
    if not table_exists(name):
        return pd.DataFrame()
    q = f"SELECT * FROM {name}"
    if order:
        q += f" ORDER BY {order}"
    rs = sql(q)
    return pd.DataFrame([dict(zip(rs.columns, r)) for r in rs.rows])


def to_time(df, col):
    if not df.empty and col in df.columns:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce").dt.tz_convert(TAIPEI)
    return df


def rerun():
    st.cache_data.clear()
    st.rerun()


def upsert_customer(uid, name, phone, area, address, vip, note, owner):
    sql("""INSERT INTO customers(line_user_id,custom_name,phone,area,address,vip,note,owner,updated_at) VALUES(?,?,?,?,?,?,?,?,datetime('now')) ON CONFLICT(line_user_id) DO UPDATE SET custom_name=excluded.custom_name,phone=excluded.phone,area=excluded.area,address=excluded.address,vip=excluded.vip,note=excluded.note,owner=excluded.owner,updated_at=datetime('now')""", [uid,name,phone,area,address,int(vip),note,owner])


def update_customer_messages(uid, status, staff):
    if staff != "未指派":
        sql("UPDATE line_messages SET status=?, handled_by=? WHERE line_user_id=? AND status!='已完成'", [status, staff, uid])
    else:
        sql("UPDATE line_messages SET status=? WHERE line_user_id=? AND status!='已完成'", [status, uid])


def add_reply(uid, text, by):
    sql("INSERT INTO replies(line_user_id,reply_text,replied_by,replied_at) VALUES(?,?,?,datetime('now'))", [uid, text, by])


def add_request(data):
    sql("""INSERT INTO service_requests(line_user_id,customer_name,phone,area,service_type,preferred_date,preferred_time,address,note,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""", [data[k] for k in ["uid","name","phone","area","service","date","time","address","note","status","by"]])


def save_quick(category, title, body):
    sql("INSERT INTO quick_replies(category,title,body,updated_at) VALUES(?,?,?,datetime('now'))", [category, title, body])


ensure_schema()
messages = to_time(read_table("line_messages", "received_at DESC"), "received_at")
replies = to_time(read_table("replies", "replied_at DESC"), "replied_at")
customers = read_table("customers")
requests = to_time(read_table("service_requests", "created_at DESC"), "created_at")
quick = read_table("quick_replies", "category,title")

for c in ["status", "handled_by", "note"]:
    if c not in messages.columns:
        messages[c] = ""
if not messages.empty:
    messages["status"] = messages["status"].replace("", "未處理").fillna("未處理")

customers_map = customers.set_index("line_user_id").to_dict("index") if not customers.empty else {}
today = datetime.now(TAIPEI).date()

if messages.empty:
    st.markdown('<div class="hero"><h1>🍋 Lemon LINE 客服中心</h1><p>目前還沒有任何 LINE 訊息。Webhook 收到客戶訊息後，這裡會自動開始累積客服案件。</p></div>', unsafe_allow_html=True)
    st.stop()

summary = messages.groupby("line_user_id").agg(
    display_name=("display_name", "last"),
    last_time=("received_at", "max"),
    total=("id", "count"),
    unhandled=("status", lambda s: (s == "未處理").sum()),
    processing=("status", lambda s: (s == "處理中").sum()),
    last_status=("status", "last"),
    owner=("handled_by", "last"),
).reset_index().sort_values("last_time", ascending=False)

def cname(uid):
    info = customers_map.get(uid, {})
    return info.get("custom_name") or summary.loc[summary.line_user_id==uid, "display_name"].iloc[0] or uid

def tag(status):
    cls = {"未處理":"red", "處理中":"yellow", "待客戶回覆":"blue", "已完成":"green"}.get(status, "")
    return f'<span class="tag {cls}">{h(status)}</span>'

st.sidebar.title("🍋 Lemon")
page = st.sidebar.radio("功能選單", ["今日總覽", "訊息中心", "客戶中心", "預約中心", "快捷回覆", "客服績效"], label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption("LINE Lemon System V2")

st.markdown('<div class="hero"><h1>🍋 Lemon LINE 客服中心</h1><p>客服接單、客戶 CRM、預約需求與快捷回覆整合後台</p></div>', unsafe_allow_html=True)

if page == "今日總覽":
    today_msgs = messages[messages.received_at.dt.date == today]
    overdue = summary[(summary.unhandled > 0) & (summary.last_time < pd.Timestamp(datetime.now(TAIPEI) - pd.Timedelta(minutes=30)))]
    c1,c2,c3,c4,c5 = st.columns(5)
    with c1: metric("今日新訊息", len(today_msgs), "LINE webhook 收到")
    with c2: metric("未處理", int((messages.status == "未處理").sum()), "需要客服處理")
    with c3: metric("處理中", int((messages.status == "處理中").sum()), "已有人接手")
    with c4: metric("客戶總數", messages.line_user_id.nunique(), "累積 LINE 客戶")
    with c5: metric("預約需求", len(requests), "客服建立的需求")
    st.write("")
    left,right = st.columns([1.2,1])
    with left:
        st.markdown('<div class="card"><div class="title">每日訊息量</div>', unsafe_allow_html=True)
        daily = messages.groupby(messages.received_at.dt.date).size().reset_index(name="訊息數").rename(columns={"received_at":"日期"})
        st.bar_chart(daily.set_index("日期"), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="card"><div class="title">超過 30 分鐘未處理</div>', unsafe_allow_html=True)
        if overdue.empty:
            st.success("目前沒有逾時未處理客戶")
        else:
            for _, r in overdue.head(8).iterrows():
                st.markdown(f'<div class="cust"><strong>{h(cname(r.line_user_id))}</strong><br><span class="muted">最後訊息 {r.last_time.strftime("%m/%d %H:%M")} · 未處理 {int(r.unhandled)} 則</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

elif page == "訊息中心":
    status_filter = st.selectbox("案件狀態", ["全部"] + STATUS, horizontal=False)
    table = summary.copy()
    if status_filter != "全部":
        uids = messages[messages.status == status_filter].line_user_id.unique()
        table = table[table.line_user_id.isin(uids)]
    col_a, col_b, col_c = st.columns([.95, 1.55, .9])
    with col_a:
        st.markdown('<div class="card"><div class="title">客戶列表</div>', unsafe_allow_html=True)
        selected = st.radio("客戶", table.line_user_id.tolist(), format_func=cname, label_visibility="collapsed")
        st.markdown('</div>', unsafe_allow_html=True)
    info = customers_map.get(selected, {})
    with col_b:
        st.markdown('<div class="card"><div class="title">對話紀錄</div>', unsafe_allow_html=True)
        cust_msgs = messages[messages.line_user_id == selected].copy()
        cust_msgs["who"] = "客戶"; cust_msgs["time"] = cust_msgs.received_at; cust_msgs["text"] = cust_msgs.message_text
        cust_replies = replies[replies.line_user_id == selected].copy() if not replies.empty else pd.DataFrame()
        if not cust_replies.empty:
            cust_replies["who"] = "客服"; cust_replies["time"] = cust_replies.replied_at; cust_replies["text"] = cust_replies.reply_text
        timeline = pd.concat([cust_msgs[["who","time","text","status"]], cust_replies[["who","time","text","replied_by"]] if not cust_replies.empty else pd.DataFrame()], ignore_index=True).sort_values("time")
        for _, r in timeline.iterrows():
            if r.who == "客戶":
                st.markdown(f'<div class="meta">🟢 客戶 · {r.time.strftime("%Y/%m/%d %H:%M")} · {tag(r.get("status",""))}</div><div class="bubble-c">{h(r.text)}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="meta">🔵 客服 {h(r.get("replied_by") or "")} · {r.time.strftime("%Y/%m/%d %H:%M")}</div><div class="bubble-s">{h(r.text)}</div>', unsafe_allow_html=True)
        with st.form("reply_form"):
            st.markdown("**補登客服回覆**")
            text = st.text_area("回覆內容", placeholder="貼上或輸入已在 LINE 回覆客戶的內容")
            by = st.selectbox("回覆人員", STAFF, index=0)
            if st.form_submit_button("儲存回覆紀錄", use_container_width=True):
                if text.strip():
                    add_reply(selected, text.strip(), by)
                    update_customer_messages(selected, "待客戶回覆", by)
                    rerun()
                st.warning("請輸入回覆內容")
        st.markdown('</div>', unsafe_allow_html=True)
    with col_c:
        st.markdown('<div class="card"><div class="title">客戶資料 / 案件動作</div>', unsafe_allow_html=True)
        with st.form("customer_form"):
            name = st.text_input("姓名 / 備註名稱", value=info.get("custom_name", "") or "")
            phone = st.text_input("電話", value=info.get("phone", "") or "")
            area = st.selectbox("地區", AREAS, index=AREAS.index(info.get("area")) if info.get("area") in AREAS else 0)
            address = st.text_input("地址", value=info.get("address", "") or "")
            owner = st.selectbox("負責客服", STAFF, index=STAFF.index(info.get("owner")) if info.get("owner") in STAFF else 0)
            vip = st.checkbox("VIP 客戶", value=bool(info.get("vip", 0)))
            note = st.text_area("內部備註", value=info.get("note", "") or "")
            status = st.selectbox("案件狀態", STATUS)
            if st.form_submit_button("更新客戶與狀態", use_container_width=True):
                upsert_customer(selected, name, phone, area, address, vip, note, owner)
                update_customer_messages(selected, status, owner)
                rerun()
        st.markdown('</div>', unsafe_allow_html=True)

elif page == "客戶中心":
    rows = []
    for _, r in summary.iterrows():
        info = customers_map.get(r.line_user_id, {})
        rows.append({"姓名": cname(r.line_user_id), "LINE暱稱": r.display_name, "地區": info.get("area", ""), "電話": info.get("phone", ""), "VIP": "是" if info.get("vip") else "", "訊息數": r.total, "未處理": r.unhandled, "最後訊息": r.last_time, "LINE ID": r.line_user_id})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, column_config={"最後訊息": st.column_config.DatetimeColumn(format="MM/DD HH:mm")})

elif page == "預約中心":
    left,right = st.columns([.9,1.1])
    with left:
        st.markdown('<div class="card"><div class="title">建立預約需求</div>', unsafe_allow_html=True)
        with st.form("request_form"):
            uid = st.selectbox("客戶", summary.line_user_id.tolist(), format_func=cname)
            info = customers_map.get(uid, {})
            name = st.text_input("姓名", value=info.get("custom_name") or cname(uid))
            phone = st.text_input("電話", value=info.get("phone", "") or "")
            area = st.selectbox("地區", AREAS, index=AREAS.index(info.get("area")) if info.get("area") in AREAS else 0)
            service = st.selectbox("服務類型", SERVICES)
            date = st.date_input("希望日期")
            time = st.text_input("希望時段", placeholder="上午 / 下午 / 09:00-13:00")
            address = st.text_input("地址", value=info.get("address", "") or "")
            note = st.text_area("需求備註")
            by = st.selectbox("建立人員", STAFF)
            if st.form_submit_button("建立預約需求", use_container_width=True):
                add_request({"uid":uid,"name":name,"phone":phone,"area":area,"service":service,"date":str(date),"time":time,"address":address,"note":note,"status":"新需求","by":by})
                rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="card"><div class="title">預約需求列表</div>', unsafe_allow_html=True)
        if requests.empty:
            st.info("尚無預約需求")
        else:
            show = requests.rename(columns={"customer_name":"姓名","phone":"電話","area":"地區","service_type":"服務","preferred_date":"日期","preferred_time":"時段","status":"狀態","created_by":"建立人","created_at":"建立時間"})
            st.dataframe(show[["建立時間","姓名","電話","地區","服務","日期","時段","狀態","建立人"]], use_container_width=True, hide_index=True, column_config={"建立時間": st.column_config.DatetimeColumn(format="MM/DD HH:mm")})
        st.markdown('</div>', unsafe_allow_html=True)

elif page == "快捷回覆":
    left,right = st.columns([1.1,.9])
    with left:
        st.markdown('<div class="card"><div class="title">快捷回覆庫</div>', unsafe_allow_html=True)
        for _, r in quick.iterrows():
            st.markdown(f'<div class="quick"><span class="tag blue">{h(r.get("category"))}</span><strong>{h(r.get("title"))}</strong><br><br>{h(r.get("body"))}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="card"><div class="title">新增快捷回覆</div>', unsafe_allow_html=True)
        with st.form("quick_form"):
            category = st.text_input("分類", placeholder="報價 / 時段 / 改期")
            title = st.text_input("標題")
            body = st.text_area("內容")
            if st.form_submit_button("新增", use_container_width=True):
                if title and body:
                    save_quick(category, title, body)
                    rerun()
                st.warning("請填標題與內容")
        st.markdown('</div>', unsafe_allow_html=True)

elif page == "客服績效":
    if replies.empty:
        st.info("尚無客服回覆紀錄")
    else:
        perf = replies[replies.replied_by.astype(str).str.strip() != ""].groupby("replied_by").size().reset_index(name="回覆則數").sort_values("回覆則數", ascending=False)
        st.dataframe(perf, use_container_width=True, hide_index=True)
        st.bar_chart(perf.set_index("replied_by"), use_container_width=True)
