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


def get_display_label(line_user_id, fallback_name):
    info = customers_map.get(line_user_id)
    if info and info.get("custom_name"):
        return f"{info['custom_name']}（{fallback_name or '未知暱稱'}）"
    return fallback_name or line_user_id


# ---------- 統計總覽 ----------
today = datetime.now(TAIPEI).date()
col1, col2, col3, col4 = st.columns(4)
col1.metric("總訊息數", len(messages_df))
col2.metric("今日訊息數", messages_df[messages_df["received_at"].dt.date == today].shape[0])
col3.metric("未處理訊息", messages_df[messages_df["status"] == "未處理"].shape[0])
col4.metric("客戶總數", messages_df["line_user_id"].nunique())

st.divider()

# ---------- 客人列表 ----------
st.subheader("👥 客人列表")

customer_summary = (
    messages_df.groupby("line_user_id")
    .agg(
        display_name=("display_name", "last"),
        last_message=("message_text", "first"),
        last_time=("received_at", "max"),
        total_count=("id", "count"),
        unhandled_count=("status", lambda s: (s == "未處理").sum()),
    )
    .reset_index()
    .sort_values("last_time", ascending=False)
)

search = st.text_input("🔍 搜尋客人（姓名 / 暱稱 / LINE ID）", "")

for _, row in customer_summary.iterrows():
    label = get_display_label(row["line_user_id"], row["display_name"])

    if (
        search
        and search.lower() not in label.lower()
        and search.lower() not in row["line_user_id"].lower()
    ):
        continue

    badge = (
        f"🟡 {row['unhandled_count']} 則未處理"
        if row["unhandled_count"] > 0
        else "✅ 已全部處理"
    )

    with st.expander(
        f"**{label}** — 共 {row['total_count']} 則訊息 — {badge} — "
        f"最後訊息：{row['last_time'].strftime('%Y-%m-%d %H:%M')}"
    ):
        line_user_id = row["line_user_id"]
        info = customers_map.get(line_user_id, {})

        # 客人資料標註
        with st.form(key=f"customer_form_{line_user_id}"):
            c1, c2 = st.columns(2)
            with c1:
                custom_name = st.text_input(
                    "真實姓名 / 自訂備註名稱",
                    value=info.get("custom_name", "") or "",
                    key=f"name_{line_user_id}",
                )
            with c2:
                customer_note = st.text_input(
                    "客人備註（例如：常住信義區、偏好早上聯絡）",
                    value=info.get("note", "") or "",
                    key=f"cnote_{line_user_id}",
                )
            if st.form_submit_button("更新客人資料"):
                upsert_customer(line_user_id, custom_name, customer_note)
                st.success("已更新")
                st.rerun()

        st.caption(f"LINE ID：`{line_user_id}`")

        st.markdown("---")
        st.markdown("**💬 對話時間軸**")

        cust_msgs = messages_df[messages_df["line_user_id"] == line_user_id].copy()
        cust_msgs["who"] = "customer"
        cust_msgs["time"] = cust_msgs["received_at"]
        cust_msgs["text"] = cust_msgs["message_text"]

        cust_replies = (
            replies_df[replies_df["line_user_id"] == line_user_id].copy()
            if not replies_df.empty
            else pd.DataFrame(columns=["line_user_id", "reply_text", "replied_by", "replied_at"])
        )
        if not cust_replies.empty:
            cust_replies["who"] = "staff"
            cust_replies["time"] = cust_replies["replied_at"]
            cust_replies["text"] = cust_replies["reply_text"]

        timeline = pd.concat(
            [
                cust_msgs[["who", "time", "text", "id", "status", "handled_by", "note"]],
                cust_replies[["who", "time", "text"]] if not cust_replies.empty else pd.DataFrame(),
            ],
            ignore_index=True,
        ).sort_values("time")

        for _, t in timeline.iterrows():
            if t["who"] == "customer":
                st.markdown(f"🟢 **客人** · {t['time'].strftime('%m/%d %H:%M')}")
                st.markdown(f"> {t['text']}")
                if t.get("status") == "未處理":
                    if st.button("標記已處理", key=f"mark_{t['id']}"):
                        update_message_status(t["id"], "已處理", "", t.get("note", "") or "")
                        st.rerun()
            else:
                st.markdown(f"🔵 **客服回覆** · {t['time'].strftime('%m/%d %H:%M')}")
                st.markdown(f"> {t['text']}")

        st.markdown("---")
        st.markdown("**✍️ 補登客服回覆內容**（客服已在 LINE App 上回覆後，回來這裡記錄）")
        with st.form(key=f"reply_form_{line_user_id}"):
            reply_text = st.text_area("回覆內容", key=f"reply_text_{line_user_id}")
            replied_by = st.text_input("回覆人員", key=f"reply_by_{line_user_id}")
            if st.form_submit_button("送出補登"):
                if reply_text.strip():
                    add_reply(line_user_id, reply_text.strip(), replied_by)
                    st.success("已記錄")
                    st.rerun()
                else:
                    st.warning("請輸入回覆內容")
