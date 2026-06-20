import streamlit as st
import pandas as pd
import libsql_client
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="LINE 客服訊息紀錄", layout="wide", page_icon="💬")

TAIPEI = ZoneInfo("Asia/Taipei")

# ---------- 簡單美化 ----------
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; max-width: 1100px; }
    [data-testid="stMetric"] {
        background: #fafafa;
        border: 1px solid #eee;
        border-radius: 10px;
        padding: 14px 18px;
    }
    .chat-bubble-customer {
        background: #f0f4ff;
        border-radius: 12px;
        padding: 10px 14px;
        margin: 4px 0 12px 0;
    }
    .chat-bubble-staff {
        background: #eafaf0;
        border-radius: 12px;
        padding: 10px 14px;
        margin: 4px 0 12px 0;
    }
    .chat-meta {
        font-size: 0.8rem;
        color: #888;
        margin-bottom: 2px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- 連線 Turso ----------
@st.cache_resource
def get_client():
    return libsql_client.create_client_sync(
        url=st.secrets["TURSO_DATABASE_URL"].replace("libsql://", "https://"),
        auth_token=st.secrets["TURSO_AUTH_TOKEN"],
    )


def to_taipei(series):
    return pd.to_datetime(series, utc=True).dt.tz_convert(TAIPEI)


def fetch_messages():
    client = get_client()
    rs = client.execute("SELECT * FROM line_messages ORDER BY received_at DESC")
    rows = [dict(zip(rs.columns, row)) for row in rs.rows]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["received_at"] = to_taipei(df["received_at"])
    return df


def fetch_replies():
    client = get_client()
    rs = client.execute("SELECT * FROM replies ORDER BY replied_at DESC")
    rows = [dict(zip(rs.columns, row)) for row in rs.rows]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["replied_at"] = to_taipei(df["replied_at"])
    return df


def fetch_customers():
    client = get_client()
    rs = client.execute("SELECT * FROM customers")
    rows = [dict(zip(rs.columns, row)) for row in rs.rows]
    return pd.DataFrame(rows)


def upsert_customer(line_user_id, custom_name, note):
    client = get_client()
    client.execute(
        """
        INSERT INTO customers (line_user_id, custom_name, note, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(line_user_id) DO UPDATE SET
            custom_name = excluded.custom_name,
            note = excluded.note,
            updated_at = datetime('now')
        """,
        [line_user_id, custom_name, note],
    )


def add_reply(line_user_id, reply_text, replied_by):
    client = get_client()
    client.execute(
        "INSERT INTO replies (line_user_id, reply_text, replied_by, replied_at) VALUES (?, ?, ?, datetime('now'))",
        [line_user_id, reply_text, replied_by],
    )


def update_message_status(message_id, status):
    client = get_client()
    client.execute(
        "UPDATE line_messages SET status = ? WHERE id = ?", [status, message_id]
    )


# ---------- 載入資料 ----------
messages_df = fetch_messages()
replies_df = fetch_replies()
customers_df = fetch_customers()

st.title("💬 LINE 客服訊息紀錄系統")

if messages_df.empty:
    st.info("目前還沒有任何訊息紀錄，等待客人傳訊息進來。")
    st.stop()

customers_map = (
    customers_df.set_index("line_user_id").to_dict("index")
    if not customers_df.empty
    else {}
)
today = datetime.now(TAIPEI).date()

customer_summary = (
    messages_df.groupby("line_user_id")
    .agg(
        display_name=("display_name", "last"),
        last_time=("received_at", "max"),
        total_count=("id", "count"),
        unhandled_count=("status", lambda s: (s == "未處理").sum()),
    )
    .reset_index()
    .sort_values("last_time", ascending=False)
)
customer_summary["真實姓名/備註"] = customer_summary["line_user_id"].apply(
    lambda uid: customers_map.get(uid, {}).get("custom_name", "") or ""
)
customer_summary["回覆則數"] = customer_summary["line_user_id"].apply(
    lambda uid: int((replies_df["line_user_id"] == uid).sum()) if not replies_df.empty else 0
)


def label_for(uid):
    info = customers_map.get(uid, {})
    name = info.get("custom_name") or ""
    nickname = customer_summary.loc[
        customer_summary["line_user_id"] == uid, "display_name"
    ].values[0]
    return f"{name}（{nickname or '未知暱稱'}）" if name else (nickname or uid)


# ======================================================
# 分頁
# ======================================================
tab_overview, tab_customers, tab_detail, tab_perf = st.tabs(
    ["📊 總覽", "👥 客人列表", "🔎 對話詳情", "🏆 客服績效"]
)

# ---------- 總覽 ----------
with tab_overview:
    st.write("")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("總訊息數", len(messages_df))
    c2.metric("今日訊息數", messages_df[messages_df["received_at"].dt.date == today].shape[0])
    c3.metric("未處理訊息", messages_df[messages_df["status"] == "未處理"].shape[0])
    c4.metric("客戶總數", messages_df["line_user_id"].nunique())

    st.write("")
    st.markdown("##### 每日訊息量")
    daily = (
        messages_df.groupby(messages_df["received_at"].dt.date)
        .size()
        .reset_index(name="訊息數")
        .rename(columns={"received_at": "日期"})
    )
    st.bar_chart(daily.set_index("日期"), use_container_width=True)

# ---------- 客人列表 ----------
with tab_customers:
    st.write("")
    search = st.text_input("🔍 搜尋客人（姓名／暱稱／LINE ID）", "", label_visibility="collapsed", placeholder="🔍 搜尋客人（姓名／暱稱／LINE ID）")

    table = customer_summary.copy()
    if search:
        mask = (
            table["真實姓名/備註"].str.contains(search, case=False, na=False)
            | table["display_name"].str.contains(search, case=False, na=False)
            | table["line_user_id"].str.contains(search, case=False, na=False)
        )
        table = table[mask]

    display_table = table.rename(
        columns={
            "line_user_id": "LINE ID",
            "display_name": "LINE 暱稱",
            "last_time": "最後訊息時間",
            "total_count": "訊息數",
            "unhandled_count": "未處理數",
        }
    )[["LINE ID", "真實姓名/備註", "LINE 暱稱", "訊息數", "未處理數", "回覆則數", "最後訊息時間"]]

    st.dataframe(
        display_table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "最後訊息時間": st.column_config.DatetimeColumn(format="MM/DD HH:mm"),
        },
    )
    st.caption(f"共 {len(display_table)} 位客人。點上方「🔎 對話詳情」分頁可查看個別客人完整對話。")

