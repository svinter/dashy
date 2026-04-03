"""PDF invoice generation for billing module.

Generates an invoice PDF using reportlab.
Provider contact info is read from billing_provider_settings (single DB row).
Invoice output directory is read from config.json billing settings.
Per-company payment instructions are stored in billing_companies.payment_instructions;
a fallback is derived from billing_method / payment_method if the field is empty.
"""

import base64
import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import DATA_DIR
from database import get_db_connection, get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])


def _get_provider() -> dict:
    """Read provider contact info from billing_provider_settings."""
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT * FROM billing_provider_settings WHERE id = 1"
        ).fetchone()
    if row:
        return {
            "provider_name":          (row["provider_name"]          or "").strip(),
            "provider_contact_name":  (row["provider_contact_name"]  or "").strip(),
            "provider_address1":      (row["provider_address1"]      or "").strip(),
            "provider_address2":      (row["provider_address2"]      or "").strip(),
            "provider_city_state_zip": (row["provider_city_state_zip"] or "").strip(),
            "provider_phone":         (row["provider_phone"]         or "").strip(),
            "provider_email":         (row["provider_email"]         or "").strip(),
        }
    return {
        "provider_name": "", "provider_contact_name": "", "provider_address1": "",
        "provider_address2": "", "provider_city_state_zip": "", "provider_phone": "",
        "provider_email": "",
    }


def _invoices_dir() -> Path:
    """Return the resolved invoice output directory, creating it if needed."""
    from app_config import get_billing_settings
    settings = get_billing_settings()
    raw = (settings.get("invoice_output_dir") or "").strip()
    path = Path(raw).expanduser() if raw else DATA_DIR / "invoices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _payment_text_fallback(billing_method: str | None, payment_method: str | None) -> str:
    """Derive a payment instruction string when none is stored on the company."""
    if billing_method == "bill.com":
        return "Arranged previously through Bill.com"
    if payment_method:
        pm = payment_method.strip()
        pm_lower = pm.lower()
        if pm_lower == "etrade":
            return "Payment via E*TRADE (ACH or wire transfer)"
        if pm_lower == "paypal":
            return "Payment via PayPal"
        if pm_lower == "venmo":
            return "Payment via Venmo"
        if pm_lower == "check":
            return "Payment via check"
        if pm_lower == "tipalti":
            return "Payment via Tipalti"
        return f"Payment via {pm}"
    return "Contact for payment details"


def _fmt_currency(val) -> str:
    if val is None:
        return "—"
    return f"${float(val):,.2f}"


