import html
from datetime import datetime
from zoneinfo import ZoneInfo

import libsql_client
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Lemon LINE 客服中心", page_icon="🍋", layout="wide")

TAIPEI = ZoneInfo("Asia/Taipei")
STATUS = ["未處理", "處理中", "待客戶回覆", "已完成"]
READ_STATUS = ["未讀", "已讀"]
STAFF = ["未指派", "楊淑慧", "曾寶彤", "梁怡潔", "蔡燕萍", "蕭鵬翔", "張齊恩", "沈宛如", "陳頡維", "簡伯宏"]
AREAS = ["未填", "台北", "新北", "桃園", "新竹", "台中", "高雄", "其他"]
SERVICES = ["居家清潔", "空屋清潔", "大掃除", "裝潢細清", "辦公室清潔", "其他"]

st.markdown("""
<style>
.block-container{padding-top:1.2rem;max-width:1480px}.hero{background:linear-gradient(135deg,#fff7cc,#fff,#eef6ff);border:1px solid #f4e6a6;border-radius:22px;padding:22px 26px;margin-bottom:14px;box-shadow:0 12px 30px rgba(15,23,42,.06)}.hero h1{margin:0;font-size:34px}.hero p{margin:.4rem 0 0;color:#667085}.card{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;box-shadow:0 8px 24px rgba(15,23,42,.045)}.metric{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:18px;min-height:108px;box-shadow:0 8px 24px rgba(15,23,42,.045)}.metric .label{font-size:13px;color:#667085}.metric .value{font-size:32px;font-weight:800;color:#111827;line-height:1.1;margin-top:8px}.metric .sub{font-size:12px;color:#667085;margin-top:8px}.title{font-size:18px;font-weight:800;margin:0 0 12px}.tag{display:inline-block;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:800;margin-right:5px;background:#f3f4f6;color:#374151}.red{background:#fee2e2;color:#991b1b}.yellow{background:#fef3c7;color:#92400e}.blue{background:#dbeafe;color:#1e40af}.green{background:#dcfce7;color:#166534}.gray{background:#f3f4f6;color:#374151}.purple{background:#ede9fe;color:#5b21b6}.muted{color:#667085;font-size:12px}.cust{border:1px solid #e5e7eb;border-radius:14px;padding:12px;margin-bottom:10px;background:#fff}.bubble-c,.bubble-s{border-radius:16px;padding:12px 14px;line-height:1.55;margin-bottom:12px}.bubble-c{background:#f3f7ff;border:1px solid #dbeafe}.bubble-s{background:#f0fdf4;border:1px solid #bbf7d0}.meta{font-size:12px;color:#667085;margin-bottom:4px}.quick{background:#fafafa;border:1px dashed #d1d5db;border-radius:14px;padding:12px;margin-bottom:10px}.stTabs [data-baseweb="tab-list"]{gap:10px}.stTabs [data-baseweb="tab"]{border:1px solid #e5e7eb;border-radius:999px;padding:8px 16px;background:#fff}.stTabs [aria-selected="true"]{background:#fff7cc!important;border-color:#facc15!important;color:#111827!important;font-weight:800}
</style>
""", unsafe_allow_html=True)


