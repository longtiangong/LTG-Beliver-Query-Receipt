import base64
import datetime
import html
import secrets
from decimal import Decimal, InvalidOperation
from io import BytesIO

import qrcode
import requests
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A5
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

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
GAS_API_KEY = st.secrets.get("GAS_API_KEY", "")

INCOME_CATEGORIES = {
    "法會進香報名": (
        "祭改",
        "光明燈",
        "太歲",
        "五大主斗",
        "補運",
        "補財庫",
        "普度",
    ),
    "添油香奉獻": ("添油香", "奉獻", "其他"),
}
EXPENSE_CATEGORIES = (
    "法會支出",
    "友宮拜訪支出",
    "平時常態支出",
    "雜項支出",
)


def _normalize_option_text(value):
    return "".join(str(value or "").split()).casefold()


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
        response = res.json()
        if res.status_code == 200 and response.get("status") == "success":
            st.cache_data.clear()  # 清除快取以刷新資料
            return response
        else:
            st.error(f"寫入失敗：{res.text}")
            return False
    except Exception as e:
        st.error(f"寫入發生例外狀況: {e}")
        return False


@st.cache_data(ttl=30)
def fetch_receipt_records():
    """從受 API 金鑰保護的 GAS 端點讀取收據總表"""
    if not GAS_URL:
        st.error("未設定 GAS_URL，無法讀取收據總表。")
        return None
    if not GAS_API_KEY:
        st.error("未設定 GAS_API_KEY，請先完成收據總表 API 金鑰設定。")
        return None
    try:
        res = requests.post(
            GAS_URL,
            json={"action": "listReceipts", "apiKey": GAS_API_KEY},
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"讀取收據總表發生錯誤：{e}")
        return None
    except requests.exceptions.JSONDecodeError:
        st.error("讀取收據總表失敗：Google Apps Script 回應不是有效的 JSON。")
        return None

    if (
        not isinstance(data, dict)
        or data.get("status") != "success"
        or not isinstance(data.get("records"), list)
    ):
        message = (
            data.get("message", "回傳格式錯誤")
            if isinstance(data, dict)
            else "回傳格式錯誤"
        )
        st.error(f"讀取收據總表失敗：{message}")
        return None
    return pd.DataFrame(data["records"])


@st.cache_data(ttl=60)
def fetch_receipt_options():
    """從受 API 金鑰保護的 GAS 端點讀取收入科目、規格與金額"""
    if not GAS_URL:
        st.error("未設定 GAS_URL，無法讀取收入科目金額。")
        return None
    if not GAS_API_KEY:
        st.error("未設定 GAS_API_KEY，無法讀取收入科目金額。")
        return None
    try:
        res = requests.post(
            GAS_URL,
            json={"action": "listReceiptOptions", "apiKey": GAS_API_KEY},
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"讀取收入科目金額發生錯誤：{e}")
        return None
    except requests.exceptions.JSONDecodeError:
        st.error("讀取收入科目金額失敗：Google Apps Script 回應不是有效的 JSON。")
        return None

    if (
        not isinstance(data, dict)
        or data.get("status") != "success"
        or not isinstance(data.get("options"), list)
    ):
        message = (
            data.get("message", "回傳格式錯誤")
            if isinstance(data, dict)
            else "回傳格式錯誤"
        )
        st.error(f"讀取收入科目金額失敗：{message}")
        return None
    options = []
    for option in data["options"]:
        if not isinstance(option, dict):
            st.error("讀取收入科目金額失敗：選項資料格式錯誤。")
            return None
        subject = str(
            option.get("科目") or option.get("主選項") or ""
        ).strip()
        specification = str(
            option.get("規格") or option.get("次選項") or ""
        ).strip()
        if subject:
            options.append(
                {
                    "科目": subject,
                    "規格": specification,
                    "金額": option.get("金額"),
                }
            )
    return options


@st.cache_data(ttl=60)
def fetch_expense_options():
    """從受 API 金鑰保護的 GAS 端點讀取支出科目與規格"""
    if not GAS_URL:
        st.error("未設定 GAS_URL，無法讀取支出科目。")
        return None
    if not GAS_API_KEY:
        st.error("未設定 GAS_API_KEY，無法讀取支出科目。")
        return None
    try:
        res = requests.post(
            GAS_URL,
            json={"action": "listExpenseOptions", "apiKey": GAS_API_KEY},
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"讀取支出科目發生錯誤：{e}")
        return None
    except requests.exceptions.JSONDecodeError:
        st.error("讀取支出科目失敗：Google Apps Script 回應不是有效的 JSON。")
        return None

    if (
        not isinstance(data, dict)
        or data.get("status") != "success"
        or not isinstance(data.get("options"), list)
    ):
        message = (
            data.get("message", "回傳格式錯誤")
            if isinstance(data, dict)
            else "回傳格式錯誤"
        )
        st.error(f"讀取支出科目失敗：{message}")
        return None
    return data["options"]


def save_expense_record(expense, pdf_bytes):
    """將支出收據及 PDF 寫入指定 Google Sheet 的支出表"""
    if not GAS_URL:
        st.error("未設定 GAS_URL，無法儲存支出。")
        return None
    if not GAS_API_KEY:
        st.error("未設定 GAS_API_KEY，無法儲存支出。")
        return None
    try:
        res = requests.post(
            GAS_URL,
            json={
                "action": "saveExpense",
                "apiKey": GAS_API_KEY,
                "expense": expense,
                "pdfBase64": base64.b64encode(pdf_bytes).decode("ascii"),
            },
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"儲存支出發生錯誤：{e}")
        return None
    except requests.exceptions.JSONDecodeError:
        st.error("儲存支出失敗：Google Apps Script 回應不是有效的 JSON。")
        return None

    if not isinstance(data, dict) or data.get("status") != "success":
        message = (
            data.get("message", "回傳格式錯誤")
            if isinstance(data, dict)
            else "回傳格式錯誤"
        )
        st.error(f"儲存支出失敗：{message}")
        return None
    if not isinstance(data.get("record"), dict):
        st.error("儲存支出失敗：Google Apps Script 未回傳支出紀錄。")
        return None
    st.cache_data.clear()
    return data["record"]


