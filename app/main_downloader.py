
import os
import re
import csv
import requests
import base64
from datetime import datetime
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def get_service():
    creds = None
    if os.path.exists('tokenGP.json'):
        creds = Credentials.from_authorized_user_file('tokenGP.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials_GP.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('tokenGP.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def download_file_from_link(url, save_dir, filename, logger=None):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, stream=True, headers=headers, timeout=15)
        if response.status_code == 200:
            filepath = os.path.join(save_dir, filename)
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            if logger:
                logger(f"✅ Đã tải: {filename}")
            else:
                print(f"✅ Đã tải: {filename}")
            return filename
        else:
            if logger:
                logger(f"⚠️ Không tải được {url} - Mã: {response.status_code}")
            else:
                print(f"⚠️ Không tải được {url} - Mã: {response.status_code}")
    except Exception as e:
        if logger:
            logger(f"⚠️ Lỗi khi tải link: {e}")
        else:
            print(f"⚠️ Lỗi khi tải link: {e}")
    return None

def download_attachments(service, message, save_dir, logger=None):
    payload = message.get('payload', {})
    parts = payload.get('parts', [])
    has_attachment = False
    attachments = []

    for part in parts:
        filename = part.get('filename')
        body = part.get('body', {})
        if filename and 'attachmentId' in body:
            att_id = body['attachmentId']
            att = service.users().messages().attachments().get(
                userId='me', messageId=message['id'], id=att_id).execute()
            file_data = base64.urlsafe_b64decode(att['data'].encode('UTF-8'))
            filepath = os.path.join(save_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(file_data)
            if logger:
                logger(f"📎 Đã lưu file đính kèm: {filename}")
            else:
                print(f"📎 Đã lưu file đính kèm: {filename}")
            has_attachment = True
            attachments.append(filename)
    return has_attachment, attachments

def extract_invoice_number(soup):
    try:
        for span in soup.find_all("span"):
            if "Hóa đơn mới số" in span.get_text():
                match = re.search(r'(\d{6,})', span.get_text())
                if match:
                    return match.group(1)
        for line in soup.get_text().splitlines():
            if "Hóa đơn mới số" in line:
                match = re.search(r'(\d{6,})', line)
                if match:
                    return match.group(1)
    except:
        pass
    return "invoice"

def extract_company_name(soup):
    try:
        for span in soup.find_all("span"):
            if "Tên khách hàng" in span.get_text():
                match = re.search(r'Tên khách hàng[:：\-]?\s*(.+)', span.get_text())
                if match:
                    return match.group(1).strip()
        text = soup.get_text()
        match = re.search(r'Tên khách hàng[:：\-]?\s*(.+)', text)
        if match:
            return match.group(1).strip()
    except:
        pass
    return "Không rõ"

def extract_links(soup):
    pdf_url = xml_url = None
    for a in soup.find_all('a', href=True):
        href = a['href'].lower()
        if 'pdfdownload' in href or href.endswith('.pdf'):
            pdf_url = a['href']
        elif 'getinvoice' in href or href.endswith('.xml'):
            xml_url = a['href']
    return pdf_url, xml_url

def write_log(log_file, row):
    file_exists = os.path.isfile(log_file)
    with open(log_file, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Số hóa đơn', 'Tên công ty', 'Ngày email', 'Tên file PDF', 'Tên file XML'])
        writer.writerow(row)

def mark_email_as_read(service, message_id):
    service.users().messages().modify(
        userId='me',
        id=message_id,
        body={'removeLabelIds': ['UNREAD']}
    ).execute()

def process_email(service, message, save_dir, log_file, logger=None):
    os.makedirs(save_dir, exist_ok=True)

    msg_date = message['internalDate']
    date_str = datetime.fromtimestamp(int(msg_date)/1000).strftime('%Y-%m-%d')

    has_attach, attachments = download_attachments(service, message, save_dir, logger)
    if has_attach:
        for att in attachments:
            write_log(log_file, ["(từ file đính kèm)", "Không rõ", date_str, att if att.endswith('.pdf') else "", att if att.endswith('.xml') else ""])
        mark_email_as_read(service, message['id'])
        return

    payload = message.get('payload', {})
    parts = payload.get('parts', [])
    html_data = None

    for part in parts:
        if part.get('mimeType') == 'text/html':
            html_data = part.get('body', {}).get('data')
            break

    if html_data:
        html_decoded = base64.urlsafe_b64decode(html_data).decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html_decoded, 'html.parser')

        invoice_number = extract_invoice_number(soup)
        company_name = extract_company_name(soup)
        pdf_url, xml_url = extract_links(soup)

        pdf_file = xml_file = ""

        if pdf_url:
            pdf_file = f"{invoice_number}.pdf"
            download_file_from_link(pdf_url, save_dir, pdf_file, logger)
        else:
            if logger:
                logger("⚠️ Không tìm thấy link PDF")
            else:
                print("⚠️ Không tìm thấy link PDF")

        if xml_url:
            xml_file = f"{invoice_number}.xml"
            download_file_from_link(xml_url, save_dir, xml_file, logger)
        else:
            if logger:
                logger("⚠️ Không tìm thấy link XML")
            else:
                print("⚠️ Không tìm thấy link XML")

        write_log(log_file, [invoice_number, company_name, date_str, pdf_file, xml_file])
    else:
        if logger:
            logger("⚠️ Email không chứa nội dung HTML")
        else:
            print("⚠️ Email không chứa nội dung HTML")

    mark_email_as_read(service, message['id'])

def process_invoices(service, query, save_dir, log_file, logger=None):
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])

    if not messages:
        if logger:
            logger("⚠️ Không tìm thấy email nào.")
        else:
            print("⚠️ Không tìm thấy email nào.")
        return

    for msg in messages:
        msg_data = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
        process_email(service, msg_data, save_dir, log_file, logger)