def esc(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return html.escape(str(value)).replace("\n", "<br>")


def metric(label, value, sub=""):
    st.markdown(f'<div class="metric"><div class="label">{esc(label)}</div><div class="value">{esc(value)}</div><div class="sub">{esc(sub)}</div></div>', unsafe_allow_html=True)


def status_tag(status):
    cls = {"未處理":"red", "處理中":"yellow", "待客戶回覆":"blue", "已完成":"green"}.get(str(status), "gray")
    return f'<span class="tag {cls}">{esc(status or "未處理")}</span>'


def area_tag(area):
    return f'<span class="tag purple">{esc(area or "未填")}</span>'


def read_tag(read_status):
    cls = "red" if read_status == "未讀" else "green"
    return f'<span class="tag {cls}">{esc(read_status or "未讀")}</span>'


@st.cache_resource
def get_client():
    return libsql_client.create_client_sync(
        url=st.secrets["TURSO_DATABASE_URL"].replace("libsql://", "https://"),
        auth_token=st.secrets["TURSO_AUTH_TOKEN"],
    )


def sql(query, params=None):
    return get_client().execute(query, params or [])


def table_exists(name):
    rs = sql("SELECT name FROM sqlite_master WHERE type='table' AND name=?", [name])
    return len(rs.rows) > 0


def table_cols(name):
    if not table_exists(name):
        return set()
    return {r[1] for r in sql(f"PRAGMA table_info({name})").rows}


def add_col(table, name, definition):
    if name not in table_cols(table):
        sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def read_table(name, order=""):
    if not table_exists(name):
        return pd.DataFrame()
    q = f"SELECT * FROM {name}"
    if order:
        q += f" ORDER BY {order}"
    rs = sql(q)
    return pd.DataFrame([dict(zip(rs.columns, r)) for r in rs.rows])


def ensure_schema():
    sql("""CREATE TABLE IF NOT EXISTS line_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,line_user_id TEXT NOT NULL,display_name TEXT,message_text TEXT,message_type TEXT,received_at TEXT DEFAULT (datetime('now')),handled_by TEXT,status TEXT DEFAULT '未處理',read_status TEXT DEFAULT '未讀',note TEXT)""")
    sql("""CREATE TABLE IF NOT EXISTS customers(line_user_id TEXT PRIMARY KEY,custom_name TEXT,phone TEXT,area TEXT,address TEXT,vip INTEGER DEFAULT 0,note TEXT,owner TEXT,updated_at TEXT DEFAULT (datetime('now')))""")
    sql("""CREATE TABLE IF NOT EXISTS replies(id INTEGER PRIMARY KEY AUTOINCREMENT,line_user_id TEXT NOT NULL,reply_text TEXT,replied_by TEXT,replied_at TEXT DEFAULT (datetime('now')))""")
    sql("""CREATE TABLE IF NOT EXISTS service_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,line_user_id TEXT NOT NULL,customer_name TEXT,phone TEXT,area TEXT,service_type TEXT,preferred_date TEXT,preferred_time TEXT,address TEXT,note TEXT,status TEXT DEFAULT '新需求',created_by TEXT,created_at TEXT DEFAULT (datetime('now')))""")
    sql("""CREATE TABLE IF NOT EXISTS quick_replies(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,title TEXT,body TEXT,updated_at TEXT DEFAULT (datetime('now')))""")
    add_col("line_messages", "handled_by", "TEXT")
    add_col("line_messages", "status", "TEXT DEFAULT '未處理'")
    add_col("line_messages", "read_status", "TEXT DEFAULT '未讀'")
    add_col("line_messages", "note", "TEXT")
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
        for item in seeds:
            sql("INSERT INTO quick_replies(category,title,body) VALUES(?,?,?)", list(item))


def to_taipei(df, col):
    if not df.empty and col in df.columns:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce").dt.tz_convert(TAIPEI)
    return df


def refresh():
    st.cache_data.clear()
    st.rerun()


def upsert_customer(uid, name, phone, area, address, vip, note, owner):
    sql("""INSERT INTO customers(line_user_id,custom_name,phone,area,address,vip,note,owner,updated_at) VALUES(?,?,?,?,?,?,?,?,datetime('now')) ON CONFLICT(line_user_id) DO UPDATE SET custom_name=excluded.custom_name,phone=excluded.phone,area=excluded.area,address=excluded.address,vip=excluded.vip,note=excluded.note,owner=excluded.owner,updated_at=datetime('now')""", [uid, name, phone, area, address, int(vip), note, owner])


def update_customer_status(uid, status, staff, read_status):
    sql("UPDATE line_messages SET status=?, handled_by=?, read_status=? WHERE line_user_id=?", [status, staff, read_status, uid])


def update_message_status(mid, status, read_status):
    sql("UPDATE line_messages SET status=?, read_status=? WHERE id=?", [status, read_status, mid])


def add_reply(uid, text, by):
    sql("INSERT INTO replies(line_user_id,reply_text,replied_by,replied_at) VALUES(?,?,?,datetime('now'))", [uid, text, by])


def add_request(data):
    sql("""INSERT INTO service_requests(line_user_id,customer_name,phone,area,service_type,preferred_date,preferred_time,address,note,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""", [data[k] for k in ["uid","name","phone","area","service","date","time","address","note","status","by"]])


def save_quick(category, title, body):
    sql("INSERT INTO quick_replies(category,title,body,updated_at) VALUES(?,?,?,datetime('now'))", [category, title, body])


ensure_schema()
messages = to_taipei(read_table("line_messages", "received_at DESC"), "received_at")
replies = to_taipei(read_table("replies", "replied_at DESC"), "replied_at")
customers = read_table("customers")
requests = to_taipei(read_table("service_requests", "created_at DESC"), "created_at")
quick = read_table("quick_replies", "category,title")

if messages.empty:
    st.markdown('<div class="hero"><h1>🍋 Lemon LINE 客服中心</h1><p>目前還沒有任何 LINE 訊息。</p></div>', unsafe_allow_html=True)
    st.stop()

for col, default in {"status":"未處理", "read_status":"未讀", "handled_by":"未指派", "note":""}.items():
    if col not in messages.columns:
        messages[col] = default
    messages[col] = messages[col].fillna(default).replace("", default)

customers_map = customers.set_index("line_user_id").to_dict("index") if not customers.empty else {}
today = datetime.now(TAIPEI).date()

summary = messages.groupby("line_user_id").agg(
    display_name=("display_name", "last"),
    last_time=("received_at", "max"),
    first_time=("received_at", "min"),
    total=("id", "count"),
    unread=("read_status", lambda s: (s == "未讀").sum()),
    unhandled=("status", lambda s: (s == "未處理").sum()),
    last_status=("status", "last"),
    last_read_status=("read_status", "last"),
    owner=("handled_by", "last"),
).reset_index().sort_values("last_time", ascending=False)


def customer_name(uid):
    info = customers_map.get(uid, {})
    row = summary[summary.line_user_id == uid]
    nickname = row.display_name.iloc[0] if not row.empty else uid
    return info.get("custom_name") or nickname or uid


def customer_area(uid):
    return customers_map.get(uid, {}).get("area") or "未填"


st.markdown('<div class="hero"><h1>🍋 Lemon LINE 客服中心</h1><p>LINE 客服接單、CRM、預約需求、快捷回覆整合後台</p></div>', unsafe_allow_html=True)

tab_overview, tab_inbox, tab_customers, tab_requests, tab_quick, tab_perf = st.tabs(["今日總覽", "訊息中心", "客戶中心", "預約中心", "快捷回覆", "客服績效"])

with tab_overview:
    today_msgs = messages[messages.received_at.dt.date == today]
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: metric("今日新訊息", len(today_msgs), "含文字 / 圖片 / 其他")
    with c2: metric("未讀訊息", int((messages.read_status == "未讀").sum()), "需要查看")
    with c3: metric("未處理", int((messages.status == "未處理").sum()), "尚未結案")
    with c4: metric("客戶總數", messages.line_user_id.nunique(), "LINE 使用者")
    with c5: metric("預約需求", len(requests), "客服建立")
    st.write("")
    left, right = st.columns([1.2, 1])
    with left:
        st.markdown('<div class="card"><div class="title">每日訊息量</div>', unsafe_allow_html=True)
        daily = messages.groupby(messages.received_at.dt.date).size().reset_index(name="訊息數").rename(columns={"received_at":"日期"})
        st.bar_chart(daily.set_index("日期"), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="card"><div class="title">最近訊息</div>', unsafe_allow_html=True)
        for _, r in messages.head(8).iterrows():
            info = customers_map.get(r.line_user_id, {})
            st.markdown(f'<div class="cust"><strong>{esc(customer_name(r.line_user_id))}</strong><br>{area_tag(info.get("area") or "未填")}{status_tag(r.status)}{read_tag(r.read_status)}<br><span class="muted">{r.received_at.strftime("%Y/%m/%d %H:%M")}</span><br>{esc(r.message_text)}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

with tab_inbox:
    filters = st.columns([1, 1, 1, 2])
    with filters[0]:
        status_filter = st.selectbox("處理狀態", ["全部"] + STATUS)
    with filters[1]:
        read_filter = st.selectbox("讀取狀態", ["全部"] + READ_STATUS)
    with filters[2]:
        area_filter = st.selectbox("地區", ["全部"] + AREAS)
    with filters[3]:
        keyword = st.text_input("搜尋", placeholder="姓名、LINE 暱稱、訊息內容")

    target = summary.copy()
    if status_filter != "全部":
        target = target[target.line_user_id.isin(messages[messages.status == status_filter].line_user_id.unique())]
    if read_filter != "全部":
        target = target[target.line_user_id.isin(messages[messages.read_status == read_filter].line_user_id.unique())]
    if area_filter != "全部":
        target = target[target.line_user_id.apply(customer_area) == area_filter]
    if keyword:
        matched_msg = messages[messages.message_text.astype(str).str.contains(keyword, case=False, na=False)].line_user_id.unique()
        target = target[target.line_user_id.apply(lambda x: keyword.lower() in customer_name(x).lower() or x in matched_msg)]

    col_list, col_chat, col_profile = st.columns([0.9, 1.45, 0.9])
    with col_list:
        st.markdown('<div class="card"><div class="title">客戶列表</div>', unsafe_allow_html=True)
        if target.empty:
            st.info("沒有符合條件的客戶")
            selected_uid = None
        else:
            selected_uid = st.radio("選擇客戶", target.line_user_id.tolist(), format_func=customer_name, label_visibility="collapsed")
            for _, r in target.head(12).iterrows():
                st.markdown(f'<div class="cust"><strong>{esc(customer_name(r.line_user_id))}</strong><br>{area_tag(customer_area(r.line_user_id))}{status_tag(r.last_status)}{read_tag(r.last_read_status)}<br><span class="muted">最後訊息：{r.last_time.strftime("%Y/%m/%d %H:%M")}｜未讀 {int(r.unread)}｜未處理 {int(r.unhandled)}</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    if selected_uid:
        info = customers_map.get(selected_uid, {})
        with col_chat:
            st.markdown('<div class="card"><div class="title">對話紀錄</div>', unsafe_allow_html=True)
            cust_msgs = messages[messages.line_user_id == selected_uid].copy()
            cust_msgs["who"] = "客戶"
            cust_msgs["time"] = cust_msgs.received_at
            cust_msgs["text"] = cust_msgs.message_text
            cust_replies = replies[replies.line_user_id == selected_uid].copy() if not replies.empty else pd.DataFrame()
            if not cust_replies.empty:
                cust_replies["who"] = "客服"
                cust_replies["time"] = cust_replies.replied_at
                cust_replies["text"] = cust_replies.reply_text
            timeline = pd.concat([
                cust_msgs[["who", "time", "text", "id", "status", "read_status"]],
                cust_replies[["who", "time", "text", "replied_by"]] if not cust_replies.empty else pd.DataFrame()
            ], ignore_index=True).sort_values("time")
            for _, r in timeline.iterrows():
                if r.who == "客戶":
                    st.markdown(f'<div class="meta">🟢 客戶 · {r.time.strftime("%Y/%m/%d %H:%M")} · {status_tag(r.get("status"))}{read_tag(r.get("read_status"))}</div><div class="bubble-c">{esc(r.text)}</div>', unsafe_allow_html=True)
                    cc1, cc2, cc3 = st.columns([1, 1, 4])
                    with cc1:
                        if st.button("已讀", key=f"read_{r.id}"):
                            update_message_status(r.id, r.get("status") or "未處理", "已讀")
                            refresh()
                    with cc2:
                        if st.button("完成", key=f"done_{r.id}"):
                            update_message_status(r.id, "已完成", "已讀")
                            refresh()
                else:
                    st.markdown(f'<div class="meta">🔵 客服 {esc(r.get("replied_by") or "")} · {r.time.strftime("%Y/%m/%d %H:%M")}</div><div class="bubble-s">{esc(r.text)}</div>', unsafe_allow_html=True)
            st.divider()
            with st.form("reply_form"):
                st.markdown("**補登客服回覆**")
                reply_text = st.text_area("回覆內容", placeholder="輸入已在 LINE 回覆客戶的內容")
                replied_by = st.selectbox("回覆人員", STAFF)
                if st.form_submit_button("儲存回覆並標記待客戶回覆", use_container_width=True):
                    if reply_text.strip():
                        add_reply(selected_uid, reply_text.strip(), replied_by)
                        update_customer_status(selected_uid, "待客戶回覆", replied_by, "已讀")
                        refresh()
                    st.warning("請輸入回覆內容")
            st.markdown('</div>', unsafe_allow_html=True)

        with col_profile:
            st.markdown('<div class="card"><div class="title">客戶資料與標記</div>', unsafe_allow_html=True)
            st.markdown(f'{area_tag(info.get("area") or "未填")} {status_tag(target[target.line_user_id == selected_uid].last_status.iloc[0])} {read_tag(target[target.line_user_id == selected_uid].last_read_status.iloc[0])}', unsafe_allow_html=True)
            with st.form("profile_form"):
                name = st.text_input("姓名 / 備註名稱", value=info.get("custom_name", "") or "")
                phone = st.text_input("電話", value=info.get("phone", "") or "")
                area = st.selectbox("地區", AREAS, index=AREAS.index(info.get("area")) if info.get("area") in AREAS else 0)
                address = st.text_input("地址", value=info.get("address", "") or "")
                owner = st.selectbox("負責客服", STAFF, index=STAFF.index(info.get("owner")) if info.get("owner") in STAFF else 0)
                vip = st.checkbox("VIP 客戶", value=bool(info.get("vip", 0)))
                note = st.text_area("內部備註", value=info.get("note", "") or "")
                status = st.selectbox("處理狀態", STATUS)
                read_status = st.selectbox("讀取狀態", READ_STATUS)
                if st.form_submit_button("更新標記", use_container_width=True):
                    upsert_customer(selected_uid, name, phone, area, address, vip, note, owner)
                    update_customer_status(selected_uid, status, owner, read_status)
                    refresh()
            st.markdown('</div>', unsafe_allow_html=True)

with tab_customers:
    rows = []
    for _, r in summary.iterrows():
        info = customers_map.get(r.line_user_id, {})
        rows.append({
            "訊息日期": r.last_time,
            "客戶": customer_name(r.line_user_id),
            "LINE暱稱": r.display_name,
            "地區Tag": info.get("area") or "未填",
            "處理狀態Tag": r.last_status,
            "讀取狀態": r.last_read_status,
            "電話": info.get("phone", ""),
            "訊息數": int(r.total),
            "未讀": int(r.unread),
            "未處理": int(r.unhandled),
            "LINE ID": r.line_user_id,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, column_config={"訊息日期": st.column_config.DatetimeColumn(format="YYYY/MM/DD HH:mm")})

with tab_requests:
    left, right = st.columns([0.9, 1.1])
    with left:
        st.markdown('<div class="card"><div class="title">建立預約需求</div>', unsafe_allow_html=True)
        with st.form("request_form"):
            uid = st.selectbox("客戶", summary.line_user_id.tolist(), format_func=customer_name)
            info = customers_map.get(uid, {})
            name = st.text_input("姓名", value=info.get("custom_name") or customer_name(uid))
            phone = st.text_input("電話", value=info.get("phone", "") or "")
            area = st.selectbox("地區", AREAS, index=AREAS.index(info.get("area")) if info.get("area") in AREAS else 0)
            service = st.selectbox("服務類型", SERVICES)
            date = st.date_input("希望日期")
            time = st.text_input("希望時段", placeholder="上午 / 下午 / 09:00-13:00")
            address = st.text_input("地址", value=info.get("address", "") or "")
            note = st.text_area("需求備註")
            by = st.selectbox("建立人員", STAFF)
            if st.form_submit_button("建立預約需求", use_container_width=True):
                add_request({"uid": uid, "name": name, "phone": phone, "area": area, "service": service, "date": str(date), "time": time, "address": address, "note": note, "status": "新需求", "by": by})
                refresh()
        st.markdown('</div>', unsafe_allow_html=True)
    with right:
        st.markdown('<div class="card"><div class="title">預約需求列表</div>', unsafe_allow_html=True)
        if requests.empty:
            st.info("尚無預約需求")
        else:
            show = requests.rename(columns={"customer_name":"姓名", "phone":"電話", "area":"地區", "service_type":"服務", "preferred_date":"日期", "preferred_time":"時段", "status":"狀態", "created_by":"建立人", "created_at":"建立時間"})
            st.dataframe(show[["建立時間", "姓名", "電話", "地區", "服務", "日期", "時段", "狀態", "建立人"]], use_container_width=True, hide_index=True, column_config={"建立時間": st.column_config.DatetimeColumn(format="MM/DD HH:mm")})
        st.markdown('</div>', unsafe_allow_html=True)

with tab_quick:
    left, right = st.columns([1.1, 0.9])
    with left:
        st.markdown('<div class="card"><div class="title">快捷回覆庫</div>', unsafe_allow_html=True)
        for _, r in quick.iterrows():
            st.markdown(f'<div class="quick"><span class="tag blue">{esc(r.get("category"))}</span><strong>{esc(r.get("title"))}</strong><br><br>{esc(r.get("body"))}</div>', unsafe_allow_html=True)
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
                    refresh()
                st.warning("請填標題與內容")
        st.markdown('</div>', unsafe_allow_html=True)

with tab_perf:
    if replies.empty:
        st.info("尚無客服回覆紀錄")
    else:
        perf = replies[replies.replied_by.astype(str).str.strip() != ""].groupby("replied_by").size().reset_index(name="回覆則數").sort_values("回覆則數", ascending=False)
        st.dataframe(perf, use_container_width=True, hide_index=True)
        st.bar_chart(perf.set_index("replied_by"), use_container_width=True)