@st.cache_data(ttl=60)
def fetch_finance_records():
    """讀取收入表與支出表供收支比較圖表使用"""
    if not GAS_URL:
        st.error("未設定 GAS_URL，無法讀取收支紀錄。")
        return None
    if not GAS_API_KEY:
        st.error("未設定 GAS_API_KEY，無法讀取收支紀錄。")
        return None
    try:
        res = requests.post(
            GAS_URL,
            json={"action": "listFinanceRecords", "apiKey": GAS_API_KEY},
            timeout=10,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"讀取收支紀錄發生錯誤：{e}")
        return None
    except requests.exceptions.JSONDecodeError:
        st.error("讀取收支紀錄失敗：Google Apps Script 回應不是有效的 JSON。")
        return None

    if (
        not isinstance(data, dict)
        or data.get("status") != "success"
        or not isinstance(data.get("income"), list)
        or not isinstance(data.get("expenses"), list)
    ):
        message = (
            data.get("message", "回傳格式錯誤")
            if isinstance(data, dict)
            else "回傳格式錯誤"
        )
        st.error(f"讀取收支紀錄失敗：{message}")
        return None
    return data


def parse_receipt_amount(value):
    """將選項表中的金額轉為整數；空白或非整數金額交由人工輸入"""
    if value is None or pd.isna(value):
        return None
    text = (
        str(value)
        .strip()
        .replace(",", "")
        .replace("NT$", "")
        .replace("元", "")
    )
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"「{value}」不是有效的整數金額。") from error
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError(f"「{value}」不是有效的非負整數金額。")
    return int(amount)


def calculate_receipt_item(main_option, sub_option, people, unit_amount):
    item_total = int(people * unit_amount)
    system_note = (
        f"{main_option}{sub_option}人數{people}人"
        f"金額為{item_total:,.0f}元"
    )
    return item_total, system_note


