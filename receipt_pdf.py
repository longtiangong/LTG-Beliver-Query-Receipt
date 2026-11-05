from io import BytesIO

import qrcode
from reportlab.lib.pagesizes import A5
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def build_receipt_display_fields(receipt):
    fields = [
        ("開立時間", receipt.get("開立時間", "")),
        ("收據編號", receipt.get("收據編號", "")),
        ("信徒姓名", receipt.get("姓名", "")),
    ]
    if "地址" in receipt:
        fields.append(("地址", receipt.get("地址") or "無"))
    fields.append(("辦理項目", receipt.get("辦理項目", "")))
    if receipt.get("科目"):
        fields.append(("科目", receipt["科目"]))
    if receipt.get("規格"):
        fields.append(("規格", receipt["規格"]))
    if receipt.get("詳細內容"):
        fields.append(("詳細內容", receipt["詳細內容"]))
    amount_label = (
        "收到金額"
        if receipt.get("辦理項目") == "收入"
        else "支出金額"
    )
    fields.append(
        (amount_label, f"NT$ {int(receipt.get('收到金額', 0)):,.0f}")
    )
    if receipt.get("選項人數"):
        fields.append(("選項人數", receipt["選項人數"]))
    fields.extend(
        [
            ("系統備註", receipt.get("系統備註") or "無"),
            ("經手人", receipt.get("經手人") or "未填"),
            (
                "經手人備註",
                receipt.get("經手人備註") or receipt.get("備註") or "無",
            ),
        ]
    )
    return fields


def create_receipt_qr(pdf_url):
    """Create a QR PNG that opens the receipt."""
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
    """Create an A5 PDF with the customer and stub receipts stacked vertically."""
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf_buffer = BytesIO()
    page_width, page_height = A5
    pdf = canvas.Canvas(pdf_buffer, pagesize=A5)
    margin = 24
    fields = build_receipt_display_fields(receipt)
    qr_image = ImageReader(
        BytesIO(create_receipt_qr(receipt["QR連結"]))
    )
    qr_size = 48

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
        max_width = page_width - margin * 2 - 20 - qr_size - 8
        pdf.drawImage(
            qr_image,
            page_width - margin - 10 - qr_size,
            copy_top - 38 - qr_size,
            width=qr_size,
            height=qr_size,
        )
        available_text_height = text_y - (copy_bottom + 62)
        pdf.setFillColorRGB(0.15, 0.15, 0.15)
        font_size = 8
        while font_size > 5.5:
            line_count = 0
            for label, value in fields:
                line = f"{label}：{value}".replace("\n", "；")
                current_line = ""
                line_count += 1
                for character in line:
                    candidate = current_line + character
                    if current_line and pdfmetrics.stringWidth(
                        candidate, "STSong-Light", font_size
                    ) > max_width:
                        line_count += 1
                        current_line = character
                    else:
                        current_line = candidate
            if line_count * (font_size + 1.5) <= available_text_height:
                break
            font_size -= 0.5
        leading = font_size + 1.5
        pdf.setFont("STSong-Light", font_size)
        for label, value in fields:
            line = f"{label}：{value}".replace("\n", "；")
            current_line = ""
            for character in line:
                candidate = current_line + character
                if current_line and pdfmetrics.stringWidth(
                    candidate, "STSong-Light", font_size
                ) > max_width:
                    pdf.drawString(text_x, text_y, current_line)
                    text_y -= leading
                    current_line = character
                else:
                    current_line = candidate
            if current_line:
                pdf.drawString(text_x, text_y, current_line)
                text_y -= leading

        signature_y = copy_bottom + 14
        pdf.drawString(text_x, signature_y + 5, "收訖/蓋章：")
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