# ---------- 對話詳情 ----------
with tab_detail:
    st.write("")
    selected_uid = st.selectbox(
        "選擇客人",
        options=customer_summary["line_user_id"].tolist(),
        format_func=label_for,
    )

    if selected_uid:
        info = customers_map.get(selected_uid, {})

        with st.expander("✏️ 編輯客人資料", expanded=not bool(info.get("custom_name"))):
            with st.form(key="customer_edit_form"):
                c1, c2 = st.columns(2)
                with c1:
                    custom_name = st.text_input(
                        "真實姓名 / 自訂備註名稱", value=info.get("custom_name", "") or ""
                    )
                with c2:
                    customer_note = st.text_input("客人備註", value=info.get("note", "") or "")
                if st.form_submit_button("更新"):
                    upsert_customer(selected_uid, custom_name, customer_note)
                    st.success("已更新")
                    st.rerun()

        st.caption(f"LINE ID：`{selected_uid}`")
        st.write("")

        cust_msgs = messages_df[messages_df["line_user_id"] == selected_uid].copy()
        cust_msgs["who"] = "customer"
        cust_msgs["time"] = cust_msgs["received_at"]
        cust_msgs["text"] = cust_msgs["message_text"]

        cust_replies = (
            replies_df[replies_df["line_user_id"] == selected_uid].copy()
            if not replies_df.empty
            else pd.DataFrame(columns=["line_user_id", "reply_text", "replied_by", "replied_at"])
        )
        if not cust_replies.empty:
            cust_replies["who"] = "staff"
            cust_replies["time"] = cust_replies["replied_at"]
            cust_replies["text"] = cust_replies["reply_text"]

        timeline = pd.concat(
            [
                cust_msgs[["who", "time", "text", "id", "status"]],
                cust_replies[["who", "time", "text", "replied_by"]] if not cust_replies.empty else pd.DataFrame(),
            ],
            ignore_index=True,
        ).sort_values("time")

        for _, t in timeline.iterrows():
            if t["who"] == "customer":
                st.markdown('<div class="chat-meta">🟢 客人 · ' + t["time"].strftime("%Y/%m/%d %H:%M") + "</div>", unsafe_allow_html=True)
                st.markdown(f'<div class="chat-bubble-customer">{t["text"]}</div>', unsafe_allow_html=True)
                if t.get("status") == "未處理":
                    if st.button("標記已處理", key=f"mark_{t['id']}"):
                        update_message_status(t["id"], "已處理")
                        st.rerun()
            else:
                by = t.get("replied_by") or "未填寫"
                st.markdown(f'<div class="chat-meta">🔵 客服回覆（{by}）· ' + t["time"].strftime("%Y/%m/%d %H:%M") + "</div>", unsafe_allow_html=True)
                st.markdown(f'<div class="chat-bubble-staff">{t["text"]}</div>', unsafe_allow_html=True)

        st.divider()
        st.markdown("**✍️ 補登客服回覆內容**")
        st.caption("客服已在 LINE App 上回覆後，回來這裡記錄回覆內容")
        with st.form(key="reply_form"):
            reply_text = st.text_area("回覆內容", label_visibility="collapsed", placeholder="輸入剛剛在 LINE 上回覆客人的內容...")
            replied_by = st.text_input("回覆人員", placeholder="你的名字")
            if st.form_submit_button("送出補登", use_container_width=True):
                if reply_text.strip():
                    add_reply(selected_uid, reply_text.strip(), replied_by)
                    st.success("已記錄")
                    st.rerun()
                else:
                    st.warning("請輸入回覆內容")

