import datetime
import html
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
        st.error("未設定 GAS_URL，無法讀取 Google Sheet。")
        return None
    try:
        res = requests.get(GAS_URL, timeout=10)
        res.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.error(f"讀取 Google Sheet 發生錯誤: {e}")
        return None

    try:
        data = res.json()
    except requests.exceptions.JSONDecodeError:
        st.error(
            "Google Apps Script 回應不是有效的 JSON。"
            "請檢查 doGet 是否執行成功，並確認 Web App 已部署最新版本。"
        )
        return None

    if isinstance(data, dict) and data.get("status") == "error":
        st.error(f"Google Apps Script 讀取失敗：{data.get('message', '未知錯誤')}")
        return None

    if not isinstance(data, list):
        st.error("Google Apps Script 回傳格式錯誤：預期為資料列清單。")
        return None
    return pd.DataFrame(data)


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
        if df is None:
            st.stop()

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
                "生辰年月日",
                "生時",
                "住址",
                "編號",
                "手機",
                "2026丁/口",
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
                    f"👤 信徒：{row.get('姓名', '')} - 手機：{row.get('手機', '無')}",
                    expanded=True,
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.markdown(f"**生辰年月日：** {row.get('生辰年月日', '')}")
                    c1.markdown(f"**生時：** {row.get('生時', '')}")

                    c2.markdown(f"**手機：** {row.get('手機', '')}")
                    c2.markdown(f"**住址：** {row.get('住址', '')}")
                    c2.markdown(f"**編號：** {row.get('編號', '')}")

                    c3.markdown(f"**2026丁/口：** {row.get('2026丁/口', '')}")
                    c3.markdown(f"**2026光明燈：** {row.get('2026光明燈', '')}")
                    c3.markdown(f"**2026太歲：** {row.get('2026太歲', '')}")

        else:
            st.info(f"查無姓名為「{search_name}」的信徒資料，可於下方手動輸入新增：")

            with st.form("add_believer_form"):
                st.subheader("➕ 手動新增信徒資料")
                col1, col2 = st.columns(2)

                name_input = col1.text_input("姓名", value=search_name)
                believer_number = col2.text_input("編號")

                birth_date = col1.text_input(
                    "生辰年月日", placeholder="例：農曆68年3月15日 或 1979-04-11"
                )
                birth_time = col2.text_input(
                    "生時", placeholder="例：吉時、子時(23-01)"
                )

                phone = col1.text_input("手機")
                address = col2.text_input("住址")

                st.markdown("---")
                col3, col4, col5 = st.columns(3)
                dinkou_2026 = col3.text_input("2026丁/口")
                guangming_2026 = col4.text_input("2026光明燈")
                taisui_2026 = col5.text_input("2026太歲")

                submit_btn = st.form_submit_button("新增並存入 Google Sheet")

                if submit_btn:
                    if not name_input:
                        st.error("姓名為必填欄位！")
                    else:
                        payload = {
                            "姓名": name_input,
                            "生辰年月日": birth_date,
                            "生時": birth_time,
                            "住址": address,
                            "編號": believer_number,
                            "手機": phone,
                            "2026丁/口": dinkou_2026,
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

                escaped_name = html.escape(r_name)
                escaped_address = html.escape(r_address or "無")
                escaped_option = html.escape(full_option)
                escaped_note = html.escape(r_note or "無").replace("\n", "<br>")

                st.components.v1.html(
                    f"""
                    <style>
                        body {{
                            margin: 0;
                            font-family: sans-serif;
                            color: #333;
                        }}
                        .receipt {{
                            box-sizing: border-box;
                            border: 2px dashed #8B0000;
                            padding: 24px;
                            border-radius: 10px;
                            background: #FFFDF0;
                        }}
                        .receipt h2 {{
                            margin: 0 0 8px;
                            text-align: center;
                            color: #8B0000;
                        }}
                        .receipt p {{
                            font-size: 1.1em;
                            line-height: 1.6;
                            overflow-wrap: anywhere;
                        }}
                        .receipt .time {{
                            text-align: right;
                            color: #666;
                            font-size: 0.9em;
                        }}
                        .receipt .option {{
                            color: #D9534F;
                            font-weight: bold;
                        }}
                        .receipt .signature {{
                            display: flex;
                            justify-content: space-between;
                            gap: 16px;
                            margin-top: 24px;
                        }}
                        .receipt .temple {{
                            color: #8B0000;
                            font-weight: bold;
                        }}
                        .print-button {{
                            margin-top: 12px;
                            padding: 8px 16px;
                            border: 0;
                            border-radius: 6px;
                            background: #8B0000;
                            color: white;
                            font-size: 1em;
                            cursor: pointer;
                        }}
                        @media print {{
                            @page {{
                                size: A5 portrait;
                                margin: 12mm;
                            }}
                            .print-button {{
                                display: none;
                            }}
                            .receipt {{
                                border-radius: 0;
                                print-color-adjust: exact;
                                -webkit-print-color-adjust: exact;
                            }}
                        }}
                    </style>
                    <div class="receipt">
                        <h2>⛩️ 龍天宮 惠存收執聯</h2>
                        <p class="time"><b>開立時間：</b>{current_time}</p>
                        <hr style="border: 1px solid #8B0000;">
                        <p><b>信徒姓名：</b> {escaped_name}</p>
                        <p><b>住址：</b> {escaped_address}</p>
                        <p><b>辦理項目（選項）：</b> <span class="option">{escaped_option}</span></p>
                        <p><b>備註：</b> {escaped_note}</p>
                        <div class="signature">
                            <span><b>經手人/蓋章：</b> __________________</span>
                            <span class="temple">龍天宮 敬啓</span>
                        </div>
                    </div>
                    <button class="print-button" onclick="window.print()">🖨️ 列印收執聯</button>
                    """,
                    height=430,
                    scrolling=False,
                )