def _generate_pdf(invoice_id: int) -> Path:
    """Build the PDF for the given invoice and return the file path."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )
        from reportlab.lib.enums import TA_RIGHT, TA_LEFT
    except ImportError as e:
        raise RuntimeError(f"reportlab not installed: {e}") from e

    provider = _get_provider()

    with get_db_connection(readonly=True) as db:
        inv = db.execute(
            """SELECT bi.*, bco.name AS company_name,
                      bco.billing_method, bco.payment_method,
                      bco.payment_instructions,
                      bco.ap_email, bco.cc_email
               FROM billing_invoices bi
               LEFT JOIN billing_companies bco ON bco.id = bi.company_id
               WHERE bi.id = ?""",
            (invoice_id,),
        ).fetchone()
        if not inv:
            raise ValueError(f"Invoice {invoice_id} not found")

        lines = db.execute(
            "SELECT * FROM billing_invoice_lines WHERE invoice_id = ? ORDER BY sort_order, id",
            (invoice_id,),
        ).fetchall()

    out_dir = _invoices_dir()
    inv_num = inv["invoice_number"] or f"INV-{invoice_id}"
    safe_num = inv_num.replace("/", "-").replace("\\", "-")
    period = inv["period_month"] or ""
    try:
        pdf_month = datetime.strptime(period, "%Y-%m").strftime("%B %Y")
    except ValueError:
        pdf_month = period
    pdf_provider = provider["provider_name"] or "Invoice"
    pdf_name = f"{pdf_provider} Invoice {safe_num}{' ' + pdf_month if pdf_month else ''}.pdf"
    out_path = out_dir / pdf_name

    # --- Color palette ---
    BRAND_GREEN      = colors.HexColor("#016630")
    TABLE_HEADER_BG  = colors.HexColor("#05DF72")
    DARK  = colors.HexColor("#1a1a1a")
    MID   = colors.HexColor("#555555")
    LIGHT = colors.HexColor("#999999")
    RULE  = colors.HexColor("#dddddd")
    TOTALS_BG = colors.HexColor("#f7f7f7")

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]

    def sty(name="Normal", **kw):
        base = styles.get(name, normal)
        return ParagraphStyle(name + str(id(kw)), parent=base, **kw)

    story = []

    # ---- Provider / company name block ----
    story.append(Paragraph(
        (provider["provider_name"] or "Invoice").upper(),
        sty(fontSize=22, fontName="Helvetica-Bold", textColor=BRAND_GREEN, spaceAfter=4),
    ))
    if provider["provider_contact_name"]:
        story.append(Paragraph(
            provider["provider_contact_name"],
            sty(fontSize=10, fontName="Helvetica", textColor=MID, spaceAfter=2),
        ))
    else:
        story.append(Paragraph(
            "Advisory Services",
            sty(fontSize=10, fontName="Helvetica", textColor=MID, spaceAfter=2),
        ))

    # Provider contact lines — render each non-empty address field on its own line
    for addr_line in filter(None, [
        provider["provider_address1"],
        provider["provider_address2"],
        provider["provider_city_state_zip"],
    ]):
        story.append(Paragraph(
            addr_line,
            sty(fontSize=8, fontName="Helvetica", textColor=LIGHT, spaceAfter=1),
        ))
    phone_email = "  ·  ".join(filter(None, [provider["provider_phone"], provider["provider_email"]]))
    if phone_email:
        story.append(Paragraph(
            phone_email,
            sty(fontSize=8, fontName="Helvetica", textColor=LIGHT, spaceAfter=2),
        ))

    story.append(HRFlowable(width="100%", thickness=1, color=RULE, spaceAfter=14))

    # ---- Invoice meta (right column) + Bill To (left column) ----
    invoice_date_str = inv["invoice_date"]  or ""
    due_date_str     = inv["due_date"]      or ""
    services_str     = inv["services_date"] or ""

    bill_to_name  = inv["company_name"] or ""
    bill_to_email = (inv["ap_email"] or "").strip()
    bill_to_lines_list = [bill_to_name]
    if bill_to_email and bill_to_email.lower() not in ("bill.com",):
        bill_to_lines_list.append(bill_to_email)

    meta_data = [
        ("INVOICE", inv_num, True),   # (label, value, is_invoice_number)
        ("Date",    invoice_date_str, False),
        ("Due",     due_date_str,     False),
    ]
    if services_str:
        meta_data.append(("Services through", services_str, False))

    meta_rows = []
    for label, value, is_inv_num in meta_data:
        label_p = Paragraph(label, sty(fontSize=8, textColor=LIGHT, fontName="Helvetica-Bold"))
        if is_inv_num:
            value_p = Paragraph(
                value,
                sty(fontSize=11, fontName="Helvetica-Bold", textColor=BRAND_GREEN, spaceAfter=6),
            )
        else:
            value_p = Paragraph(
                value,
                sty(fontSize=9, textColor=DARK, fontName="Helvetica-Bold"),
            )
        meta_rows.append([label_p, value_p])

    meta_table = Table(meta_rows, colWidths=[1.1 * inch, 2.1 * inch], hAlign="RIGHT")
    meta_table.setStyle(TableStyle([
        ("ROWPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN",      (0, 0), (0, -1), "RIGHT"),
        ("ALIGN",      (1, 0), (1, -1), "LEFT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))

    bill_to_p = [Paragraph("BILL TO", sty(fontSize=8, textColor=LIGHT, fontName="Helvetica-Bold",
                                           spaceAfter=3))]
    for bt_line in bill_to_lines_list:
        bill_to_p.append(Paragraph(bt_line, sty(fontSize=9, textColor=DARK, spaceAfter=1)))

    header_table = Table([[bill_to_p, meta_table]], colWidths=None)
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN",  (1, 0), (1, 0),   "RIGHT"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.25 * inch))

    # ---- Line items table ----
    col_headers = ["Description", "Date", "Unit Cost", "Hours", "Amount"]
    col_widths  = [2.8 * inch, 1.1 * inch, 0.9 * inch, 0.7 * inch, 0.9 * inch]

    RIGHT_HEADERS = {"Unit Cost", "Hours", "Amount"}
    header_row = [
        Paragraph(h, sty(fontSize=8, fontName="Helvetica-Bold", textColor=DARK,
                         alignment=TA_RIGHT if h in RIGHT_HEADERS else TA_LEFT))
        for h in col_headers
    ]

    table_rows = [header_row]
    for line in lines:
        desc   = line["description"] or ""
        date_r = line["date_range"]  or ""
        unit_c = _fmt_currency(line["unit_cost"]) if line["unit_cost"] else "—"
        qty    = f'{float(line["quantity"]):.2f}' if line["quantity"] is not None else "—"
        amt    = _fmt_currency(line["amount"])

        table_rows.append([
            Paragraph(desc, sty(fontSize=9, textColor=DARK)),
            Paragraph(date_r, sty(fontSize=9, textColor=MID)),
            Paragraph(unit_c, sty(fontSize=9, textColor=MID, alignment=TA_RIGHT)),
            Paragraph(qty,    sty(fontSize=9, textColor=MID, alignment=TA_RIGHT)),
            Paragraph(amt,    sty(fontSize=9, textColor=DARK, fontName="Helvetica-Bold",
                                  alignment=TA_RIGHT)),
        ])

    # Totals row
    total_hours = sum(
        float(line["quantity"]) for line in lines
        if line["quantity"] is not None
    )
    total_hours_str = f"{total_hours:.2f}" if total_hours else "—"
    table_rows.append([
        Paragraph("", normal),
        Paragraph("", normal),
        Paragraph("Total", sty(fontSize=9, fontName="Helvetica-Bold", textColor=DARK,
                               alignment=TA_RIGHT)),
        Paragraph(total_hours_str, sty(fontSize=9, fontName="Helvetica-Bold", textColor=DARK,
                                       alignment=TA_RIGHT)),
        Paragraph(_fmt_currency(inv["total_amount"]),
                  sty(fontSize=10, fontName="Helvetica-Bold", textColor=DARK,
                      alignment=TA_RIGHT)),
    ])

    lines_table = Table(table_rows, colWidths=col_widths)
    n_data = len(table_rows)
    lines_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("LINEBELOW",  (0, 0), (-1, 0), 0.75, RULE),
        ("ROWPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        *[("LINEBELOW", (0, i), (-1, i), 0.5, RULE) for i in range(1, n_data - 1)],
        ("LINEABOVE",  (0, n_data - 1), (-1, n_data - 1), 1, DARK),
        ("BACKGROUND", (0, n_data - 1), (-1, n_data - 1), TOTALS_BG),
    ]))

    story.append(lines_table)
    story.append(Spacer(1, 0.3 * inch))

    # ---- Payment section ----
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE, spaceAfter=8))
    story.append(Paragraph("PAYMENT", sty(fontSize=8, fontName="Helvetica-Bold",
                                           textColor=LIGHT, spaceAfter=4)))

    pay_text = (inv["payment_instructions"] or "").strip() or \
               _payment_text_fallback(inv["billing_method"], inv["payment_method"])
    story.append(Paragraph(pay_text, sty(fontSize=9, textColor=MID)))

    if inv["notes"]:
        story.append(Spacer(1, 0.15 * inch))
        story.append(Paragraph("NOTES", sty(fontSize=8, fontName="Helvetica-Bold",
                                             textColor=LIGHT, spaceAfter=4)))
        story.append(Paragraph(inv["notes"], sty(fontSize=9, textColor=MID)))

    doc.build(story)
    return out_path


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/invoices/dir")
def get_invoices_dir():
    """Return the resolved invoice output directory path."""
    return {"path": str(_invoices_dir())}


@router.post("/invoices/{invoice_id}/pdf", status_code=200)
def generate_invoice_pdf(invoice_id: int):
    """Generate a PDF for the given invoice and save path to billing_invoices.pdf_path."""
    try:
        out_path = _generate_pdf(invoice_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("PDF generation failed for invoice %s", invoice_id)
        raise HTTPException(status_code=500, detail=str(e))

    with get_write_db() as db:
        db.execute(
            "UPDATE billing_invoices SET pdf_path = ? WHERE id = ?",
            (str(out_path), invoice_id),
        )
        db.commit()

    return {"ok": True, "pdf_path": str(out_path)}


@router.get("/invoices/{invoice_id}/pdf")
def download_invoice_pdf(invoice_id: int):
    """Download the generated PDF for an invoice."""
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT invoice_number, period_month, pdf_path FROM billing_invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_path = row["pdf_path"]
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(
            status_code=404,
            detail="PDF not yet generated. POST /billing/invoices/{id}/pdf first.",
        )

    inv_num = (row["invoice_number"] or f"INV-{invoice_id}").replace("/", "-")
    try:
        dl_month = datetime.strptime(row["period_month"] or "", "%Y-%m").strftime("%B %Y")
    except ValueError:
        dl_month = row["period_month"] or ""
    dl_provider = (_get_provider()["provider_name"] or "Invoice")
    dl_filename = f"{dl_provider} Invoice {inv_num}{' ' + dl_month if dl_month else ''}.pdf"
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=dl_filename,
    )


# ---------------------------------------------------------------------------
# Email compose / send / draft
# ---------------------------------------------------------------------------

_DEFAULT_EMAIL_SUBJECT = "Invoice {{invoice_number}} from {{provider_name}} for services for {{month}}"
_DEFAULT_EMAIL_BODY = (
    "Hi,\n\n"
    "Please find attached invoice {{invoice_number}} for services through {{month}}.\n\n"
    "Amount due: {{total_amount}}\n"
    "Due date: {{due_date}}\n\n"
    "Thank you,\n{{sender_name}}\n{{provider_name}}"
)


def _substitute(template: str, variables: dict) -> str:
    def replacer(m: re.Match) -> str:
        return variables.get(m.group(1), m.group(0))
    return re.sub(r"\{\{(\w+)\}\}", replacer, template)


def _compose_invoice_email(invoice_id: int) -> dict:
    """Build a composed email dict for the given invoice (no side effects)."""
    with get_db_connection(readonly=True) as db:
        inv = db.execute(
            """SELECT bi.*, bco.name AS company_name, bco.ap_email, bco.cc_email,
                      bco.email_subject, bco.email_body
               FROM billing_invoices bi
               LEFT JOIN billing_companies bco ON bco.id = bi.company_id
               WHERE bi.id = ?""",
            (invoice_id,),
        ).fetchone()
        if not inv:
            raise ValueError(f"Invoice {invoice_id} not found")

        client_names = [
            r[0] for r in db.execute(
                """SELECT DISTINCT bc.name
                   FROM billing_invoice_lines bil
                   JOIN billing_sessions bs ON bs.invoice_line_id = bil.id
                   JOIN billing_clients bc ON bc.id = bs.client_id
                   WHERE bil.invoice_id = ?""",
                (invoice_id,),
            ).fetchall()
        ]

    inv_num = inv["invoice_number"] or f"INV-{invoice_id}"
    period = inv["period_month"] or ""  # YYYY-MM
    try:
        month_str = datetime.strptime(period, "%Y-%m").strftime("%B %Y")
    except ValueError:
        month_str = period

    total = inv["total_amount"]
    total_str = f"${float(total):,.2f}" if total is not None else "—"
    due = inv["due_date"] or "—"
    company = inv["company_name"] or ""
    clients_str = ", ".join(client_names) if client_names else company

    provider = _get_provider()
    provider_name = provider["provider_name"] or "Invoice"

    # Prefer the stored contact name, fall back to profile user_name, then provider_name
    sender_name = provider["provider_contact_name"]
    if not sender_name:
        try:
            from app_config import load_config
            sender_name = load_config().get("profile", {}).get("user_name", "") or provider_name
        except Exception:
            sender_name = provider_name

    variables = {
        "invoice_number": inv_num,
        "month": month_str,
        "client_names": clients_str,
        "company_name": company,
        "total_amount": total_str,
        "due_date": due,
        "provider_name": provider_name,
        "sender_name": sender_name,
    }

    subject_tpl = (inv["email_subject"] or "").strip() or _DEFAULT_EMAIL_SUBJECT
    body_tpl = (inv["email_body"] or "").strip() or _DEFAULT_EMAIL_BODY

    safe_num = inv_num.replace("/", "-").replace("\\", "-")
    return {
        "invoice_id": invoice_id,
        "invoice_number": inv_num,
        "to": inv["ap_email"] or "",
        "cc": inv["cc_email"] or "",
        "subject": _substitute(subject_tpl, variables),
        "body": _substitute(body_tpl, variables),
        "pdf_filename": f"{provider_name} Invoice {safe_num}{' ' + month_str if month_str else ''}.pdf",
        "pdf_path": inv["pdf_path"] or None,
    }


def _build_mime_with_attachment(to: str, subject: str, body: str,
                                 cc: str | None, pdf_path: str | None,
                                 pdf_filename: str) -> str:
    """Build a base64url-encoded RFC 2822 message suitable for the Gmail API."""
    import email.policy
    from email.message import EmailMessage

    msg = EmailMessage(policy=email.policy.SMTP)
    msg["to"] = to
    msg["subject"] = subject
    if cc:
        msg["cc"] = cc
    msg.set_content(body)

    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
        msg.add_attachment(
            pdf_data,
            maintype="application",
            subtype="pdf",
            filename=pdf_filename,
        )

    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


class InvoiceSendBody(BaseModel):
    to: str
    cc: str = ""
    subject: str
    body: str


@router.get("/invoices/{invoice_id}/compose")
def compose_invoice_email(invoice_id: int):
    """Return a composed email preview for the given invoice."""
    try:
        return _compose_invoice_email(invoice_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/invoices/{invoice_id}/send-draft")
def save_invoice_draft(invoice_id: int, payload: InvoiceSendBody):
    """Save the invoice email as a Gmail draft (no PDF attached)."""
    try:
        from connectors.google_auth import get_google_credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Gmail not available: {e}")

    creds = get_google_credentials()
    if not creds:
        raise HTTPException(status_code=503, detail="Gmail not authenticated")

    service = build("gmail", "v1", credentials=creds)

    # Fetch pdf_path for attachment
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT invoice_number, period_month, pdf_path FROM billing_invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv_num = (row["invoice_number"] or f"INV-{invoice_id}").replace("/", "-")
    pdf_path = row["pdf_path"]
    try:
        send_month = datetime.strptime(row["period_month"] or "", "%Y-%m").strftime("%B %Y")
    except ValueError:
        send_month = row["period_month"] or ""
    send_provider = (_get_provider()["provider_name"] or "Invoice")
    send_pdf_filename = f"{send_provider} Invoice {inv_num}{' ' + send_month if send_month else ''}.pdf"

    raw = _build_mime_with_attachment(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        cc=payload.cc or None,
        pdf_path=pdf_path,
        pdf_filename=send_pdf_filename,
    )

    try:
        result = service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
    except Exception as e:
        logger.exception("Failed to create Gmail draft for invoice %s", invoice_id)
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "draft_id": result.get("id"), "message_id": result.get("message", {}).get("id")}


@router.post("/invoices/{invoice_id}/send-email")
def send_invoice_email(invoice_id: int, payload: InvoiceSendBody):
    """Send the invoice email via Gmail with PDF attached, then mark invoice as sent."""
    try:
        from connectors.google_auth import get_google_credentials
        from googleapiclient.discovery import build
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Gmail not available: {e}")

    creds = get_google_credentials()
    if not creds:
        raise HTTPException(status_code=503, detail="Gmail not authenticated")

    service = build("gmail", "v1", credentials=creds)

    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT invoice_number, period_month, pdf_path FROM billing_invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv_num = (row["invoice_number"] or f"INV-{invoice_id}").replace("/", "-")
    pdf_path = row["pdf_path"]

    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(
            status_code=400,
            detail="PDF not generated. Generate the PDF first before sending.",
        )

    try:
        send_month = datetime.strptime(row["period_month"] or "", "%Y-%m").strftime("%B %Y")
    except ValueError:
        send_month = row["period_month"] or ""
    send_provider = (_get_provider()["provider_name"] or "Invoice")
    send_pdf_filename = f"{send_provider} Invoice {inv_num}{' ' + send_month if send_month else ''}.pdf"

    raw = _build_mime_with_attachment(
        to=payload.to,
        subject=payload.subject,
        body=payload.body,
        cc=payload.cc or None,
        pdf_path=pdf_path,
        pdf_filename=send_pdf_filename,
    )

    try:
        result = service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
    except Exception as e:
        logger.exception("Failed to send invoice email %s", invoice_id)
        raise HTTPException(status_code=500, detail=str(e))

    sent_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with get_write_db() as db:
        db.execute(
            "UPDATE billing_invoices SET status = 'sent', sent_at = ? WHERE id = ?",
            (sent_at, invoice_id),
        )
        db.commit()

    return {
        "ok": True,
        "message_id": result.get("id"),
        "thread_id": result.get("threadId"),
        "sent_at": sent_at,
    }
