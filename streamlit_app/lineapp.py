import streamlit as st
import pandas as pd
import libsql_client
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title="LINE 客服訊息紀錄", layout="wide")

# ---------- 連線 Turso ----------
@st.cache_resource
def get_client():
    return libsql_client.create_client_sync(
        url=st.secrets["TURSO_DATABASE_URL"].replace("libsql://", "https://"),
        auth_token=st.secrets["TURSO_AUTH_TOKEN"],
    )


def fetch_messages():
    client = get_client()
    rs = client.execute("SELECT * FROM line_messages ORDER BY received_at DESC")
    columns = rs.columns
    rows = [dict(zip(columns, row)) for row in rs.rows]
    return pd.DataFrame(rows)


def update_status(message_id, status, handled_by, note):
    client = get_client()
    client.execute(
        "UPDATE line_messages SET status = ?, handled_by = ?, note = ? WHERE id = ?",
        [status, handled_by, note, message_id],
    )


# ---------- 介面 ----------
st.title("📋 LINE 客服訊息紀錄系統")

df = fetch_messages()

if df.empty:
    st.info("目前還沒有任何訊息紀錄，等待客人傳訊息進來。")
    st.stop()

df["received_at"] = pd.to_datetime(df["received_at"], utc=True).dt.tz_convert("Asia/Taipei")

# ---------- 統計區 ----------
st.subheader("📊 統計總覽")
col1, col2, col3, col4 = st.columns(4)

today = datetime.now(ZoneInfo("Asia/Taipei")).date()
today_count = df[df["received_at"].dt.date == today].shape[0]
unhandled_count = df[df["status"] == "未處理"].shape[0]
unique_customers = df["line_user_id"].nunique()

col1.metric("總訊息數", len(df))
col2.metric("今日訊息數", today_count)
col3.metric("未處理訊息", unhandled_count)
col4.metric("客戶總數", unique_customers)

# 每日訊息量趨勢
daily_counts = (
    df.groupby(df["received_at"].dt.date).size().reset_index(name="訊息數")
)
daily_counts.columns = ["日期", "訊息數"]
st.bar_chart(daily_counts.set_index("日期"))

st.divider()

# ---------- 篩選區 ----------
st.subheader("🔍 訊息紀錄")
filter_col1, filter_col2, filter_col3 = st.columns(3)

with filter_col1:
    status_filter = st.selectbox("狀態篩選", ["全部", "未處理", "已處理"])
with filter_col2:
    customer_filter = st.selectbox(
        "客人篩選", ["全部"] + sorted(df["line_user_id"].unique().tolist())
    )
with filter_col3:
    days_filter = st.selectbox("時間範圍", ["全部", "今天", "近7天", "近30天"])

filtered_df = df.copy()

if status_filter != "全部":
    filtered_df = filtered_df[filtered_df["status"] == status_filter]

if customer_filter != "全部":
    filtered_df = filtered_df[filtered_df["line_user_id"] == customer_filter]

if days_filter == "今天":
    filtered_df = filtered_df[filtered_df["received_at"].dt.date == today]
elif days_filter == "近7天":
    cutoff = datetime.now(ZoneInfo("Asia/Taipei")) - timedelta(days=7)
    filtered_df = filtered_df[filtered_df["received_at"] >= cutoff]
elif days_filter == "近30天":
    cutoff = datetime.now(ZoneInfo("Asia/Taipei")) - timedelta(days=30)
    filtered_df = filtered_df[filtered_df["received_at"] >= cutoff]

st.caption(f"共 {len(filtered_df)} 筆")

# ---------- 訊息列表 + 處理狀態更新 ----------
for _, row in filtered_df.iterrows():
    with st.expander(
        f"{'🟡' if row['status'] == '未處理' else '✅'} "
        f"{row['display_name'] or row['line_user_id']} — "
        f"{row['received_at'].strftime('%Y-%m-%d %H:%M')} — "
        f"{row['message_text'][:30]}"
    ):
        st.write(f"**LINE ID：** `{row['line_user_id']}`")
        st.write(f"**訊息內容：** {row['message_text']}")
        st.write(f"**訊息類型：** {row['message_type']}")
        st.write(f"**時間：** {row['received_at']}")

        with st.form(key=f"form_{row['id']}"):
            new_status = st.selectbox(
                "處理狀態",
                ["未處理", "已處理"],
                index=0 if row["status"] == "未處理" else 1,
                key=f"status_{row['id']}",
            )
            handled_by = st.text_input(
                "處理人員", value=row["handled_by"] or "", key=f"handler_{row['id']}"
            )
            note = st.text_area(
                "備註", value=row["note"] or "", key=f"note_{row['id']}"
            )
            submitted = st.form_submit_button("更新")
            if submitted:
                update_status(row["id"], new_status, handled_by, note)
                st.success("已更新")
                st.rerun()
