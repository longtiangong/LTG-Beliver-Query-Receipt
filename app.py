import datetime
import requests
import pandas as pd
import streamlit as st

# 頁面基本設定
st.set_page_config(
    page_title="龍天宮信徒查詢及收據系統", page_icon="⛩️", layout="wide"
)

# -----------------------------------------------------------------------------
# 1. 第一重密碼驗證（開啟 App 存取控管）
# -----------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("⛩️ 龍天宮管理系統 - 登入")
    pwd_input = st.text_input("請輸入系統開啟密碼", type="password")
    if st.button("確認登入"):
        if pwd_input == st.secrets.get("SYSTEM_PASSWORD", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("密碼不正確，請重新輸入。")
    st.stop()


# -----------------------------------------------------------------------------
# 2. API Helper Function (存取 Google Apps Script)
# -----------------------------------------------------------------------------
GAS_URL = st.secrets.get("GAS_URL", "")


@st.cache_data(ttl=60)
def fetch_believer_data():
    """從 Google Sheet 抓取信徒資料"""
    if not GAS_URL:
        return pd.DataFrame()
    try:
        res = requests.get(GAS_URL, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return pd.DataFrame(data)
        else:
            st.error(f"無法讀取 Google Sheet 資料，HTTP 狀態碼：{res.status_code}")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"讀取 Google Sheet 發生錯誤: {e}")
        return pd.DataFrame()


def save_believer_data(payload):
    """將新信徒資料發送至 Google Sheet"""
    if not GAS_URL:
        st.error("未設定 GAS_URL")
        return False
    try:
        res = requests.post(GAS_URL, json=payload, timeout=10)
        if res.status_code == 200 and res.json().get("status") == "success":
            st.cache_data.clear()  # 清除快取以刷新資料
            return True
        else:
            st.error(f"寫入失敗：{res.text}")
            return False
    except Exception as e:
        st.error(f"寫入發生例外狀況: {e}")
        return False


# -----------------------------------------------------------------------------
# 3. 右側/側邊欄選單
# -----------------------------------------------------------------------------
st.sidebar.title("⛩️ 龍天宮系統選單")
menu_option = st.sidebar.radio(
    "請選擇功能：", ["一、信徒資料查詢", "二、各類收據開立"]
)

if st.sidebar.button("登出系統"):
    st.session_state.authenticated = False
    st.rerun()

# -----------------------------------------------------------------------------
# 功能一：信徒資料查詢
# -----------------------------------------------------------------------------
if menu_option == "一、信徒資料查詢":
    st.header("🔍 信徒資料查詢與新增")

    search_name = st.text_input("請輸入信徒姓名進行查詢：").strip()

    if "data_unlocked" not in st.session_state:
        st.session_state.data_unlocked = False

    if search_name:
        df = fetch_believer_data()

        # 第二重密碼檢核（保護調閱資料安全）
        if not st.session_state.data_unlocked:
            st.warning("⚠️ 檢閱詳細信徒資料需要輸入第二重密碼")
            sec_pwd = st.text_input(
                "請輸入第二重解鎖密碼：", type="password", key="sec_pwd_input"
            )
            if st.button("驗證密碼並解鎖資料"):
                if sec_pwd == st.secrets.get("DATA_PASSWORD", ""):
                    st.session_state.data_unlocked = True
                    st.success("解鎖成功！")
                    st.rerun()
                else:
                    st.error("第二重密碼錯誤！")
            st.stop()

        # 搜尋符合特姓名之資料
        if not df.empty and "姓名" in df.columns:
            matched_df = df[
                df["姓名"].astype(str).str.strip() == search_name
            ]
        else:
            matched_df = pd.DataFrame()

        # 查有資料 (顯示同名同姓的所有筆數)
        if not matched_df.empty:
            count = len(matched_df)
            st.success(f"共找到 {count} 位名為「{search_name}」的信徒資料：")

            # 定義主要欄位順序以確保顯示穩定
            expected_cols = [
                "姓名",
                "稱謂",
                "生辰年月日",
                "時辰",
                "地址",
                "手機",
                "2026丁口",
                "2026光明燈",
                "2026太歲",
            ]
            display_cols = [c for c in expected_cols if c in matched_df.columns]
            other_cols = [
                c for c in matched_df.columns if c not in expected_cols
            ]
            matched_df = matched_df[display_cols + other_cols]

            for idx, row in matched_df.iterrows():
                with st.expander(
                    f"👤 信徒：{row.get('姓名', '')} ({row.get('稱謂', '信士/女')}) - 手機：{row.get('手機', '無')}",
                    expanded=True,
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.markdown(f"**稱謂：** {row.get('稱謂', '')}")
                    c1.markdown(f"**生辰年月日：** {row.get('生辰年月日', '')}")
                    c1.markdown(f"**時辰：** {row.get('時辰', '')}")

                    c2.markdown(f"**手機：** {row.get('手機', '')}")
                    c2.markdown(f"**地址：** {row.get('地址', '')}")

                    c3.markdown(f"**2026丁口：** {row.get('2026丁口', '')}")
                    c3.markdown(f"**2026光明燈：** {row.get('2026光明燈', '')}")
                    c3.markdown(f"**2026太歲：** {row.get('2026太歲', '')}")

        else:
            st.info(f"查無姓名為「{search_name}」的信徒資料，可於下方手動輸入新增：")

            with st.form("add_believer_form"):
                st.subheader("➕ 手動新增信徒資料")
                col1, col2 = st.columns(2)

                name_input = col1.text_input("姓名", value=search_name)
                gender_title = col2.selectbox(
                    "稱謂", ["信士", "信女", "乾造", "坤造"]
                )

                birth_date = col1.text_input("生辰年月日", placeholder="例：農曆68年3月15日 或 1979-04-11")
                birth_time = col2.text_input("時辰", placeholder="例：吉時、子時(23-01)")

                phone = col1.text_input("手機")
                address = col2.text_input("地址")

                st.markdown("---")
                col3, col4, col5 = st.columns(3)
                dinkou_2026 = col3.text_input("2026丁口")
                guangming_2026 = col4.text_input("2026光明燈")
                taisui_2026 = col5.text_input("2026太歲")

                submit_btn = st.form_submit_button("新增並存入 Google Sheet")

                if submit_btn:
                    if not name_input:
                        st.error("姓名為必填欄位！")
                    else:
                        payload = {
                            "姓名": name_input,
                            "稱謂": gender_title,
                            "生辰年月日": birth_date,
                            "時辰": birth_time,
                            "地址": address,
                            "手機": phone,
                            "2026丁口": dinkou_2026,
                            "2026光明燈": guangming_2026,
                            "2026太歲": taisui_2026,
                        }
                        if save_believer_data(payload):
                            st.success("成功新增資料至 Google Sheet！")
                            st.rerun()

# -----------------------------------------------------------------------------
# 功能二：各類收據開立
# -----------------------------------------------------------------------------
elif menu_option == "二、各類收據開立":
    st.header("🧾 各類收據與收執聯開立")

    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.subheader("1. 輸入收據資料")
        r_name = st.text_input("信徒姓名")
        r_address = st.text_input("地址")

        receipt_type = st.selectbox(
            "選擇種類選項",
            [
                "1. 祭改",
                "2. 光明燈",
                "3. 太歲",
                "4. 年斗",
                "5. 補運",
                "6. 補財庫",
                "7. 進香",
                "8. 添油香",
                "9. 其他",
            ],
        )

        sub_option = ""
        if receipt_type in ["5. 補運", "6. 補財庫"]:
            sub_option = st.radio("選擇月份", ["3月", "6月", "9月"], horizontal=True)
        elif receipt_type == "7. 進香":
            sub_option = st.radio("選擇行程", ["南巡", "北巡"], horizontal=True)

        r_note = st.text_area("備註說明", placeholder="可在此輸入詳細細節或金額等備註...")

        generate_btn = st.button("🧾 生成收執聯", type="primary")

    with col_r:
        st.subheader("2. 收執聯預覽/呈現")

        if generate_btn:
            if not r_name:
                st.warning("請先輸入信徒姓名！")
            else:
                current_time = datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                # 組合選項名稱
                full_option = receipt_type
                if sub_option:
                    full_option += f" ({sub_option})"

                # 呈現樣式收執聯
                st.markdown(
                    f"""
                <div style="border: 2px dashed #8B0000; padding: 25px; border-radius: 10px; background-color: #FFFDF0; color: #333;">
                    <h2 style="text-align: center; color: #8B0000; margin-bottom: 5px;">⛩️ 龍天宮 惠存收執聯</h2>
                    <p style="text-align: right; color: #666; font-size: 0.9em;"><b>開立時間：</b>{current_time}</p>
                    <hr style="border: 1px solid #8B0000;">
                    <p style="font-size: 1.1em;"><b>信徒姓名：</b> {r_name}</p>
                    <p style="font-size: 1.1em;"><b>住址：</b> {r_address if r_address else '無'}</p>
                    <p style="font-size: 1.1em;"><b>辦理項目（選項）：</b> <span style="color: #D9534F; font-weight: bold;">{full_option}</span></p>
                    <p style="font-size: 1.1em;"><b>備註：</b> {r_note if r_note else '無'}</p>
                    <br>
                    <div style="display: flex; justify-content: space-between; margin-top: 20px;">
                        <span><b>經手人/蓋章：</b> __________________</span>
                        <span style="color: #8B0000; font-weight: bold;">龍天宮 敬啓</span>
                    </div>
                </div>
                """,
                    unsafe_allow_html=True,
                )