def save_receipt_record(receipt, pdf_bytes):
    """將收據存入 Google Sheet 的收據總表"""
    if not GAS_URL:
        st.error("未設定 GAS_URL，無法儲存收據。")
        return None
    if not GAS_API_KEY:
        st.error("未設定 GAS_API_KEY，請先完成收據總表 API 金鑰設定。")
        return None
    try:
        res = requests.post(
            GAS_URL,
            json={
                "action": "saveReceipt",
                "apiKey": GAS_API_KEY,
                "receipt": receipt,
                "pdfBase64": base64.b64encode(pdf_bytes).decode("ascii"),
            },
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()
    except requests.exceptions.RequestException as e:
        st.error(f"儲存收據發生錯誤：{e}")
        return None
    except requests.exceptions.JSONDecodeError:
        st.error("儲存收據失敗：Google Apps Script 回應不是有效的 JSON。")
        return None

    if (
        not isinstance(data, dict)
        or data.get("status") != "success"
        or not isinstance(data.get("record"), dict)
    ):
        message = (
            data.get("message", "回傳格式錯誤")
            if isinstance(data, dict)
            else "回傳格式錯誤"
        )
        st.error(f"儲存收據失敗：{message}")
        return None

    st.cache_data.clear()
    return data["record"]


def create_receipt_qr(pdf_url):
    """在本機產生直接連到私有收執聯 PDF 的 QR PNG"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=4,
        border=2,
    )
    qr.add_data(pdf_url)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white")
    qr_buffer = BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    return qr_buffer.getvalue()


def create_receipt_pdf(receipt):
    """製作上下排列的 A5 收執聯及存根聯 PDF"""
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf_buffer = BytesIO()
    page_width, page_height = A5
    pdf = canvas.Canvas(pdf_buffer, pagesize=A5)
    margin = 24
    fields = [
        ("開立時間", str(receipt["開立時間"])),
        ("收據編號", str(receipt["收據編號"])),
        ("信徒姓名", str(receipt["姓名"])),
        *(
            [("住址", str(receipt.get("地址") or "無"))]
            if receipt.get("地址") is not None
            else []
        ),
        ("辦理項目", str(receipt["辦理項目"])),
        ("收到金額", f"NT$ {float(receipt['收到金額']):,.0f}"),
        ("系統備註", str(receipt.get("系統備註") or "")),
        (
            "經手人備註",
            str(receipt.get("經手人備註") or receipt.get("備註") or "無"),
        ),
    ]
    if receipt.get("日期"):
        fields.insert(1, ("支出日期", str(receipt["日期"])))

    copy_height = (page_height - margin * 2 - 12) / 2
    for copy_index, title in enumerate(("收執聯", "存根聯")):
        copy_top = page_height - margin - copy_index * (copy_height + 12)
        copy_bottom = copy_top - copy_height
        pdf.setStrokeColorRGB(0.55, 0.0, 0.0)
        pdf.rect(margin, copy_bottom, page_width - margin * 2, copy_height)
        pdf.setFillColorRGB(0.55, 0.0, 0.0)
        pdf.setFont("STSong-Light", 13)
        pdf.drawCentredString(
            page_width / 2, copy_top - 20, f"龍天宮 {title}"
        )

        text_x = margin + 10
        text_y = copy_top - 38
        max_width = page_width - margin * 2 - 20
        pdf.setFillColorRGB(0.15, 0.15, 0.15)
        pdf.setFont("STSong-Light", 8)
        for label, value in fields:
            line = f"{label}：{value}".replace("\n", "；")
            wrapped_lines = []
            current_line = ""
            for character in line:
                candidate = current_line + character
                if current_line and pdfmetrics.stringWidth(
                    candidate, "STSong-Light", 8
                ) > max_width:
                    wrapped_lines.append(current_line)
                    current_line = character
                else:
                    current_line = candidate
            wrapped_lines.append(current_line)
            for wrapped_line in wrapped_lines:
                pdf.drawString(text_x, text_y, wrapped_line)
                text_y -= 10

        signature_y = copy_bottom + 14
        pdf.drawString(text_x, signature_y + 5, "經手人/蓋章：")
        pdf.line(text_x + 52, signature_y + 3, text_x + 120, signature_y + 3)
        seal_size = 42
        seal_x = page_width - margin - 10 - seal_size
        seal_y = copy_bottom + 8
        pdf.setStrokeColorRGB(0.7, 0.08, 0.08)
        pdf.setLineWidth(2)
        pdf.rect(seal_x, seal_y, seal_size, seal_size)
        pdf.setLineWidth(0.8)
        pdf.rect(seal_x + 3, seal_y + 3, seal_size - 6, seal_size - 6)
        pdf.setFillColorRGB(0.7, 0.08, 0.08)
        pdf.setFont("STSong-Light", 9)
        pdf.drawCentredString(seal_x + seal_size / 2, seal_y + 24, "龍天宮")
        pdf.drawCentredString(seal_x + seal_size / 2, seal_y + 12, "管委會")

    pdf.setStrokeColorRGB(0.55, 0.0, 0.0)
    pdf.setDash(3, 3)
    pdf.line(margin, page_height / 2, page_width - margin, page_height / 2)
    pdf.setDash()

    pdf.save()
    return pdf_buffer.getvalue()


def render_receipt_preview(receipt, qr_bytes, receipt_type):
    qr_data_uri = (
        "data:image/png;base64,"
        + base64.b64encode(qr_bytes).decode("ascii")
    )
    fields = [
        ("開立時間", receipt.get("開立時間", "")),
        ("收據編號", receipt.get("收據編號", "")),
        ("姓名", receipt.get("姓名", "")),
    ]
    if receipt.get("日期"):
        fields.insert(1, ("支出日期", receipt["日期"]))
    if receipt.get("地址"):
        fields.append(("地址", receipt["地址"]))
    fields.extend(
        [
            ("辦理項目", receipt.get("辦理項目", "")),
            ("收到金額", f"NT$ {int(receipt.get('收到金額', 0)):,.0f}"),
            ("系統備註", receipt.get("系統備註") or "無"),
            (
                "經手人備註",
                receipt.get("經手人備註") or receipt.get("備註") or "無",
            ),
        ]
    )
    details = "".join(
        "<p><b>"
        + html.escape(str(label))
        + "：</b>"
        + html.escape(str(value)).replace("\n", "<br>")
        + "</p>"
        for label, value in fields
    )
    st.image(
        qr_bytes,
        caption="掃描 QR code 即可開啟收執聯 PDF",
        width=160,
    )
    st.link_button("開啟收執聯 PDF", receipt["PDF連結"])
    st.components.v1.html(
        f"""
        <style>
            body {{ margin: 0; font-family: sans-serif; color: #333; }}
            .copies {{ display: grid; grid-template-rows: 1fr auto 1fr; gap: 8px; }}
            .receipt-copy {{ position: relative; min-height: 245px; padding: 12px 16px 76px; border: 1px solid #8B0000; background: #FFFDF0; }}
            .receipt-copy h2 {{ margin: 0 0 8px; text-align: center; color: #8B0000; font-size: 1.25em; }}
            .copy-content {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
            .receipt-copy p {{ margin: 4px 0; font-size: .9em; line-height: 1.25; overflow-wrap: anywhere; }}
            .qr-code {{ width: 68px; height: 68px; flex: 0 0 68px; }}
            .signature {{ position: absolute; right: 16px; bottom: 10px; left: 16px; display: flex; justify-content: space-between; align-items: flex-end; font-size: .78em; }}
            .seal {{ display: flex; width: 64px; height: 64px; align-items: center; justify-content: center; border: 3px double #B22222; color: #B22222; font-size: 13px; font-weight: bold; text-align: center; }}
            .cut-line {{ border-top: 2px dashed #8B0000; color: #8B0000; font-size: .75em; text-align: center; }}
            .print-button {{ margin-top: 12px; padding: 8px 16px; border: 0; border-radius: 6px; background: #8B0000; color: white; font-size: 1em; cursor: pointer; }}
            @media print {{
                @page {{ size: A5 portrait; margin: 8mm; }}
                html, body {{ width: 100%; height: 190mm; }}
                .copies {{ height: 190mm; gap: 4px; break-inside: avoid; page-break-inside: avoid; }}
                .receipt-copy {{ min-height: 0; padding: 8px 12px 68px; print-color-adjust: exact; -webkit-print-color-adjust: exact; break-inside: avoid; page-break-inside: avoid; }}
                .receipt-copy .signature {{ right: 12px; bottom: 8px; left: 12px; }}
                .receipt-copy .seal {{ width: 58px; height: 58px; }}
                .qr-code {{ width: 62px; height: 62px; flex-basis: 62px; }}
                .print-button {{ display: none; }}
            }}
        </style>
        <div class="copies">
            <section class="receipt-copy">
                <h2>⛩️ 龍天宮 {html.escape(receipt_type)}收執聯</h2>
                <div class="copy-content">{details}<img class="qr-code" src="{qr_data_uri}" alt="收據 QR code"></div>
                <div class="signature"><span><b>經手人/蓋章：</b> ______________</span><span class="seal">龍天宮<br>管委會</span></div>
            </section>
            <div class="cut-line">沿虛線裁切</div>
            <section class="receipt-copy">
                <h2>⛩️ 龍天宮 {html.escape(receipt_type)}存根聯</h2>
                <div class="copy-content">{details}<img class="qr-code" src="{qr_data_uri}" alt="收據 QR code"></div>
                <div class="signature"><span><b>經手人/蓋章：</b> ______________</span><span class="seal">龍天宮<br>管委會</span></div>
            </section>
        </div>
        <button class="print-button" onclick="window.print()">🖨️ 列印收執聯/存根聯</button>
        """,
        height=660,
        scrolling=False,
    )


# -----------------------------------------------------------------------------
# 3. 右側/側邊欄選單
# -----------------------------------------------------------------------------
st.sidebar.title("⛩️ 龍天宮系統選單")
menu_option = st.sidebar.radio(
    "請選擇功能：",
    [
        "一、信徒資料查詢",
        "二、收入收據",
        "三、支出內容",
        "四、收入與支出比較圖表",
    ],
)
submenu_option = None
if menu_option == "二、收入收據":
    submenu_option = st.sidebar.selectbox(
        "收入類別：", list(INCOME_CATEGORIES)
    )
elif menu_option == "三、支出內容":
    submenu_option = st.sidebar.selectbox(
        "支出類別：", EXPENSE_CATEGORIES
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
                            "手機": phone,
                            "2026丁/口": dinkou_2026,
                            "2026光明燈": guangming_2026,
                            "2026太歲": taisui_2026,
                        }
                        result = save_believer_data(payload)
                        if result:
                            st.success(
                                f"成功新增資料至 Google Sheet！編號：{result.get('number', '已自動編號')}"
                            )
                            st.rerun()

# -----------------------------------------------------------------------------
# 功能二：各類收據開立
# -----------------------------------------------------------------------------
elif menu_option == "二、收入收據":
    st.header(f"🧾 收入收據｜{submenu_option}")

    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.subheader("1. 輸入收據資料")
        r_name = st.text_input("大德姓名", key="receipt_name")

        if r_name != st.session_state.get("_receipt_lookup_name"):
            st.session_state["receipt_address"] = ""
            if r_name.strip():
                believer_df = fetch_believer_data()
                if (
                    believer_df is not None
                    and "姓名" in believer_df.columns
                ):
                    matches = believer_df[
                        believer_df["姓名"].astype(str).str.strip()
                        == r_name.strip()
                    ]
                    if not matches.empty:
                        address_column = (
                            "住址"
                            if "住址" in matches.columns
                            else "地址"
                        )
                        if address_column in matches.columns:
                            address_value = matches.iloc[0][address_column]
                            if pd.isna(address_value):
                                address_value = ""
                            st.session_state["receipt_address"] = str(
                                address_value
                            )
                        if len(matches) > 1:
                            st.info(
                                f"找到 {len(matches)} 筆同名資料，已帶出第一筆住址；"
                                "請確認或手動修改。"
                            )
            st.session_state["_receipt_lookup_name"] = r_name

        r_address = st.text_input("地址", key="receipt_address")
        st.caption("輸入完整姓名並找到資料後，地址會自動帶出，仍可手動修改。")

        receipt_options = fetch_receipt_options()
        available_subjects = list(
            dict.fromkeys(
                str(option.get("科目", "")).strip()
                for option in (receipt_options or [])
                if str(option.get("科目", "")).strip()
            )
        )
        category_subjects = {
            _normalize_option_text(subject)
            for subject in INCOME_CATEGORIES[submenu_option]
        }
        subject_options = [
            subject
            for subject in available_subjects
            if _normalize_option_text(subject) in category_subjects
        ]
        if available_subjects and not subject_options:
            subject_options = available_subjects
            st.warning(
                f"收入科目金額工作表中的科目未對應「{submenu_option}」的預設清單，"
                "目前先顯示工作表全部科目；請確認選取正確。"
            )
        receipt_items = []
        if subject_options:
            if "receipt_item_count" not in st.session_state:
                st.session_state["receipt_item_count"] = 1

            for item_index in range(st.session_state["receipt_item_count"]):
                item_key_prefix = f"income_{submenu_option}_{item_index}"
                st.markdown(f"**選項明細 {item_index + 1}**")
                item_subject = st.selectbox(
                    "科目",
                    subject_options,
                    key=f"{item_key_prefix}_subject",
                )
                matching_options = [
                    option
                    for option in receipt_options
                    if _normalize_option_text(option.get("科目"))
                    == _normalize_option_text(item_subject)
                ]
                sub_options = list(
                    dict.fromkeys(
                        str(option.get("規格", "")).strip()
                        for option in matching_options
                        if str(option.get("規格", "")).strip()
                    )
                )
                selected_specification = ""
                manual_specification = ""
                if sub_options:
                    selected_specification = st.selectbox(
                        "規格",
                        [""] + sub_options,
                        format_func=lambda value: value or "請選擇（或手動輸入）",
                        key=f"{item_key_prefix}_specification",
                    )
                if not selected_specification:
                    manual_specification = st.text_input(
                        "規格（無清單項目時手動輸入）",
                        key=f"{item_key_prefix}_manual_specification",
                    )
                effective_specification = (
                    selected_specification or manual_specification.strip()
                )

                lookup_specification = selected_specification
                if not sub_options:
                    lookup_specification = ""
                matching_prices = []
                for option in matching_options:
                    if (
                        str(option.get("規格", "")).strip()
                        != lookup_specification
                    ):
                        continue
                    try:
                        matching_prices.append(
                            parse_receipt_amount(option.get("金額"))
                        )
                    except ValueError as error:
                        st.warning(
                            f"{item_subject} {lookup_specification} 的工作表金額有誤：{error}"
                            "；請手動確認金額。"
                        )
                sheet_amount = next(
                    (amount for amount in matching_prices if amount is not None),
                    None,
                )
                amount_key = f"{item_key_prefix}_amount"
                signature_key = f"_{item_key_prefix}_price_signature"
                price_signature = (
                    f"{item_subject}\u241f{lookup_specification}"
                )
                if st.session_state.get(signature_key) != price_signature:
                    st.session_state[amount_key] = sheet_amount or 0
                    st.session_state[signature_key] = price_signature

                item_columns = st.columns(2)
                with item_columns[0]:
                    item_people = st.number_input(
                        "選項人數",
                        min_value=1,
                        value=1,
                        step=1,
                        key=f"{item_key_prefix}_people",
                    )
                with item_columns[1]:
                    item_unit_amount = st.number_input(
                        "金額（每人，元）",
                        min_value=0,
                        step=1,
                        key=amount_key,
                    )

                item_total, item_note = calculate_receipt_item(
                    item_subject,
                    effective_specification,
                    item_people,
                    item_unit_amount,
                )
                receipt_items.append(
                    {
                        "主選項": item_subject,
                        "次選項": effective_specification,
                        "人數": int(item_people),
                        "單價": int(item_unit_amount),
                        "金額": item_total,
                        "系統備註": item_note,
                    }
                )
                st.caption(f"此項金額：NT$ {item_total:,.0f}")

            item_buttons = st.columns(2)
            if item_buttons[0].button(
                "＋ 新增一筆科目", key="add_receipt_item"
            ):
                st.session_state["receipt_item_count"] += 1
                st.rerun()
            if (
                st.session_state["receipt_item_count"] > 1
                and item_buttons[1].button(
                    "－ 刪除最後一筆", key="remove_receipt_item"
                )
            ):
                st.session_state["receipt_item_count"] -= 1
                st.rerun()

            r_total = sum(item["金額"] for item in receipt_items)
            system_note = "\n".join(
                item["系統備註"] for item in receipt_items
            )
            st.text_area("系統備註", value=system_note, disabled=True)
            st.metric("總金額", f"NT$ {r_total:,.0f}")
        else:
            st.error(
                "「收入科目金額」工作表沒有可用科目。"
                "請確認工作表標題為「科目、規格、金額(元)」，"
                "並確認已部署最新的 Apps Script。"
            )
            r_total = 0
            system_note = ""

        handler_note = st.text_area(
            "經手人備註",
            key="receipt_handler_note",
            placeholder="可在此輸入其他備註...",
        )

        # * 2 收據金額輸入、總表永久保存及 QR code 生成
        generate_btn = st.button(
            "🧾 登記收據並準備列印",
            type="primary",
            disabled=not subject_options,
        )

    with col_r:
        st.subheader("2. 收執聯預覽/呈現")

        if generate_btn:
            if not r_name.strip():
                st.warning("請先輸入大德姓名！")
            else:
                taiwan_timezone = datetime.timezone(datetime.timedelta(hours=8))
                issued_at = datetime.datetime.now(taiwan_timezone)
                opened_at = issued_at.strftime("%Y-%m-%d %H:%M:%S")
                full_option = "\n".join(
                    item["主選項"]
                    + (f" {item['次選項']}" if item["次選項"] else "")
                    for item in receipt_items
                )
                item_values = {
                    "主選項": "\n".join(
                        item["主選項"] for item in receipt_items
                    ),
                    "次選項": "\n".join(
                        item["次選項"] for item in receipt_items
                    ),
                    "選項人數": "\n".join(
                        str(item["人數"]) for item in receipt_items
                    ),
                }
                receipt_draft = {
                    "收據編號": (
                        "LTG-"
                        + issued_at.strftime("%Y%m%d")
                        + "-"
                        + str(secrets.randbelow(90000) + 10000)
                    ),
                    "開立時間": opened_at,
                    "姓名": r_name.strip(),
                    "地址": r_address.strip(),
                    "辦理項目": full_option,
                    "收到金額": r_total,
                    "類別": submenu_option,
                    **item_values,
                    "系統備註": system_note,
                    "經手人備註": handler_note.strip(),
                    "備註": handler_note.strip(),
                }
                pdf_bytes = create_receipt_pdf(receipt_draft)
                receipt = save_receipt_record(receipt_draft, pdf_bytes)
                if receipt:
                    qr_bytes = create_receipt_qr(receipt["PDF連結"])
                    st.session_state["active_receipt"] = receipt
                    st.session_state["active_receipt_qr"] = qr_bytes
                    st.success(
                        f"收據 {receipt['收據編號']} 已建立 PDF，並加入收據總表與收入表。"
                    )
        receipt = st.session_state.get("active_receipt")
        if receipt:
            receipt_id = str(receipt["收據編號"])
            receipt_name = str(receipt["姓名"])
            receipt_amount = float(receipt["收到金額"])
            system_note = str(receipt.get("系統備註") or "")
            handler_note = str(
                receipt.get("經手人備註") or receipt.get("備註") or ""
            )
            qr_bytes = st.session_state.get("active_receipt_qr")
            if not qr_bytes:
                qr_bytes = create_receipt_qr(receipt["PDF連結"])
                st.session_state["active_receipt_qr"] = qr_bytes
            qr_data_uri = (
                "data:image/png;base64,"
                + base64.b64encode(qr_bytes).decode("ascii")
            )

            st.image(
                qr_bytes,
                caption="掃描 QR code 即可開啟收執聯 PDF",
                width=160,
            )
            st.link_button("開啟收執聯 PDF", receipt["PDF連結"])

            escaped_id = html.escape(receipt_id)
            escaped_time = html.escape(str(receipt["開立時間"]))
            escaped_name = html.escape(receipt_name)
            escaped_address = html.escape(str(receipt["地址"]) or "無")
            escaped_option = html.escape(str(receipt["辦理項目"])).replace(
                "\n", "<br>"
            )
            escaped_amount = f"{receipt_amount:,.0f}"
            escaped_system_note = html.escape(system_note or "無").replace(
                "\n", "<br>"
            )
            escaped_handler_note = html.escape(handler_note or "無").replace(
                "\n", "<br>"
            )

            # * 1 A5 直式收執聯／存根聯上下排列，中間以虛線裁切
            # * 3 收執聯與存根聯右下角加印「龍天宮管委會」關防章
            receipt_details = f"""
                <div class="copy-content">
                    <div>
                        <p class="time"><b>開立時間：</b>{escaped_time}</p>
                        <p><b>收據編號：</b>{escaped_id}</p>
                        <p><b>信徒姓名：</b>{escaped_name}</p>
                        <p><b>住址：</b>{escaped_address}</p>
                        <p><b>辦理項目：</b><span class="option">{escaped_option}</span></p>
                        <p><b>收到金額：</b>NT$ {escaped_amount}</p>
                        <p><b>系統備註：</b>{escaped_system_note}</p>
                        <p><b>經手人備註：</b>{escaped_handler_note}</p>
                    </div>
                    <img class="qr-code" src="{qr_data_uri}" alt="收據 QR code">
                </div>
                <div class="signature">
                    <span><b>經手人/蓋章：</b> ______________</span>
                    <span class="seal">龍天宮<br>管委會</span>
                </div>
            """

            st.components.v1.html(
                f"""
                <style>
                    body {{
                        margin: 0;
                        font-family: sans-serif;
                        color: #333;
                    }}
                    .copies {{
                        box-sizing: border-box;
                        display: grid;
                        grid-template-rows: minmax(0, 1fr) auto minmax(0, 1fr);
                        gap: 8px;
                    }}
                    .receipt-copy {{
                        box-sizing: border-box;
                        position: relative;
                        min-height: 0;
                        padding: 12px 16px 76px;
                        border: 1px solid #8B0000;
                        background: #FFFDF0;
                    }}
                    .receipt-copy h2 {{
                        margin: 0 0 4px;
                        text-align: center;
                        color: #8B0000;
                        font-size: 1.25em;
                    }}
                    .copy-content {{
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 8px;
                    }}
                    .receipt-copy p {{
                        margin: 4px 0;
                        font-size: 0.9em;
                        line-height: 1.25;
                        overflow-wrap: anywhere;
                    }}
                    .receipt-copy .time {{
                        color: #666;
                        font-size: 0.75em;
                    }}
                    .receipt-copy .option {{
                        color: #D9534F;
                        font-weight: bold;
                    }}
                    .qr-code {{
                        width: 68px;
                        height: 68px;
                        flex: 0 0 68px;
                    }}
                    .receipt-copy .signature {{
                        display: flex;
                        justify-content: space-between;
                        align-items: flex-end;
                        gap: 12px;
                        position: absolute;
                        right: 16px;
                        bottom: 10px;
                        left: 16px;
                        font-size: 0.78em;
                    }}
                    .receipt-copy .seal {{
                        box-sizing: border-box;
                        display: flex;
                        width: 64px;
                        height: 64px;
                        align-items: center;
                        justify-content: center;
                        border: 3px double #B22222;
                        border-radius: 2px;
                        box-shadow: inset 0 0 0 2px #FFFDF0, inset 0 0 0 3px #B22222;
                        color: #B22222;
                        font-size: 13px;
                        font-weight: bold;
                        line-height: 1.2;
                        text-align: center;
                        transform: rotate(-5deg);
                    }}
                    .cut-line {{
                        border-top: 2px dashed #8B0000;
                        color: #8B0000;
                        font-size: 0.75em;
                        text-align: center;
                        line-height: 1;
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
                            margin: 8mm;
                        }}
                        html, body {{
                            width: 100%;
                            height: 190mm;
                        }}
                        .copies {{
                            height: 190mm;
                            gap: 4px;
                            break-inside: avoid;
                            page-break-inside: avoid;
                        }}
                        .receipt-copy {{
                            padding: 8px 12px 68px;
                            print-color-adjust: exact;
                            -webkit-print-color-adjust: exact;
                            break-inside: avoid;
                            page-break-inside: avoid;
                        }}
                        .receipt-copy .signature {{
                            right: 12px;
                            left: 12px;
                            bottom: 8px;
                        }}
                        .receipt-copy .seal {{
                            width: 58px;
                            height: 58px;
                        }}
                        .qr-code {{
                            width: 62px;
                            height: 62px;
                            flex-basis: 62px;
                        }}
                        .print-button {{
                            display: none;
                        }}
                    }}
                </style>
                <div class="copies">
                    <section class="receipt-copy">
                        <h2>⛩️ 龍天宮 收執聯</h2>
                        {receipt_details}
                    </section>
                    <div class="cut-line">沿虛線裁切</div>
                    <section class="receipt-copy">
                        <h2>⛩️ 龍天宮 存根聯</h2>
                        {receipt_details}
                    </section>
                </div>
                <button class="print-button" onclick="window.print()">🖨️ 列印收執聯/存根聯</button>
                """,
                height=660,
                scrolling=False,
            )

    st.divider()
    st.subheader("3. 收據總表")
    receipt_records = fetch_receipt_records()
    if receipt_records is not None:
        if receipt_records.empty:
            st.info("目前尚無收據紀錄。")
        else:
            column_order = [
                "收據編號",
                "開立時間",
                "姓名",
                "地址",
                "辦理項目",
                "類別",
                "科目",
                "規格",
                "選項人數",
                "收到金額",
                "系統備註",
                "經手人備註",
                "備註",
                "PDF連結",
            ]
            available_columns = [
                column
                for column in column_order
                if column in receipt_records.columns
            ]
            st.dataframe(
                receipt_records[available_columns],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "PDF連結": st.column_config.LinkColumn(
                        "收執聯 PDF",
                        display_text="開啟 PDF",
                    )
                },
            )

elif menu_option == "三、支出內容":
    st.header(f"💸 支出內容｜{submenu_option}")
    expense_options = fetch_expense_options()
    matching_expenses = [
        option
        for option in (expense_options or [])
        if _normalize_option_text(option.get("科目"))
        == _normalize_option_text(submenu_option)
    ]
    specifications = list(
        dict.fromkeys(
            str(option.get("規格", "")).strip()
            for option in matching_expenses
            if str(option.get("規格", "")).strip()
        )
    )

    expense_col, preview_col = st.columns([1, 1])
    with expense_col:
        st.subheader("1. 輸入支出資料")
        expense_name = st.text_input("大德姓名", key="expense_name")
        expense_date = st.date_input(
            "支出日期", value=datetime.date.today(), key="expense_date"
        )
        if "expense_item_count" not in st.session_state:
            st.session_state["expense_item_count"] = 1

        expense_items = []
        for item_index in range(st.session_state["expense_item_count"]):
            st.markdown(f"**支出明細 {item_index + 1}**")
            item_key_prefix = f"expense_{submenu_option}_{item_index}"
            if specifications:
                specification = st.selectbox(
                    "規格",
                    specifications,
                    key=f"{item_key_prefix}_specification",
                )
            else:
                specification = st.text_input(
                    "規格", key=f"{item_key_prefix}_manual_specification"
                )

            selected_expense = next(
                (
                    option
                    for option in matching_expenses
                    if _normalize_option_text(option.get("規格"))
                    == _normalize_option_text(specification)
                ),
                {},
            )
            try:
                suggested_amount = parse_receipt_amount(
                    selected_expense.get("金額")
                )
            except ValueError as error:
                st.warning(
                    f"{submenu_option} {specification} 的工作表預設金額有誤："
                    f"{error}請手動輸入金額。"
                )
                suggested_amount = None

            signature_key = f"_{item_key_prefix}_price_signature"
            amount_key = f"{item_key_prefix}_amount"
            price_signature = f"{submenu_option}\u241f{specification}"
            if st.session_state.get(signature_key) != price_signature:
                st.session_state[amount_key] = suggested_amount or 0
                st.session_state[signature_key] = price_signature
            item_columns = st.columns(2)
            with item_columns[0]:
                item_people = st.number_input(
                    "人數",
                    min_value=1,
                    value=1,
                    step=1,
                    key=f"{item_key_prefix}_people",
                )
            with item_columns[1]:
                item_unit_amount = st.number_input(
                    "金額（每人，元）",
                    min_value=0,
                    step=1,
                    key=amount_key,
                )
            item_total, item_note = calculate_receipt_item(
                submenu_option,
                specification,
                item_people,
                item_unit_amount,
            )
            expense_items.append(
                {
                    "規格": specification.strip(),
                    "人數": int(item_people),
                    "單價": int(item_unit_amount),
                    "金額": item_total,
                    "系統備註": item_note,
                }
            )
            st.caption(f"此項金額：NT$ {item_total:,.0f}")

        item_buttons = st.columns(2)
        if item_buttons[0].button(
            "＋ 新增一筆規格", key="add_expense_item"
        ):
            st.session_state["expense_item_count"] += 1
            st.rerun()
        if (
            st.session_state["expense_item_count"] > 1
            and item_buttons[1].button(
                "－ 刪除最後一筆", key="remove_expense_item"
            )
        ):
            st.session_state["expense_item_count"] -= 1
            st.rerun()

        expense_total = sum(item["金額"] for item in expense_items)
        expense_system_note = "\n".join(
            item["系統備註"] for item in expense_items
        )
        st.text_area(
            "系統備註",
            value=expense_system_note,
            disabled=True,
            key="expense_system_note_display",
        )
        st.metric("總金額", f"NT$ {expense_total:,.0f}")
        expense_handler_note = st.text_area(
            "經手人備註", key="expense_handler_note"
        )
        save_expense = st.button(
            "🧾 登記支出並準備列印",
            type="primary",
            disabled=not expense_items,
            key="save_expense_receipt",
        )

    with preview_col:
        st.subheader("2. 收執聯預覽/呈現")
        if save_expense:
            if not expense_name.strip():
                st.warning("請先輸入大德姓名。")
            elif any(not item["規格"] for item in expense_items):
                st.warning("請完成所有支出明細的規格。")
            else:
                taiwan_timezone = datetime.timezone(
                    datetime.timedelta(hours=8)
                )
                issued_at = datetime.datetime.now(taiwan_timezone)
                opened_at = issued_at.strftime("%Y-%m-%d %H:%M:%S")
                receipt_id = (
                    "LTG-EXP-"
                    + issued_at.strftime("%Y%m%d")
                    + "-"
                    + str(secrets.randbelow(90000) + 10000)
                )
                full_option = "\n".join(
                    f"{submenu_option} {item['規格']}".strip()
                    for item in expense_items
                )
                expense_draft = {
                    "收據編號": receipt_id,
                    "開立時間": opened_at,
                    "日期": expense_date.strftime("%Y-%m-%d"),
                    "姓名": expense_name.strip(),
                    "辦理項目": full_option,
                    "收到金額": expense_total,
                    "規格": "\n".join(
                        item["規格"] for item in expense_items
                    ),
                    "選項人數": "\n".join(
                        str(item["人數"]) for item in expense_items
                    ),
                    "類別": submenu_option,
                    "科目": submenu_option,
                    "系統備註": expense_system_note,
                    "經手人備註": expense_handler_note.strip(),
                    "備註": expense_handler_note.strip(),
                }
                pdf_bytes = create_receipt_pdf(expense_draft)
                result = save_expense_record(
                    {
                        "收據編號": receipt_id,
                        "日期": expense_date.strftime("%Y-%m-%d"),
                        "開立時間": opened_at,
                        "科目": submenu_option,
                        "規格": expense_draft["規格"],
                        "姓名": expense_name.strip(),
                        "金額(元)": expense_total,
                        "系統備註": expense_system_note,
                        "經手人備註": expense_handler_note.strip(),
                        "備註": expense_handler_note.strip(),
                    },
                    pdf_bytes,
                )
                if result:
                    qr_bytes = create_receipt_qr(result["PDF連結"])
                    st.session_state["active_expense_receipt"] = {
                        **expense_draft,
                        **result,
                    }
                    st.session_state["active_expense_receipt_qr"] = qr_bytes
                    st.success(
                        f"支出收據 {receipt_id} 已建立 PDF 並加入支出表。"
                    )

        active_expense = st.session_state.get("active_expense_receipt")
        if active_expense:
            qr_bytes = st.session_state.get("active_expense_receipt_qr")
            if not qr_bytes:
                qr_bytes = create_receipt_qr(active_expense["PDF連結"])
                st.session_state["active_expense_receipt_qr"] = qr_bytes
            render_receipt_preview(
                active_expense, qr_bytes, receipt_type="支出"
            )

    st.divider()
    st.subheader("支出紀錄")
    finance_records = fetch_finance_records()
    if finance_records is not None:
        expense_df = pd.DataFrame(finance_records["expenses"])
        if "科目" in expense_df.columns:
            expense_df = expense_df[
                expense_df["科目"].astype(str).str.strip() == submenu_option
            ]
        if expense_df.empty:
            st.info("目前沒有此類別的支出紀錄。")
        else:
            st.dataframe(
                expense_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "PDF連結": st.column_config.LinkColumn(
                        "收執聯 PDF",
                        display_text="開啟 PDF",
                    )
                },
            )

elif menu_option == "四、收入與支出比較圖表":
    st.header("📊 收入與支出比較圖表")
    finance_records = fetch_finance_records()
    if finance_records is not None:
        income_df = pd.DataFrame(finance_records["income"])
        expense_df = pd.DataFrame(finance_records["expenses"])
        amount_column = "金額(元)"
        date_column = "日期"
        if (
            income_df.empty
            and expense_df.empty
        ):
            st.info("目前沒有收入或支出紀錄可供比較。")
        elif (
            any(
                amount_column not in frame.columns
                or date_column not in frame.columns
                for frame in (income_df, expense_df)
                if not frame.empty
            )
        ):
            st.error("收入表或支出表缺少「日期」或「金額(元)」欄位，無法產生圖表。")
        else:
            chart_frames = []
            for label, frame in (
                ("收入", income_df),
                ("支出", expense_df),
            ):
                if frame.empty:
                    continue
                chart_frame = frame[[date_column, amount_column]].copy()
                chart_frame["日期"] = pd.to_datetime(
                    chart_frame[date_column], errors="coerce"
                )
                chart_frame["金額"] = pd.to_numeric(
                    chart_frame[amount_column]
                    .astype(str)
                    .str.replace(",", "", regex=False)
                    .str.replace("元", "", regex=False),
                    errors="coerce",
                )
                chart_frame = chart_frame.dropna(subset=["日期", "金額"])
                chart_frame["類別"] = label
                chart_frames.append(chart_frame[["日期", "金額", "類別"]])

            if not chart_frames:
                st.info("找不到有效的日期與金額資料，無法產生圖表。")
            else:
                chart_data = pd.concat(chart_frames, ignore_index=True)
                chart_data["月份"] = (
                    chart_data["日期"].dt.to_period("M").astype(str)
                )
                monthly_totals = (
                    chart_data.groupby(["月份", "類別"])["金額"]
                    .sum()
                    .unstack(fill_value=0)
                    .reindex(columns=["收入", "支出"], fill_value=0)
                    .sort_index()
                )
                st.bar_chart(monthly_totals)
                st.dataframe(
                    monthly_totals.reset_index(),
                    use_container_width=True,
                    hide_index=True,
                )