# ---------- 客服績效 ----------
with tab_perf:
    st.write("")

    valid_replies = (
        replies_df[replies_df["replied_by"].astype(str).str.strip() != ""]
        if not replies_df.empty
        else pd.DataFrame()
    )

    if valid_replies.empty:
        st.info("目前還沒有任何客服補登回覆紀錄。")
    else:
        st.markdown("##### 回覆次數總覽（依回覆人員）")
        reply_perf = (
            valid_replies.groupby("replied_by")
            .size()
            .reset_index(name="回覆則數")
            .sort_values("回覆則數", ascending=False)
        )
        st.dataframe(reply_perf, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("##### 查看單一客服的回覆內容明細")

        staff_options = reply_perf["replied_by"].tolist()
        selected_staff = st.selectbox("選擇客服人員", options=staff_options)

        staff_replies = valid_replies[valid_replies["replied_by"] == selected_staff].copy()

        # 加上客人姓名/暱稱，方便對照是回覆給誰
        staff_replies["客人"] = staff_replies["line_user_id"].apply(label_for)

        detail_table = staff_replies.rename(
            columns={"replied_at": "回覆時間", "reply_text": "回覆內容"}
        )[["回覆時間", "客人", "回覆內容"]].sort_values("回覆時間", ascending=False)

        st.dataframe(
            detail_table,
            use_container_width=True,
            hide_index=True,
            column_config={
                "回覆時間": st.column_config.DatetimeColumn(format="MM/DD HH:mm"),
                "回覆內容": st.column_config.TextColumn(width="large"),
            },
        )
        st.caption(f"{selected_staff} 共回覆 {len(staff_replies)} 則訊息")
