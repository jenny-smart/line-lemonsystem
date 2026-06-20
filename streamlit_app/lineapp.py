import streamlit as st
import pandas as pd
import libsql_client
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="LINE 客服訊息紀錄", layout="wide")

TAIPEI = ZoneInfo("Asia/Taipei")


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


def update_message_status(message_id, status, handled_by, note):
    client = get_client()
    client.execute(
        "UPDATE line_messages SET status = ?, handled_by = ?, note = ? WHERE id = ?",
        [status, handled_by, note, message_id],
    )


# ---------- 載入資料 ----------
st.title("📋 LINE 客服訊息紀錄系統")

messages_df = fetch_messages()
replies_df = fetch_replies()
customers_df = fetch_customers()

if messages_df.empty:
    st.info("目前還沒有任何訊息紀錄，等待客人傳訊息進來。")
    st.stop()

customers_map = (
    customers_df.set_index("line_user_id").to_dict("index")
    if not customers_df.empty
    else {}
)

today = datetime.now(TAIPEI).date()

# ======================================================
# 統計總覽
# ======================================================
col1, col2, col3, col4 = st.columns(4)
col1.metric("總訊息數", len(messages_df))
col2.metric("今日訊息數", messages_df[messages_df["received_at"].dt.date == today].shape[0])
col3.metric("未處理訊息", messages_df[messages_df["status"] == "未處理"].shape[0])
col4.metric("客戶總數", messages_df["line_user_id"].nunique())

st.divider()

# ======================================================
# 客服績效統計
# ======================================================
st.subheader("🏆 客服績效統計")

perf_col1, perf_col2 = st.columns(2)

with perf_col1:
    st.markdown("**補登回覆次數**（依回覆人員）")
    if not replies_df.empty and replies_df["replied_by"].notna().any():
        reply_perf = (
            replies_df[replies_df["replied_by"].str.strip() != ""]
            .groupby("replied_by")
            .size()
            .reset_index(name="回覆則數")
            .sort_values("回覆則數", ascending=False)
        )
        st.dataframe(reply_perf, use_container_width=True, hide_index=True)
    else:
        st.caption("尚無補登回覆紀錄")

with perf_col2:
    st.markdown("**標記已處理次數**（依處理人員）")
    handled = messages_df[
        (messages_df["status"] == "已處理") & (messages_df["handled_by"].notna())
    ]
    if not handled.empty and handled["handled_by"].str.strip().any():
        handled_perf = (
            handled[handled["handled_by"].str.strip() != ""]
            .groupby("handled_by")
            .size()
            .reset_index(name="處理則數")
            .sort_values("處理則數", ascending=False)
        )
        st.dataframe(handled_perf, use_container_width=True, hide_index=True)
    else:
        st.caption("尚無標記處理人員紀錄")

st.divider()

# ======================================================
# 客人總覽表格
# ======================================================
st.subheader("👥 客人總覽")

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
    lambda uid: (replies_df["line_user_id"] == uid).sum() if not replies_df.empty else 0
)

display_table = customer_summary.rename(
    columns={
        "line_user_id": "LINE ID",
        "display_name": "LINE 暱稱",
        "last_time": "最後訊息時間",
        "total_count": "訊息數",
        "unhandled_count": "未處理數",
    }
)[
    [
        "LINE ID",
        "真實姓名/備註",
        "LINE 暱稱",
        "訊息數",
        "未處理數",
        "回覆則數",
        "最後訊息時間",
    ]
]

st.dataframe(
    display_table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "最後訊息時間": st.column_config.DatetimeColumn(format="MM/DD HH:mm"),
    },
)

st.divider()

# ======================================================
# 選擇客人查看詳情
# ======================================================
st.subheader("🔎 查看單一客人詳情")


def label_for(uid):
    info = customers_map.get(uid, {})
    name = info.get("custom_name") or ""
    nickname = customer_summary.loc[
        customer_summary["line_user_id"] == uid, "display_name"
    ].values[0]
    if name:
        return f"{name}（{nickname or '未知暱稱'}）— {uid}"
    return f"{nickname or '未知暱稱'} — {uid}"


selected_uid = st.selectbox(
    "選擇客人",
    options=customer_summary["line_user_id"].tolist(),
    format_func=label_for,
)

if selected_uid:
    info = customers_map.get(selected_uid, {})

    with st.form(key="customer_edit_form"):
        c1, c2 = st.columns(2)
        with c1:
            custom_name = st.text_input(
                "真實姓名 / 自訂備註名稱", value=info.get("custom_name", "") or ""
            )
        with c2:
            customer_note = st.text_input(
                "客人備註", value=info.get("note", "") or ""
            )
        if st.form_submit_button("更新客人資料"):
            upsert_customer(selected_uid, custom_name, customer_note)
            st.success("已更新")
            st.rerun()

    st.caption(f"LINE ID：`{selected_uid}`")

    st.markdown("**💬 對話時間軸**")

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
        cust_replies["replied_by"] = cust_replies["replied_by"]

    timeline = pd.concat(
        [
            cust_msgs[["who", "time", "text", "id", "status"]],
            cust_replies[["who", "time", "text", "replied_by"]] if not cust_replies.empty else pd.DataFrame(),
        ],
        ignore_index=True,
    ).sort_values("time")

    for _, t in timeline.iterrows():
        if t["who"] == "customer":
            st.markdown(f"🟢 **客人** · {t['time'].strftime('%Y/%m/%d %H:%M')}")
            st.markdown(f"> {t['text']}")
            if t.get("status") == "未處理":
                if st.button("標記已處理", key=f"mark_{t['id']}"):
                    update_message_status(t["id"], "已處理", "", "")
                    st.rerun()
        else:
            by = t.get("replied_by") or "未填寫"
            st.markdown(f"🔵 **客服回覆（{by}）** · {t['time'].strftime('%Y/%m/%d %H:%M')}")
            st.markdown(f"> {t['text']}")

    st.markdown("---")
    st.markdown("**✍️ 補登客服回覆內容**（客服已在 LINE App 上回覆後，回來這裡記錄）")
    with st.form(key="reply_form"):
        reply_text = st.text_area("回覆內容")
        replied_by = st.text_input("回覆人員")
        if st.form_submit_button("送出補登"):
            if reply_text.strip():
                add_reply(selected_uid, reply_text.strip(), replied_by)
                st.success("已記錄")
                st.rerun()
            else:
                st.warning("請輸入回覆內容")
