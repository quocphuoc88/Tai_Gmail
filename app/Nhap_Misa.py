import os
import re
import time
import email
from email import policy

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

# ==========================================
# THƯ MỤC
# ==========================================
EML_FOLDER = r"C:\Users\Admin\Desktop\New folder"
SAVE_FOLDER = r"C:\Users\Admin\Desktop\New folder"

os.makedirs(SAVE_FOLDER, exist_ok=True)

# ==========================================
# CHROME OPTIONS
# ==========================================
chrome_options = Options()

prefs = {
    "download.default_directory": SAVE_FOLDER,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "plugins.always_open_pdf_externally": True,
    "safebrowsing.enabled": True
}

chrome_options.add_experimental_option("prefs", prefs)

driver = webdriver.Chrome(options=chrome_options)

# ==========================================
# ĐỌC EMAIL
# ==========================================
def read_eml_text(eml_path):

    with open(eml_path, "rb") as f:

        msg = email.message_from_binary_file(
            f,
            policy=policy.default
        )

    text = ""

    for part in msg.walk():

        ctype = part.get_content_type()

        try:
            content = part.get_content()
        except:
            continue

        if ctype in ["text/plain", "text/html"]:
            text += "\n" + str(content)

    return text

# ==========================================
# TÌM MÃ TRA CỨU
# ==========================================
def find_ma_tra_cuu(text):

    patterns = [

        r"(?:Mã tra cứu|Ma tra cuu)[^A-Z0-9]*([A-Z0-9]{8,25})",

        r"(?:mã số|ma so)[^A-Z0-9]*([A-Z0-9]{8,25})",

        r"sc=([A-Z0-9]{8,25})"
    ]

    for p in patterns:

        m = re.search(p, text, re.IGNORECASE)

        if m:
            return m.group(1)

    return None

# ==========================================
# CHỜ DOWNLOAD XONG
# ==========================================
def wait_download(timeout=60):

    start = time.time()

    while True:

        downloading = False

        for f in os.listdir(SAVE_FOLDER):

            if f.endswith(".crdownload"):
                downloading = True
                break

        if not downloading:
            return True

        if time.time() - start > timeout:
            return False

        time.sleep(1)

# ==========================================
# CLICK MENU TẢI
# ==========================================
def click_download_menu():

    btn_menu = driver.find_element(
        By.XPATH,
        "//*[contains(text(),'Tải hóa đơn')]"
    )

    btn_menu.click()

    time.sleep(2)

# ==========================================
# TẢI PDF
# ==========================================
def download_pdf():

    click_download_menu()

    btn_pdf = driver.find_element(
        By.XPATH,
        "//*[contains(text(),'Tải hóa đơn dạng PDF')]"
    )

    btn_pdf.click()

    print("ĐÃ CLICK PDF")

    ok = wait_download()

    if ok:
        print("PDF OK")
    else:
        print("PDF TIMEOUT")

# ==========================================
# TẢI XML
# ==========================================
def download_xml():

    click_download_menu()

    btn_xml = driver.find_element(
        By.XPATH,
        "//*[contains(text(),'Tải hóa đơn dạng XML')]"
    )

    btn_xml.click()

    print("ĐÃ CLICK XML")

    ok = wait_download()

    if ok:
        print("XML OK")
    else:
        print("XML TIMEOUT")

# ==========================================
# LOOP EMAIL
# ==========================================
for file in os.listdir(EML_FOLDER):

    if not file.lower().endswith(".eml"):
        continue

    print("=" * 60)
    print("ĐANG XỬ LÝ:", file)

    full_path = os.path.join(EML_FOLDER, file)

    text = read_eml_text(full_path)

    ma_tra_cuu = find_ma_tra_cuu(text)

    if not ma_tra_cuu:

        print("KHÔNG TÌM THẤY MÃ")
        continue

    print("MÃ:", ma_tra_cuu)

    # ==========================================
    # MỞ WEB
    # ==========================================
    url = f"https://www.meinvoice.vn/tra-cuu/?sc={ma_tra_cuu}"

    print(url)

    driver.get(url)

    time.sleep(8)

    try:

        # ==========================================
        # TẢI PDF
        # ==========================================
        download_pdf()

        time.sleep(3)

        # ==========================================
        # TẢI XML
        # ==========================================
        download_xml()

    except Exception as e:

        print("LỖI:", e)

    time.sleep(5)

driver.quit()

print("DONE")