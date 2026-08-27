"""
Kiro Refresh Token Generator (Google OAuth - undetected-chromedriver)

Flow:
  1. Generate PKCE (code_verifier + code_challenge)
  2. Navigate ke Kiro login URL (idp=Google)
  3. Login Google (email + password + TOTP optional)
  4. Auto-solve CAPTCHA (ddddocr + pytesseract, NO API key needed)
  5. Auto OTP verification via Litensi.id (Google SMS, Indonesia)
  6. Capture callback kiro://...?code=...
  7. Exchange code -> refreshToken
  8. Output ke refresh_tokens.txt

Input:  accounts.txt (format: email:password[:totp_secret])
Output: refresh_tokens.txt (format: refreshToken per baris)
"""

import base64
import hashlib
import hmac as hmac_mod
import io
import json
import os
import random
import re
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, urlencode

# Force UTF-8
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ── Auto-detect Chrome version ───────────────────────────
def detect_chrome_version():
    import subprocess
    try:
        result = subprocess.run(
            ["google-chrome-stable", "--version"],
            capture_output=True, text=True, timeout=10
        )
        ver_str = result.stdout.strip()
        match = re.search(r'(\d+)\.', ver_str)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["google-chrome", "--version"],
            capture_output=True, text=True, timeout=10
        )
        ver_str = result.stdout.strip()
        match = re.search(r'(\d+)\.', ver_str)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["chromium-browser", "--version"],
            capture_output=True, text=True, timeout=10
        )
        ver_str = result.stdout.strip()
        match = re.search(r'(\d+)\.', ver_str)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None

CHROME_VERSION = detect_chrome_version()

# ── File Logger ──────────────────────────────────────────
_file_log_lock = threading.Lock()
_log_file_handle = None

def init_log_file(script_dir):
    global _log_file_handle
    log_path = os.path.join(script_dir, LOG_FILE)
    _log_file_handle = open(log_path, "a", encoding="utf-8")
    _log_file_handle.write(f"\n{'='*60}\n")
    _log_file_handle.write(f"KIRO AI Session: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    _log_file_handle.write(f"{'='*60}\n")
    _log_file_handle.flush()

def log_to_file(msg):
    if _log_file_handle:
        with _file_log_lock:
            try:
                _log_file_handle.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
                _log_file_handle.flush()
            except Exception:
                pass

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        NoSuchElementException,
        TimeoutException,
        ElementNotInteractableException,
        StaleElementReferenceException,
        WebDriverException,
    )
except ImportError:
    import subprocess
    print("Auto-installing: undetected-chromedriver selenium...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--ignore-installed",
                    "undetected-chromedriver", "selenium"], capture_output=True)
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait, Select
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import (
            NoSuchElementException,
            TimeoutException,
            ElementNotInteractableException,
            StaleElementReferenceException,
            WebDriverException,
        )
    except ImportError:
        print("ERROR: Failed to install undetected-chromedriver/selenium")
        print("Run manually: bash install.sh")
        sys.exit(1)

try:
    import httpx
except ImportError:
    import subprocess
    print("Auto-installing: httpx...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--ignore-installed", "httpx"],
                   capture_output=True)
    try:
        import httpx
    except ImportError:
        print("ERROR: Failed to install httpx. Run: bash install.sh")
        sys.exit(1)

try:
    from pyvirtualdisplay import Display
    HAS_VDISPLAY = True
except ImportError:
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--ignore-installed", "pyvirtualdisplay"],
                       capture_output=True)
        from pyvirtualdisplay import Display
        HAS_VDISPLAY = True
    except ImportError:
        HAS_VDISPLAY = False

# ── CAPTCHA Solver imports ──
try:
    import ddddocr
    HAS_DDDDOCR = True
except ImportError:
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--ignore-installed", "ddddocr"],
                       capture_output=True)
        import ddddocr
        HAS_DDDDOCR = True
    except ImportError:
        HAS_DDDDOCR = False

try:
    import pytesseract
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    HAS_TESSERACT = True
except ImportError:
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--ignore-installed",
                        "pytesseract", "Pillow"], capture_output=True)
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        HAS_TESSERACT = True
    except ImportError:
        HAS_TESSERACT = False

try:
    import speech_recognition as sr
    HAS_SPEECH = True
except ImportError:
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--ignore-installed", "SpeechRecognition"],
                       capture_output=True)
        import speech_recognition as sr
        HAS_SPEECH = True
    except ImportError:
        HAS_SPEECH = False

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    try:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "--ignore-installed", "pydub"],
                       capture_output=True)
        from pydub import AudioSegment
        HAS_PYDUB = True
    except ImportError:
        HAS_PYDUB = False


# ── Config ──────────────────────────────────────────────
KIRO_AUTH_SERVICE = "https://prod.us-east-1.auth.desktop.kiro.dev"
KIRO_LOGIN_URL = f"{KIRO_AUTH_SERVICE}/login"
KIRO_TOKEN_URL = f"{KIRO_AUTH_SERVICE}/oauth/token"
KIRO_REDIRECT_URI = "kiro://kiro.kiroAgent/authenticate-success"
SOCIAL_PROFILE_ARN = "arn:aws:codewhisperer:us-east-1:699475941385:profile/EHGA3GRVQMUK"

CHROME_VERSION = detect_chrome_version() if CHROME_VERSION is None else CHROME_VERSION
CAPTCHA_MAX_RETRIES = 8
CAPTCHA_DEBUG_DIR = "captcha_debug"
DRIVER_MAX_RETRIES = 3
LOG_FILE = "kiro.log"
RECAPTCHA_AUDIO_MAX_RETRIES = 5

# ── Litensi OTP Config ──────────────────────────────────
LITENSI_API_KEY = ""
LITENSI_API_ID = "3192"
LITENSI_BASE_URL = "https://litensi.id/api/sms/handler_api.php"
LITENSI_SERVICE = "go"
LITENSI_COUNTRY = "6"
LITENSI_OPERATOR = "any"
LITENSI_OTP_TIMEOUT = 90
LITENSI_MAX_RETRIES = 8
LITENSI_RETRY_SMS_AFTER = 45
LITENSI_RETRY_SMS_AFTER_2 = 75


# ── Litensi OTP Client ──────────────────────────────────
class LitensiOTP:
    """Client untuk Litensi.id SMS Activation API."""

    def __init__(self, api_key, log_fn=None):
        self.api_key = api_key
        self.log = log_fn or (lambda x: None)

    def _request(self, params):
        params["api_key"] = self.api_key
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(LITENSI_BASE_URL, params=params)
                return resp.text.strip()
        except Exception as e:
            return f"ERROR:{e}"

    def get_balance(self):
        resp = self._request({"action": "getBalance"})
        if resp.startswith("ACCESS_BALANCE:"):
            return int(resp.split(":")[1])
        return None

    def get_prices(self, service=LITENSI_SERVICE, country=LITENSI_COUNTRY):
        resp = self._request({"action": "getPrices", "service": service, "country": country})
        try:
            data = json.loads(resp)
            prices = data.get("data", {}).get(service, {}).get(country, {}).get("map", {})
            return {int(k): int(v) for k, v in prices.items()}
        except Exception:
            return {}

    def order_number(self, service=LITENSI_SERVICE, country=LITENSI_COUNTRY, operator=LITENSI_OPERATOR):
        params = {
            "action": "getNumber",
            "service": service,
            "country": country,
            "operator": operator,
        }
        resp = self._request(params)
        if resp.startswith("ACCESS_NUMBER:"):
            parts = resp.split(":")
            return {"id": parts[1], "phone": parts[2]}
        self.log(f"Order failed: {resp}")
        return None

    def get_status(self, activation_id):
        resp = self._request({"action": "getStatus", "id": activation_id})
        return resp

    def set_status(self, activation_id, status):
        resp = self._request({"action": "setStatus", "id": activation_id, "status": str(status)})
        return resp

    def cancel(self, activation_id):
        return self.set_status(activation_id, 8)

    def finish(self, activation_id):
        return self.set_status(activation_id, 6)

    def retry_sms(self, activation_id):
        return self.set_status(activation_id, 3)

    def wait_for_otp(self, activation_id, timeout=LITENSI_OTP_TIMEOUT):
        start = time.time()
        poll_count = 0
        retry_sent = False
        retry2_sent = False
        while time.time() - start < timeout:
            poll_count += 1
            elapsed = int(time.time() - start)
            resp = self.get_status(activation_id)

            if resp.startswith("STATUS_OK:"):
                code = resp.split(":", 1)[1].strip()
                self.log(f"OTP received! Code: {code} (after {elapsed}s, {poll_count} polls)")
                return code
            elif resp.startswith("STATUS_WAIT_RETRY:"):
                code = resp.split(":", 1)[1].strip()
                self.log(f"OTP retry code received: {code} (after {elapsed}s)")
                return code
            elif resp == "STATUS_WAIT_CODE":
                if poll_count % 3 == 0:
                    self.log(f"Waiting for OTP... {elapsed}s elapsed ({poll_count} polls)")
                if not retry_sent and elapsed >= LITENSI_RETRY_SMS_AFTER:
                    self.log(f"No OTP after {elapsed}s, requesting SMS retry #1 (status=3)...")
                    retry_resp = self.retry_sms(activation_id)
                    self.log(f"Retry SMS #1 response: {retry_resp}")
                    retry_sent = True
                elif retry_sent and not retry2_sent and elapsed >= LITENSI_RETRY_SMS_AFTER_2:
                    self.log(f"Still no OTP after {elapsed}s, requesting SMS retry #2 (status=3)...")
                    retry_resp2 = self.retry_sms(activation_id)
                    self.log(f"Retry SMS #2 response: {retry_resp2}")
                    retry2_sent = True
            elif resp == "STATUS_CANCEL":
                self.log("Activation was cancelled by provider")
                return None
            elif resp == "NO_ACTIVATION":
                self.log("Activation not found on Litensi")
                return None
            else:
                self.log(f"Status: {resp} (after {elapsed}s)")
            time.sleep(3)
        self.log(f"OTP timeout after {timeout}s ({poll_count} polls)")
        return None

    def order_and_get_otp(self, log):
        """Order number, return (activation_id, phone_number)."""
        balance = self.get_balance()
        if balance is not None:
            log(f"Litensi balance: {balance} IDR")
        else:
            log("Failed to get Litensi balance")
            return None, None

        log(f"Ordering number: service={LITENSI_SERVICE}, country={LITENSI_COUNTRY}, operator={LITENSI_OPERATOR}")
        result = self.order_number()
        if not result:
            log("No number available")
            return None, None

        activation_id = result["id"]
        phone = result["phone"]
        log(f"Number ordered: ID={activation_id}, Phone={phone}")
        return activation_id, phone


# ── Phone Verification Handler ──────────────────────────
def handle_phone_verification(driver, log, script_dir, email):
    """
    Handle Google phone verification challenge using Litensi OTP.
    Returns True if verification succeeded.
    """
    otp_client = LitensiOTP(LITENSI_API_KEY, log_fn=log)

    for attempt in range(1, LITENSI_MAX_RETRIES + 1):
        log(f"Phone verification attempt {attempt}/{LITENSI_MAX_RETRIES}")

        activation_id, phone = otp_client.order_and_get_otp(log)
        if not activation_id:
            log("Failed to order number, retrying...")
            time.sleep(3)
            continue

        phone_clean = phone.lstrip("+")
        if phone_clean.startswith("62"):
            phone_without_country = phone_clean[2:]
        elif phone_clean.startswith("0"):
            phone_without_country = phone_clean[1:]
        else:
            phone_without_country = phone_clean

        log(f"Phone: +62 {phone_without_country} (raw: {phone})")

        try:
            filled = fill_phone_number_on_google(driver, phone_without_country, log)
            if not filled:
                log("Failed to fill phone number on Google")
                otp_client.cancel(activation_id)
                time.sleep(2)
                continue

            time.sleep(5)

            current_url_after_phone = ""
            try:
                current_url_after_phone = driver.current_url
            except Exception:
                pass

            try:
                error_txt = driver.execute_script("return document.body ? document.body.innerText : '';")
            except Exception:
                error_txt = ""

            phone_error_patterns = [
                "cannot be used for verification",
                "tidak dapat digunakan",
                "invalid phone",
                "nomor tidak valid",
                "phone number is invalid",
                "This phone number format is not recognized",
                "Please enter a valid phone number",
                "not a valid",
                "This number can no longer be used",
                "number has been used too many times",
            ]
            phone_error = None
            for pat in phone_error_patterns:
                if pat.lower() in error_txt.lower():
                    phone_error = pat
                    break

            if phone_error:
                log(f"Google rejected phone number: {phone_error}")
                otp_client.cancel(activation_id)
                time.sleep(2)
                continue

            # Check if OTP entry page is shown
            otp_page_indicators = [
                "challenge/ipp" in current_url_after_phone,
                "Enter the code" in error_txt,
                "Masukkan kode" in error_txt,
                "code" in error_txt.lower() and "sent" in error_txt.lower(),
                "we sent" in error_txt.lower(),
                "kami telah mengirim" in error_txt.lower(),
                "kode telah dikirim" in error_txt.lower(),
            ]

            try:
                otp_inputs_check = driver.find_elements(By.CSS_SELECTOR,
                    'input[type="tel"], input[name="code"], input[id="code"], '
                    'input[autocomplete="one-time-code"], input[name="Pin"]'
                )
                otp_visible = any(inp.is_displayed() for inp in otp_inputs_check)
            except Exception:
                otp_visible = False

            if otp_visible or any(otp_page_indicators):
                log("Phone accepted by Google! OTP entry page detected.")
            else:
                log(f"Phone submission unclear. URL: {current_url_after_phone[:80]}")
                log(f"Page text: {error_txt[:200]}")

            # Poll Litensi API for OTP code (with auto retry_sms after 45s)
            log(f"Polling Litensi API for OTP (timeout {LITENSI_OTP_TIMEOUT}s, retry SMS after {LITENSI_RETRY_SMS_AFTER}s)...")
            otp_code = otp_client.wait_for_otp(activation_id)
            if not otp_code:
                log(f"No OTP received after {LITENSI_OTP_TIMEOUT}s, cancelling and trying new number...")
                otp_client.cancel(activation_id)
                time.sleep(2)
                continue

            log(f"OTP received from Litensi: {otp_code}")
            entered = enter_otp_on_google(driver, otp_code, log)
            if not entered:
                log("Failed to enter OTP on Google page")
                otp_client.cancel(activation_id)
                time.sleep(2)
                continue

            time.sleep(5)

            # Check if OTP was accepted
            try:
                post_otp_url = driver.current_url
                post_otp_text = driver.execute_script("return document.body ? document.body.innerText : '';")
            except Exception:
                post_otp_url = ""
                post_otp_text = ""

            otp_error_patterns = [
                "invalid code",
                "kode tidak valid",
                "wrong code",
                "kode salah",
                "try again",
                "coba lagi",
                "couldn't verify",
                "tidak dapat memverifikasi",
            ]
            otp_error = None
            for pat in otp_error_patterns:
                if pat.lower() in post_otp_text.lower():
                    otp_error = pat
                    break

            if otp_error:
                log(f"OTP rejected by Google: {otp_error}")
                otp_client.cancel(activation_id)
                time.sleep(2)
                continue

            if "accounts.google.com" not in post_otp_url or "challenge" not in post_otp_url:
                log("OTP verification appears successful! Page moved past challenge.")
                otp_client.finish(activation_id)
                return True

            log("OTP submitted, page may have advanced. Finishing activation.")
            otp_client.finish(activation_id)
            return True

        except Exception as e:
            log(f"Phone verification error: {e}")
            try:
                otp_client.cancel(activation_id)
            except Exception:
                pass
            time.sleep(2)

    log(f"Phone verification failed after {LITENSI_MAX_RETRIES} attempts")
    return False


def select_indonesia_country(driver, log):
    """Change country region to Indonesia (+62) on Google phone verification page."""
    country_selected = False

    # Method 1: Native <select> element with Select class
    try:
        selects = driver.find_elements(By.CSS_SELECTOR, 'select')
        for sel_el in selects:
            if not sel_el.is_displayed():
                continue
            try:
                select_obj = Select(sel_el)
                options = select_obj.options
                for opt in options:
                    val = opt.get_attribute("value") or ""
                    text = opt.get_attribute("textContent") or ""
                    if val == "62" or "Indonesia" in text or "+62" in text:
                        select_obj.select_by_value(val)
                        country_selected = True
                        log(f"Selected Indonesia (+62) via <select> (value={val})")
                        time.sleep(1)
                        return True
            except Exception:
                # Fallback: click option directly
                try:
                    options = sel_el.find_elements(By.TAG_NAME, 'option')
                    for opt in options:
                        val = opt.get_attribute("value") or ""
                        text = opt.get_attribute("textContent") or ""
                        if val == "62" or "Indonesia" in text or "+62" in text:
                            opt.click()
                            country_selected = True
                            log(f"Selected Indonesia (+62) via <select> click (value={val})")
                            time.sleep(1)
                            return True
                except Exception:
                    pass
    except Exception:
        pass

    # Method 2: Google custom dropdown (div[role=combobox] or div[role=listbox])
    if not country_selected:
        try:
            dropdowns = driver.find_elements(By.CSS_SELECTOR,
                'div[role="combobox"], div[role="listbox"], div[jsname="CJsAMe"], '
                'div[aria-haspopup="listbox"], div[aria-haspopup="combobox"], '
                'div[class*="country"], div[data-value*="62"]'
            )
            for dd in dropdowns:
                try:
                    if not dd.is_displayed():
                        continue
                    dd.click()
                    time.sleep(1.5)
                    # Search for Indonesia option
                    options = driver.find_elements(By.CSS_SELECTOR,
                        'div[role="option"], li[role="option"], div[data-value], span[role="option"]'
                    )
                    for opt in options:
                        t = opt.get_attribute("textContent") or ""
                        val = opt.get_attribute("data-value") or ""
                        if "Indonesia" in t or "+62" in t or val == "62":
                            opt.click()
                            country_selected = True
                            log(f"Selected Indonesia (+62) via dropdown: {t[:40]}")
                            time.sleep(1)
                            return True
                except Exception:
                    pass
                # Close dropdown
                try:
                    driver.execute_script("document.body.click();")
                except Exception:
                    pass
                time.sleep(0.5)
        except Exception:
            pass

    # Method 3: JavaScript to set <select> value
    if not country_selected:
        try:
            js_result = driver.execute_script("""
                var selects = document.querySelectorAll('select');
                for (var i = 0; i < selects.length; i++) {
                    var opts = selects[i].options;
                    for (var j = 0; j < opts.length; j++) {
                        var v = opts[j].value || '';
                        var t = opts[j].text || '';
                        if (v === '62' || t.indexOf('Indonesia') >= 0 || t.indexOf('+62') >= 0) {
                            selects[i].selectedIndex = j;
                            selects[i].value = opts[j].value;
                            selects[i].dispatchEvent(new Event('change', {bubbles: true}));
                            selects[i].dispatchEvent(new Event('input', {bubbles: true}));
                            return 'OK:' + opts[j].value + ':' + opts[j].text;
                        }
                    }
                }
                return 'NOT_FOUND';
            """)
            if js_result and js_result.startswith("OK:"):
                country_selected = True
                log(f"Selected Indonesia (+62) via JS: {js_result}")
                time.sleep(1)
                return True
        except Exception:
            pass

    # Method 4: Try clicking element that contains "+62" or "Indonesia" text
    if not country_selected:
        try:
            all_elements = driver.find_elements(By.CSS_SELECTOR, 'div, span, li, option, a')
            for el in all_elements:
                if not el.is_displayed():
                    continue
                t = el.get_attribute("textContent") or ""
                if ("+62" in t or "Indonesia" in t) and len(t) < 50:
                    el.click()
                    country_selected = True
                    log(f"Selected Indonesia (+62) via text click: {t[:40]}")
                    time.sleep(1)
                    return True
        except Exception:
            pass

    if not country_selected:
        log("WARNING: Could not change country to Indonesia (+62)")
    return country_selected


def fill_phone_number_on_google(driver, phone_number, log):
    """Fill phone number on Google's phone verification page."""
    try:
        # Step 1: If on "Choose how to verify" page, click phone/SMS option
        try:
            body_text = driver.execute_script("return document.body ? document.body.innerText : '';")
        except Exception:
            body_text = ""

        if any(k in body_text for k in ["Choose how", "Pilih cara", "Verify it's you", "confirm your identity", "verify your phone"]):
            log("Verification method selection page detected")
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, "button, a, div[role='button'], div[role='link'], li")
                for btn in btns:
                    if not btn.is_displayed():
                        continue
                    t = btn.get_attribute("textContent") or ""
                    if any(k in t for k in ["text message", "SMS", "phone", "telepon", "Get a code", "Dapatkan kode", "sms", "Call me"]):
                        btn.click()
                        log(f"Clicked verification option: {t[:50]}")
                        time.sleep(3)
                        break
            except Exception:
                pass

        # Step 2: Select Indonesia (+62) as country
        log("Selecting country: Indonesia (+62)...")
        select_indonesia_country(driver, log)

        # Step 3: Find and fill phone number input
        phone_selectors = [
            'input[type="tel"]',
            'input[name="phoneNumber"]',
            'input[name="number"]',
            'input[autocomplete="tel"]',
            'input[data-initial-value]',
        ]

        phone_input = None
        for sel in phone_selectors:
            try:
                inputs = driver.find_elements(By.CSS_SELECTOR, sel)
                for inp in inputs:
                    if inp.is_displayed():
                        phone_input = inp
                        break
            except Exception:
                pass
            if phone_input:
                break

        if not phone_input:
            try:
                all_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input[type="tel"]')
                for inp in all_inputs:
                    if inp.is_displayed():
                        name = inp.get_attribute("name") or ""
                        if name not in ("identifier", "Passwd", "hiddenPassword", "ca"):
                            phone_input = inp
                            break
            except Exception:
                pass

        if not phone_input:
            log("No phone input field found")
            return False

        phone_input.clear()
        time.sleep(0.3)
        human_type(phone_input, phone_number, delay_range=(0.03, 0.06))
        time.sleep(0.5)

        log(f"Phone number entered: {phone_number}")

        clicked = click_advance(driver)
        if not clicked:
            try:
                phone_input.send_keys(Keys.RETURN)
            except Exception:
                pass

        log("Submitted phone number")
        return True

    except Exception as e:
        log(f"Error filling phone number: {e}")
        return False


def enter_otp_on_google(driver, otp_code, log):
    """Enter OTP code on Google's verification page."""
    try:
        # Wait for OTP input to appear
        time.sleep(2)

        otp_selectors = [
            'input[type="tel"]',
            'input[name="code"]',
            'input[name="Pin"]',
            'input[name="totpPin"]',
            'input[id="code"]',
            'input[autocomplete="one-time-code"]',
            'input[name="OtpCode"]',
            'input[name="otp"]',
        ]

        otp_input = None
        for sel in otp_selectors:
            try:
                inputs = driver.find_elements(By.CSS_SELECTOR, sel)
                for inp in inputs:
                    if inp.is_displayed():
                        otp_input = inp
                        break
            except Exception:
                pass
            if otp_input:
                break

        # Fallback: find any visible text/tel input that's not email/password/captcha
        if not otp_input:
            try:
                all_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"], input[type="tel"], input[type="number"]')
                for inp in all_inputs:
                    if inp.is_displayed():
                        name = inp.get_attribute("name") or ""
                        inp_type = inp.get_attribute("type") or ""
                        if name not in ("identifier", "Passwd", "hiddenPassword", "ca", "phoneNumber", "number"):
                            otp_input = inp
                            break
            except Exception:
                pass

        if not otp_input:
            # Try JS to find any input on the page
            try:
                js_found = driver.execute_script("""
                    var inputs = document.querySelectorAll('input[type="tel"], input[type="text"], input[name="code"], input[autocomplete="one-time-code"]');
                    for (var i = 0; i < inputs.length; i++) {
                        if (inputs[i].offsetParent !== null) {
                            inputs[i].focus();
                            return true;
                        }
                    }
                    return false;
                """)
                if js_found:
                    log("Found OTP input via JS focus")
            except Exception:
                pass

            # Re-try finding the input after JS focus
            for sel in otp_selectors:
                try:
                    inputs = driver.find_elements(By.CSS_SELECTOR, sel)
                    for inp in inputs:
                        if inp.is_displayed():
                            otp_input = inp
                            break
                except Exception:
                    pass
                if otp_input:
                    break

        if not otp_input:
            log("No OTP input field found")
            return False

        otp_input.clear()
        time.sleep(0.3)
        human_type(otp_input, otp_code, delay_range=(0.05, 0.1))
        time.sleep(0.5)

        log(f"OTP code entered: {otp_code}")

        clicked = click_advance(driver)
        if not clicked:
            try:
                otp_input.send_keys(Keys.RETURN)
            except Exception:
                pass

        log("Submitted OTP code")
        return True

    except Exception as e:
        log(f"Error entering OTP: {e}")
        return False


# ── PKCE ────────────────────────────────────────────────
def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce():
    code_verifier = b64url(secrets.token_bytes(32))
    code_challenge = b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
    state = b64url(secrets.token_bytes(16))
    return code_verifier, code_challenge, state


# ── Account Reader ──────────────────────────────────────
def read_accounts(file_path):
    accounts = []
    if not os.path.exists(file_path):
        return accounts
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 2:
                continue
            email = parts[0].strip()
            password = parts[1].strip()
            totp_secret = parts[2].strip() if len(parts) >= 3 else None
            if email and password:
                accounts.append({
                    "email": email,
                    "password": password,
                    "totp_secret": totp_secret,
                    "line": line_num,
                })
    return accounts


# ── TOTP Generator ──────────────────────────────────────
def generate_totp(secret: str) -> str:
    cleaned = secret.replace(" ", "").upper()
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    bits = ""
    for ch in cleaned.rstrip("="):
        v = alphabet.index(ch)
        bits += format(v, "05b")
    byte_arr = bytearray()
    for i in range(0, len(bits), 8):
        byte_arr.append(int(bits[i : i + 8], 2))
    key = bytes(byte_arr)
    counter = int(time.time()) // 30
    counter_bytes = counter.to_bytes(8, "big")
    hmac_result = hmac_mod.new(key, counter_bytes, hashlib.sha1).digest()
    offset = hmac_result[-1] & 0x0F
    code = (
        ((hmac_result[offset] & 0x7F) << 24)
        | ((hmac_result[offset + 1] & 0xFF) << 16)
        | ((hmac_result[offset + 2] & 0xFF) << 8)
        | (hmac_result[offset + 3] & 0xFF)
    )
    return str(code % 1000000).zfill(6)


# ── Rich UI Setup ──────────────────────────────────────
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.columns import Columns
from rich import box
from rich.theme import Theme

_theme = Theme({
    "success": "bold green",
    "error": "bold red",
    "warn": "bold yellow",
    "info": "bold cyan",
    "dim": "dim white",
    "accent": "bold magenta",
    "header": "bold white on blue",
    "label": "bold bright_blue",
    "value": "bright_white",
})

console = Console(theme=_theme, force_terminal=True)
_print_lock = threading.RLock()

BANNER = r"""
 ██╗  ██╗██╗██████╗ ███████╗██╗      ██╗  ██╗
 ██║ ██╔╝██║██╔══██╗██╔════╝██║      ██║ ██╔╝
 █████╔╝ ██║██║  ██║█████╗  ██║█████╗█████╔╝ 
 ██╔═██╗ ██║██║  ██║██╔══╝  ██║╚════╝██╔═██╗ 
 ██║  ██╗██║██████╔╝███████╗██║      ██║  ██╗
 ╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝╚═╝      ╚═╝  ╚═╝
"""

VERSION = "v3.0 PREMIUM"


def ok(text):
    with _print_lock:
        console.print(f"  [bold green]✓[/] {text}")

def fail(text):
    with _print_lock:
        console.print(f"  [bold red]✗[/] {text}")

def info(text):
    with _print_lock:
        console.print(f"  [bold cyan]●[/] {text}")

def warn(text):
    with _print_lock:
        console.print(f"  [bold yellow]⚠[/] {text}")

def step(text):
    with _print_lock:
        console.print(f"  [bold magenta]→[/] [dim]{text}[/]")

def rule(char="═", width=52):
    with _print_lock:
        console.print(f"  [dim]{char * width}[/]")

def log_line(line, msg, level="info"):
    colors = {"ok": "green", "fail": "red", "warn": "yellow", "info": "cyan", "step": "magenta"}
    icons = {"ok": "✓", "fail": "✗", "warn": "⚠", "info": "●", "step": "→"}
    c = colors.get(level, "cyan")
    icon = icons.get(level, "●")
    with _print_lock:
        console.print(f"    [dim]│[/] [bold {c}]{icon}[/] [dim]\\[{line}][/dim] {msg}")
    log_to_file(f"[{line}] {msg}")

def print_banner():
    console.print()
    banner_text = Text(BANNER, style="bold cyan", justify="center")
    ver_text = Text(f"  {VERSION}  ", style="bold white on blue", justify="center")
    sub_text = Text(
        "Google OAuth  •  Auto CAPTCHA Solver  •  Auto OTP (Litensi.id)\n",
        style="dim", justify="center"
    )
    console.print(Align.center(banner_text))
    console.print(Align.center(ver_text))
    console.print(Align.center(sub_text))
    console.print(Align.center(Text("─" * 56, style="dim blue")))
    console.print()

def print_config_table(config_data):
    table = Table(box=box.ROUNDED, show_header=False, border_style="blue", width=56)
    table.add_column("Key", style="bold cyan", width=16)
    table.add_column("Value", style="white")
    for k, v in config_data:
        table.add_row(k, str(v))
    with _print_lock:
        console.print(Align.center(table))
    console.print()

def print_summary_panel(total, success, failed, output, elapsed, num_workers):
    rate = (success / total * 100) if total > 0 else 0
    if rate >= 80:
        border = "green"
        status_icon = "✓"
        status_text = "EXCELLENT"
    elif rate >= 50:
        border = "yellow"
        status_icon = "⚠"
        status_text = "PARTIAL"
    else:
        border = "red"
        status_icon = "✗"
        status_text = "FAILED"

    table = Table(box=box.SQUARE, show_header=False, border_style=border, width=56)
    table.add_column("k", style="bold bright_blue", width=14)
    table.add_column("v", style="bright_white")
    table.add_row("Total Accounts", str(total))
    table.add_row("Successful", f"[bold green]{success}[/]")
    table.add_row("Failed", f"[bold red]{failed}[/]")
    table.add_row("Success Rate", f"{rate:.1f}%")
    table.add_row("Workers", str(num_workers))
    table.add_row("Output File", output)
    table.add_row("Elapsed Time", f"{elapsed:.1f}s")
    if total > 0:
        avg = elapsed / total
        table.add_row("Avg / Account", f"{avg:.1f}s")

    status_line = Text(f" {status_icon} {status_text} ", style=f"bold white on {border}", justify="center")

    with _print_lock:
        console.print()
        console.print(Align.center(Text("━" * 56, style=f"{border}")))
        console.print(Align.center(Text("  EXECUTION SUMMARY  ", style=f"bold {border}")))
        console.print(Align.center(Text("━" * 56, style=f"{border}")))
        console.print()
        console.print(Align.center(table))
        console.print()
        console.print(Align.center(status_line))
        console.print()


# ── CAPTCHA Solver ──────────────────────────────────────
_ddddocr_instance = None
_ddddocr_beta = None
_ddddocr_lock = threading.Lock()


def get_ddddocr():
    global _ddddocr_instance, _ddddocr_beta
    if not HAS_DDDDOCR:
        return None, None
    with _ddddocr_lock:
        if _ddddocr_instance is None:
            _ddddocr_instance = ddddocr.DdddOcr(show_ad=False)
            _ddddocr_beta = ddddocr.DdddOcr(show_ad=False, beta=True)
    return _ddddocr_instance, _ddddocr_beta


def preprocess_captcha_image(img_bytes):
    """Preprocess CAPTCHA image untuk meningkatkan akurasi OCR."""
    images = []
    img = Image.open(io.BytesIO(img_bytes))

    # Original
    images.append(("original", img_bytes))

    # Grayscale
    gray = img.convert("L")
    buf = io.BytesIO()
    gray.save(buf, format="PNG")
    images.append(("gray", buf.getvalue()))

    # Grayscale + threshold (binary)
    threshold = 128
    binary = gray.point(lambda x: 255 if x > threshold else 0, "1")
    buf = io.BytesIO()
    binary.save(buf, format="PNG")
    images.append(("binary", buf.getvalue()))

    # Grayscale + contrast enhancement
    enhancer = ImageEnhance.Contrast(gray)
    contrast = enhancer.enhance(2.0)
    buf = io.BytesIO()
    contrast.save(buf, format="PNG")
    images.append(("contrast", buf.getvalue()))

    # Grayscale + sharpen
    sharpened = gray.filter(ImageFilter.SHARPEN)
    buf = io.BytesIO()
    sharpened.save(buf, format="PNG")
    images.append(("sharpen", buf.getvalue()))

    # Inverted grayscale
    inverted = ImageOps.invert(gray)
    buf = io.BytesIO()
    inverted.save(buf, format="PNG")
    images.append(("inverted", buf.getvalue()))

    # Upscaled grayscale (2x)
    w, h = gray.size
    upscaled = gray.resize((w * 2, h * 2), Image.LANCZOS)
    buf = io.BytesIO()
    upscaled.save(buf, format="PNG")
    images.append(("upscaled", buf.getvalue()))

    # Grayscale + median filter (denoise)
    denoised = gray.filter(ImageFilter.MedianFilter(size=3))
    buf = io.BytesIO()
    denoised.save(buf, format="PNG")
    images.append(("denoised", buf.getvalue()))

    return images


def solve_captcha_ocr(img_bytes, log):
    """
    Solve CAPTCHA menggunakan multiple OCR engines + preprocessing.
    Return list of (method, result) tuples, sorted by confidence.
    """
    results = []

    # Preprocess
    processed = preprocess_captcha_image(img_bytes)

    # ddddocr (ML-based, paling akurat untuk CAPTCHA)
    ocr1, ocr2 = get_ddddocr()
    if ocr1:
        for name, img_data in processed:
            try:
                result = ocr1.classification(img_data)
                if result and len(result) <= 10:
                    result = result.strip()
                    if result:
                        results.append((f"ddddocr-{name}", result))
            except Exception:
                pass
        for name, img_data in processed:
            try:
                result = ocr2.classification(img_data)
                if result and len(result) <= 10:
                    result = result.strip()
                    if result:
                        results.append((f"ddddocr_beta-{name}", result))
            except Exception:
                pass

    # pytesseract (fallback)
    if HAS_TESSERACT:
        tesseract_configs = [
            "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            "--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            "--psm 10 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            "--psm 13 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            "--psm 7",
            "--psm 8",
            "--psm 13",
        ]
        for name, img_data in processed:
            for config in tesseract_configs:
                try:
                    img = Image.open(io.BytesIO(img_data))
                    result = pytesseract.image_to_string(img, config=config).strip()
                    if result and len(result) <= 10:
                        results.append((f"tesseract-{name}-{config.split()[1]}", result))
                except Exception:
                    pass

    return results


def vote_captcha_solution(results):
    """
    Pilih solusi terbaik dari hasil OCR.
    Strategy: group by result, pilih yang paling sering muncul.
    """
    if not results:
        return None

    counts = {}
    for method, result in results:
        result = result.strip()
        if not result:
            continue
        if result not in counts:
            counts[result] = {"count": 0, "methods": []}
        counts[result]["count"] += 1
        counts[result]["methods"].append(method)

    if not counts:
        return None

    # Sort by count descending, then by length (shorter = more likely correct for CAPTCHA)
    sorted_results = sorted(counts.items(), key=lambda x: (-x[1]["count"], len(x[0])))

    best_result = sorted_results[0]
    return best_result[0]


def save_captcha_debug(img_bytes, attempt, email, result, script_dir):
    """Save CAPTCHA image dan hasil untuk debugging."""
    debug_dir = os.path.join(script_dir, CAPTCHA_DEBUG_DIR)
    os.makedirs(debug_dir, exist_ok=True)
    safe_email = email.split("@")[0].replace(".", "_")
    filename = f"captcha_{safe_email}_attempt{attempt}_result_{result or 'none'}.png"
    filepath = os.path.join(debug_dir, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(img_bytes)
    except Exception:
        pass
    return filepath


def detect_captcha_type(driver):
    """
    Deteksi jenis CAPTCHA yang muncul di halaman.
    Return: 'text', 'recaptcha_checkbox', 'recaptcha_image', 'turnstile', 'none'
    """
    try:
        # 1. Text/image CAPTCHA (img tag dengan alt CAPTCHA)
        captcha_imgs = driver.find_elements(
            By.CSS_SELECTOR,
            'img[alt*="CAPTCHA"], img[alt*="captcha"], img[src*="Captcha"], img[src*="captcha"]'
        )
        for img in captcha_imgs:
            if img.is_displayed():
                return "text"
    except Exception:
        pass

    try:
        # 2. reCAPTCHA v2 checkbox (iframe dengan src recaptcha)
        recaptcha_frames = driver.find_elements(
            By.CSS_SELECTOR,
            'iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"], iframe[title*="recaptcha"]'
        )
        for frame in recaptcha_frames:
            try:
                if frame.is_displayed():
                    src = frame.get_attribute("src") or ""
                    if "recaptcha" in src.lower():
                        return "recaptcha_checkbox"
            except Exception:
                pass
    except Exception:
        pass

    try:
        # 3. reCAPTCHA image challenge (iframe dengan title "recaptcha challenge")
        challenge_frames = driver.find_elements(
            By.CSS_SELECTOR,
            'iframe[title*="recaptcha challenge"], iframe[title*="challenge"]'
        )
        for frame in challenge_frames:
            if frame.is_displayed():
                return "recaptcha_image"
    except Exception:
        pass

    try:
        # 4. Cloudflare Turnstile
        turnstile = driver.find_elements(
            By.CSS_SELECTOR,
            'iframe[src*="turnstile"], div[class*="cf-turnstile"], iframe[src*="challenges.cloudflare"]'
        )
        for el in turnstile:
            if el.is_displayed():
                return "turnstile"
    except Exception:
        pass

    try:
        # 5. Google's own interstitial challenge page
        body_text = driver.execute_script("return document.body ? document.body.innerText : '';")
        if body_text:
            bl = body_text.lower()
            if any(k in bl for k in ["unusual activity", "aktivitas yang tidak wajar",
                                     "verify you are human", "verifikasi bahwa anda manusia",
                                     "please verify", "mohon verifikasi"]):
                return "interstitial"
    except Exception:
        pass

    return "none"


def solve_recaptcha_audio(driver, log, script_dir, email):
    """
    Solve reCAPTCHA v2 menggunakan audio challenge.
    1. Click checkbox reCAPTCHA
    2. If image challenge appears, switch to audio challenge
    3. Download audio, convert to text via speech recognition
    4. Submit answer
    """
    import tempfile
    import subprocess

    for attempt in range(1, RECAPTCHA_AUDIO_MAX_RETRIES + 1):
        log(f"reCAPTCHA audio attempt {attempt}/{RECAPTCHA_AUDIO_MAX_RETRIES}")

        # Step 1: Find and switch to reCAPTCHA iframe
        recaptcha_frame = None
        try:
            frames = driver.find_elements(
                By.CSS_SELECTOR,
                'iframe[src*="recaptcha"], iframe[title*="reCAPTCHA"], iframe[title*="recaptcha"]'
            )
            for frame in frames:
                if frame.is_displayed():
                    recaptcha_frame = frame
                    break
        except Exception:
            pass

        if not recaptcha_frame:
            log("No reCAPTCHA iframe found")
            break

        # Step 2: Click the checkbox
        try:
            driver.switch_to.frame(recaptcha_frame)
            time.sleep(1)
            checkbox = driver.find_element(By.CSS_SELECTOR, '.recaptcha-checkbox-border, #recaptcha-anchor')
            if checkbox:
                checkbox.click()
                log("Clicked reCAPTCHA checkbox")
                time.sleep(3)
            driver.switch_to.default_content()
        except Exception as e:
            log(f"Checkbox click error: {e}")
            driver.switch_to.default_content()

        time.sleep(2)

        # Step 3: Check if we passed (no challenge iframe)
        captcha_type = detect_captcha_type(driver)
        if captcha_type == "none":
            log("reCAPTCHA solved via checkbox!")
            return True

        # Step 4: Switch to audio challenge
        challenge_frame = None
        try:
            frames = driver.find_elements(
                By.CSS_SELECTOR,
                'iframe[title*="recaptcha challenge"], iframe[title*="challenge"]'
            )
            for frame in frames:
                if frame.is_displayed():
                    challenge_frame = frame
                    break
        except Exception:
            pass

        if not challenge_frame:
            log("No challenge frame found after checkbox")
            time.sleep(2)
            continue

        try:
            driver.switch_to.frame(challenge_frame)
            time.sleep(1)

            # Click "Get an audio challenge" / audio button
            audio_btn = None
            try:
                audio_btns = driver.find_elements(By.CSS_SELECTOR, '#recaptcha-audio-button, .rc-button-audio')
                for btn in audio_btns:
                    if btn.is_displayed():
                        audio_btn = btn
                        break
            except Exception:
                pass

            if not audio_btn:
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, 'button, a, div[role="button"]')
                    for btn in btns:
                        t = btn.get_attribute("textContent") or ""
                        if "audio" in t.lower() or "Headphone" in t:
                            audio_btn = btn
                            break
                except Exception:
                    pass

            if audio_btn:
                audio_btn.click()
                log("Switched to audio challenge")
                time.sleep(3)
            else:
                log("Could not find audio challenge button")
                driver.switch_to.default_content()
                time.sleep(2)
                continue

            # Step 5: Get audio URL
            audio_url = None
            try:
                audio_el = driver.find_element(By.CSS_SELECTOR, 'audio source, audio[src]')
                audio_url = audio_el.get_attribute("src")
            except Exception:
                pass

            if not audio_url:
                try:
                    audio_el = driver.find_element(By.TAG_NAME, 'audio')
                    audio_url = audio_el.get_attribute("src")
                except Exception:
                    pass

            if not audio_url:
                log("No audio URL found")
                driver.switch_to.default_content()
                time.sleep(2)
                continue

            log(f"Audio URL found: {audio_url[:60]}...")

            # Step 6: Download and convert audio to text
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_audio:
                tmp_audio_path = tmp_audio.name

            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.get(audio_url)
                    with open(tmp_audio_path, 'wb') as f:
                        f.write(resp.content)
            except Exception as e:
                log(f"Failed to download audio: {e}")
                driver.switch_to.default_content()
                time.sleep(2)
                continue

            # Convert to WAV for speech recognition
            tmp_wav_path = tmp_audio_path.replace('.mp3', '.wav')
            try:
                subprocess.run(
                    ['ffmpeg', '-y', '-i', tmp_audio_path, '-ar', '16000', '-ac', '1', tmp_wav_path],
                    capture_output=True, timeout=30
                )
            except Exception as e:
                log(f"FFmpeg convert error: {e}")
                time.sleep(2)
                continue

            # Speech recognition
            if HAS_SPEECH:
                recognizer = sr.Recognizer()
                try:
                    with sr.AudioFile(tmp_wav_path) as source:
                        audio_data = recognizer.record(source)
                    text = recognizer.recognize_google(audio_data)
                    text = text.strip().lower().replace(' ', '')
                    log(f"Audio recognized: '{text}'")
                except Exception as e:
                    log(f"Speech recognition error: {e}")
                    text = ""
            else:
                log("SpeechRecognition not installed, cannot solve audio CAPTCHA")
                text = ""

            # Cleanup temp files
            try:
                os.unlink(tmp_audio_path)
                os.unlink(tmp_wav_path)
            except Exception:
                pass

            if not text:
                log("No text from audio, retrying...")
                driver.switch_to.default_content()
                time.sleep(2)
                continue

            # Step 7: Enter audio answer
            try:
                audio_input = driver.find_element(By.CSS_SELECTOR, '#audio-response, input[type="text"]')
                audio_input.clear()
                time.sleep(0.3)
                for ch in text:
                    audio_input.send_keys(ch)
                    time.sleep(random.uniform(0.03, 0.08))
                time.sleep(0.5)
                log(f"Audio answer entered: {text}")
            except Exception as e:
                log(f"Failed to enter audio answer: {e}")
                driver.switch_to.default_content()
                time.sleep(2)
                continue

            # Step 8: Submit
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, '#recaptcha-verify-button, button')
                if submit_btn:
                    submit_btn.click()
                    log("Submitted audio answer")
            except Exception:
                pass

            driver.switch_to.default_content()
            time.sleep(4)

            # Step 9: Check if solved
            captcha_type = detect_captcha_type(driver)
            if captcha_type == "none":
                log("reCAPTCHA audio solved!")
                return True
            else:
                log("Audio answer wrong, retrying...")

        except Exception as e:
            log(f"Audio challenge error: {e}")
            driver.switch_to.default_content()
            time.sleep(2)

    log(f"reCAPTCHA audio solving failed after {RECAPTCHA_AUDIO_MAX_RETRIES} attempts")
    return False


def solve_turnstile(driver, log, script_dir, email):
    """
    Solve Cloudflare Turnstile dengan menunggu auto-solve atau click checkbox.
    """
    log("Turnstile detected, waiting for auto-solve...")

    for _ in range(15):
        time.sleep(2)
        try:
            frames = driver.find_elements(
                By.CSS_SELECTOR,
                'iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]'
            )
            if not frames:
                log("Turnstile resolved!")
                return True

            for frame in frames:
                if not frame.is_displayed():
                    log("Turnstile resolved!")
                    return True
                try:
                    driver.switch_to.frame(frame)
                    try:
                        checkbox = driver.find_element(By.CSS_SELECTOR, 'input[type="checkbox"], label')
                        if checkbox:
                            checkbox.click()
                            log("Clicked Turnstile checkbox")
                            time.sleep(3)
                    except Exception:
                        pass
                    driver.switch_to.default_content()
                except Exception:
                    driver.switch_to.default_content()
        except Exception:
            pass

    log("Turnstile auto-solve timeout")
    return False


def solve_interstitial(driver, log, script_dir, email):
    """
    Handle Google's interstitial challenge page ("unusual activity").
    Coba klik button verify/continue, atau tunggu.
    """
    log("Google interstitial challenge detected")
    time.sleep(2)

    for _ in range(5):
        clicked = click_advance(driver)
        if clicked:
            log("Clicked advance on interstitial page")
            time.sleep(4)
        else:
            log("No button on interstitial, waiting...")
            time.sleep(5)

        captcha_type = detect_captcha_type(driver)
        if captcha_type == "none":
            log("Interstitial passed!")
            return True

    # Try refreshing page
    try:
        log("Trying page refresh...")
        driver.refresh()
        time.sleep(5)
        captcha_type = detect_captcha_type(driver)
        if captcha_type == "none":
            log("Interstitial passed after refresh!")
            return True
    except Exception:
        pass

    log("Could not pass interstitial")
    return False


def detect_and_solve_captcha(driver, log, email, script_dir, max_retries=None):
    """
    Deteksi & solve SEMUA jenis CAPTCHA.
    Return True jika CAPTCHA solved (atau tidak ada CAPTCHA).
    """
    if max_retries is None:
        max_retries = CAPTCHA_MAX_RETRIES

    captcha_type = detect_captcha_type(driver)

    if captcha_type == "none":
        return True

    log(f"CAPTCHA type detected: {captcha_type}")

    if captcha_type == "text":
        return solve_text_captcha(driver, log, email, script_dir, max_retries)

    if captcha_type == "recaptcha_checkbox":
        solved = solve_recaptcha_audio(driver, log, script_dir, email)
        if solved:
            return True
        # If audio failed, try text CAPTCHA handler (maybe checkbox passed but image challenge appeared)
        time.sleep(2)
        new_type = detect_captcha_type(driver)
        if new_type == "text":
            return solve_text_captcha(driver, log, email, script_dir, max_retries)
        return False

    if captcha_type == "recaptcha_image":
        return solve_recaptcha_audio(driver, log, script_dir, email)

    if captcha_type == "turnstile":
        return solve_turnstile(driver, log, script_dir, email)

    if captcha_type == "interstitial":
        return solve_interstitial(driver, log, script_dir, email)

    # Unknown captcha type, try text handler as fallback
    log(f"Unknown CAPTCHA type: {captcha_type}, trying text handler...")
    return solve_text_captcha(driver, log, email, script_dir, max_retries)


def solve_text_captcha(driver, log, email, script_dir, max_retries=None):
    """Solve text/image CAPTCHA menggunakan OCR."""
    if max_retries is None:
        max_retries = CAPTCHA_MAX_RETRIES

    for attempt in range(1, max_retries + 1):
        # Cari CAPTCHA image
        captcha_img = None
        try:
            captcha_imgs = driver.find_elements(
                By.CSS_SELECTOR,
                'img[alt*="CAPTCHA"], img[alt*="captcha"], img[src*="Captcha"], img[src*="captcha"]'
            )
            for img in captcha_imgs:
                if img.is_displayed():
                    captcha_img = img
                    break
        except Exception:
            pass

        if not captcha_img:
            # Tidak ada CAPTCHA - cek apakah kita sudah di page selanjutnya
            log("No CAPTCHA detected - proceeding")
            return True

        log(f"CAPTCHA detected! Attempt {attempt}/{max_retries}")

        # Screenshot CAPTCHA image
        try:
            img_bytes = captcha_img.screenshot_as_png
        except Exception as e:
            log(f"Failed to capture CAPTCHA: {e}")
            time.sleep(1)
            continue

        # Solve dengan OCR
        log("Solving CAPTCHA with OCR (ddddocr + tesseract)...")
        ocr_results = solve_captcha_ocr(img_bytes, log)

        if not ocr_results:
            log("OCR returned no results")
            # Save untuk debug
            save_captcha_debug(img_bytes, attempt, email, "no_ocr", script_dir)
            # Refresh CAPTCHA dan retry
            try:
                captcha_img.click()
                time.sleep(2)
            except Exception:
                pass
            continue

        # Vote untuk solusi terbaik
        best = vote_captcha_solution(ocr_results)
        all_results = list(set(r[1] for r in ocr_results))

        if not best:
            log("No valid CAPTCHA solution from voting")
            save_captcha_debug(img_bytes, attempt, email, "no_vote", script_dir)
            try:
                captcha_img.click()
                time.sleep(2)
            except Exception:
                pass
            continue

        log(f"CAPTCHA candidates: {all_results[:5]}")
        log(f"Best solution: '{best}' (from {len(ocr_results)} OCR attempts)")

        # Save untuk debug
        save_captcha_debug(img_bytes, attempt, email, best, script_dir)

        # Isi CAPTCHA input
        try:
            captcha_input = driver.find_element(By.CSS_SELECTOR, 'input[name="ca"]:visible, input[name="ca"]')
            captcha_input.clear()
            time.sleep(0.2)
            # Human-like typing
            for ch in best:
                captcha_input.send_keys(ch)
                time.sleep(random.uniform(0.03, 0.08))
            time.sleep(0.3)
        except NoSuchElementException:
            # Try any visible text input yang bukan email/password
            try:
                text_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type="text"]:visible, input[type="text"]')
                for inp in text_inputs:
                    name = inp.get_attribute("name") or ""
                    if name not in ("identifier", "Passwd", "hiddenPassword"):
                        inp.clear()
                        for ch in best:
                            inp.send_keys(ch)
                            time.sleep(random.uniform(0.03, 0.08))
                        time.sleep(0.3)
                        break
            except Exception as e:
                log(f"Failed to fill CAPTCHA input: {e}")
                continue

        # Click Next/Submit
        click_advance(driver)
        time.sleep(5)

        # Cek hasil
        try:
            captcha_imgs2 = driver.find_elements(
                By.CSS_SELECTOR,
                'img[alt*="CAPTCHA"], img[alt*="captcha"], img[src*="Captcha"], img[src*="captcha"]'
            )
            still_captcha = any(img.is_displayed() for img in captcha_imgs2)
        except Exception:
            still_captcha = False

        if not still_captcha:
            # Cek apakah password field muncul atau halaman berubah
            try:
                pwd = driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
                pwd_visible = any(p.is_displayed() for p in pwd)
            except Exception:
                pwd_visible = False

            try:
                current_url = driver.current_url
            except Exception:
                current_url = ""

            if pwd_visible or "accounts.google.com" not in current_url or "signin/challenge/pwd" in current_url:
                log(f"CAPTCHA solved! Proceeding...")
                return True

            # Mungkin halaman berubah tapi bukan password - tetap sukses
            log(f"CAPTCHA appears solved, page changed")
            return True
        else:
            log(f"CAPTCHA wrong, retrying...")

    log(f"CAPTCHA solving failed after {max_retries} attempts")
    return False


# ── Human-like Helpers ──────────────────────────────────
def human_type(element, text, delay_range=(0.03, 0.08)):
    """Type text seperti manusia dengan random delay."""
    element.click()
    time.sleep(random.uniform(0.1, 0.3))
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(*delay_range))


def human_mouse_move(driver, x=None, y=None):
    """Simulasi pergerakan mouse seperti manusia."""
    try:
        if x is None:
            x = random.randint(100, 800)
        if y is None:
            y = random.randint(100, 600)
        action = __import__('selenium.webdriver.common.action_chains', fromlist=['ActionChains']).ActionChains(driver)
        action.move_by_offset(x, y)
        action.perform()
    except Exception:
        pass


def random_human_pause(min_sec=0.5, max_sec=2.0):
    """Random pause seperti manusia."""
    time.sleep(random.uniform(min_sec, max_sec))


# ── Google Login Helpers ────────────────────────────────
ADVANCE_LABELS = [
    "Saya mengerti", "Saya menyetujui", "Saya setuju", "Lanjutkan", "Izinkan", "Berikutnya",
    "Mengerti", "Setuju", "Lanjut", "Ya",
    "I understand", "I accept", "I agree", "Accept", "Allow", "Continue", "Next", "Verify", "Confirm",
    "Got it", "OK", "Done", "Yes", "Sure", "I have read", "Agree", "Proceed",
]

GOOGLE_ERROR_PATTERNS = [
    "Couldn't find your Google Account",
    "Tidak dapat menemukan Akun Google",
    "Akun Google tidak dapat ditemukan",
    "Wrong password",
    "Kata sandi salah",
    "Password salah",
    "Please try again",
    "Coba lagi",
    "couldn't verify",
    "tidak dapat memverifikasi",
    "suspended",
    "dinonaktifkan",
    "unusual activity",
    "aktivitas yang tidak wajar",
    "has been disabled",
    "akun dinonaktifkan",
    "Start appeal",
]


def check_google_errors(driver):
    try:
        html = driver.page_source
    except Exception:
        return None
    html_lower = html.lower()
    for pattern in GOOGLE_ERROR_PATTERNS:
        if pattern.lower() in html_lower:
            return pattern
    return None


def click_advance(driver):
    pattern = re.compile("|".join(re.escape(l) for l in ADVANCE_LABELS), re.IGNORECASE)

    # Try input[type=submit] and button[type=submit]
    try:
        submits = driver.find_elements(By.CSS_SELECTOR, 'input[type=submit], button[type=submit]')
    except Exception:
        submits = []
    for btn in submits:
        try:
            if not btn.is_displayed():
                continue
            value = btn.get_attribute("value") or ""
            text = btn.get_attribute("textContent") or ""
            if pattern.search(value) or pattern.search(text):
                btn.click()
                return True
        except Exception:
            pass

    # Try button/a/div with role=button
    try:
        btns = driver.find_elements(By.CSS_SELECTOR, "button, div[role='button'], a[role='button']")
    except Exception:
        btns = []
    for btn in btns:
        try:
            if not btn.is_displayed():
                continue
            text = btn.get_attribute("textContent") or ""
            if pattern.search(text):
                btn.click()
                return True
        except Exception:
            pass

    # JavaScript fallback
    try:
        js_clicked = driver.execute_script("""
            var labels = %s;
            var pattern = new RegExp(labels.join('|'), 'i');
            var elements = document.querySelectorAll('button, div[role="button"], input[type="submit"], a[role="button"]');
            for (var i = 0; i < elements.length; i++) {
                var el = elements[i];
                var rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                var text = el.textContent || el.value || '';
                if (pattern.test(text)) {
                    el.click();
                    return true;
                }
            }
            return false;
        """ % json.dumps(ADVANCE_LABELS))
        if js_clicked:
            return True
    except Exception:
        pass

    return False


def handle_google_login(driver, account, log, script_dir):
    """Handle email + password + CAPTCHA + 2FA on accounts.google.com"""
    email = account["email"]
    password = account["password"]
    totp_secret = account.get("totp_secret")

    time.sleep(2)

    # Step 1: Email
    try:
        email_input = None
        for _ in range(10):
            candidates = driver.find_elements(By.CSS_SELECTOR, 'input[type=email], #identifierId, input[name=identifier]')
            for cand in candidates:
                try:
                    name = cand.get_attribute("name") or ""
                    if "hidden" in name.lower() or "hidden" in (cand.get_attribute("aria-hidden") or "").lower():
                        continue
                except Exception:
                    pass
                if cand.is_displayed():
                    email_input = cand
                    break
            if email_input is not None:
                break
            time.sleep(1)
        if email_input is None:
            raise NoSuchElementException("Visible email input not found")
        log("Entering email...")
        human_mouse_move(driver)
        random_human_pause(0.2, 0.5)
        human_type(email_input, email)
        random_human_pause(0.3, 0.7)
        click_advance(driver)
        time.sleep(5)
    except NoSuchElementException:
        pass

    # Check for CAPTCHA after email submission
    captcha_solved = detect_and_solve_captcha(driver, log, email, script_dir)
    if not captcha_solved:
        raise Exception("Failed to solve CAPTCHA after email submission")

    # Check for errors after email
    err = check_google_errors(driver)
    if err:
        raise Exception(f"Google email error: {err}")

    # Step 2: Password (wait for password field to be visible)
    log("Waiting for password field...")
    pwd_found = False
    for _ in range(15):
        try:
            pwd_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type=password]')
            for p in pwd_inputs:
                # Skip Google's hidden password field (aria-hidden / hiddenPassword)
                try:
                    name = p.get_attribute("name") or ""
                    aria_hidden = p.get_attribute("aria-hidden") or ""
                    cls = p.get_attribute("class") or ""
                except Exception:
                    name = aria_hidden = cls = ""
                if "hiddenPassword" in name or "hidden" in aria_hidden.lower() or "hidden" in cls.lower():
                    continue
                if not p.is_displayed():
                    continue
                # Extra JS check: field must be actually on-screen and clickable
                try:
                    usable = driver.execute_script(
                        "var r=arguments[0].getBoundingClientRect();"
                        "var w=arguments[0].offsetWidth,h=arguments[0].offsetHeight;"
                        "var s=getComputedStyle(arguments[0]);"
                        "var vis=s.visibility!=='hidden'&&s.display!=='none';"
                        "var top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2)||document.elementFromPoint(r.left,r.top);"
                        "return vis&&w>0&&h>0&&(top===arguments[0]||arguments[0].contains(top)||top===null);",
                        p,
                    )
                except Exception:
                    usable = True
                if not usable:
                    continue
                log("Entering password...")
                human_mouse_move(driver)
                random_human_pause(0.2, 0.5)
                human_type(p, password)
                random_human_pause(0.3, 0.7)
                click_advance(driver)
                pwd_found = True
                break
        except Exception:
            pass
        if pwd_found:
            break
        time.sleep(1)

    if pwd_found:
        time.sleep(5)

        # Check for CAPTCHA after password submission
        captcha_solved = detect_and_solve_captcha(driver, log, email, script_dir)
        if not captcha_solved:
            raise Exception("Failed to solve CAPTCHA after password submission")

        err = check_google_errors(driver)
        if err:
            raise Exception(f"Google password error: {err}")


def handle_google_consent(driver, log, script_dir, email):
    """Handle post-login Google pages: consent, terms of service, account chooser, 2FA, CAPTCHA, phone verification."""
    try:
        current_url = driver.current_url
    except Exception:
        return

    # Detect disabled account
    if "disabled" in current_url.lower():
        raise Exception("Akun Google dinonaktifkan (disabled). Gunakan akun lain.")

    # Get page text via JavaScript (with short timeout)
    txt = ""
    try:
        txt = driver.execute_script("return document.body ? document.body.innerText : '';")
    except Exception:
        try:
            txt = driver.page_source[:5000]
        except Exception:
            txt = ""

    # Detect disabled account via text
    if "Start appeal" in txt or "has been disabled" in txt:
        raise Exception("Akun Google dinonaktifkan (disabled). Gunakan akun lain.")

    # Detect phone verification challenge
    phone_challenge_keywords = [
        "phone number", "nomor telepon", "Verify it's you", "verify your identity",
        "text message", "SMS", "Get a code", "Dapatkan kode",
        "phone to verify", "Add a phone", "Tambahkan nomor",
        "Verify your phone", "Konfirmasi nomor",
    ]
    is_phone_challenge = (
        "challenge/iap" in current_url
        or "challenge/az" in current_url
        or "challenge/ipp" in current_url
        or "challenge/dp" in current_url
        or "challenge/kp" in current_url
        or any(k.lower() in txt.lower() for k in phone_challenge_keywords)
    )

    if is_phone_challenge:
        log("Phone verification challenge detected!")
        log("Auto-ordering OTP from Litensi.id (Indonesia, Google)...")
        verified = handle_phone_verification(driver, log, script_dir, email)
        if verified:
            return
        else:
            raise Exception("Phone verification failed via Litensi OTP")

    # Check for CAPTCHA on any page
    try:
        captcha_imgs = driver.find_elements(
            By.CSS_SELECTOR,
            'img[alt*="CAPTCHA"], img[alt*="captcha"], img[src*="Captcha"], img[src*="captcha"]'
        )
        has_captcha = any(img.is_displayed() for img in captcha_imgs)
    except Exception:
        has_captcha = False

    if has_captcha:
        log("CAPTCHA detected on consent page")
        detect_and_solve_captcha(driver, log, email, script_dir)
        return

    # 2FA (TOTP)
    totp_secret = getattr(driver, '_kiro_totp', None)
    if any(k in txt for k in ["2-Step", "Enter the code", "Authenticator", "Verifikasi 2", "two-factor", "verification code"]):
        if not totp_secret:
            raise Exception("Akun butuh 2FA tapi totp_secret kosong (format: email:password:totp_secret)")
        code = generate_totp(totp_secret)
        log(f"Entering TOTP code: {code}")
        try:
            totp_inputs = driver.find_elements(By.CSS_SELECTOR, 'input[type=tel], input[name=totpPin], input[type=text]')
            for inp in totp_inputs:
                if inp.is_displayed():
                    inp.clear()
                    human_type(inp, code, delay_range=(0.05, 0.1))
                    time.sleep(0.3)
                    click_advance(driver)
                    time.sleep(4)
                    return
        except Exception as e:
            log(f"TOTP input error: {e}")
            return

    # Account chooser - click first account
    if any(k in txt for k in ["Choose an account", "Pilih akun", "Use another account"]):
        log("Account chooser detected, clicking first account...")
        try:
            acc_items = driver.find_elements(By.CSS_SELECTOR, '[data-email]')
            for item in acc_items:
                if item.is_displayed():
                    item.click()
                    time.sleep(3)
                    return
        except Exception:
            pass
        return

    # Check for checkboxes (terms of service) via JS
    try:
        driver.execute_script("""
            var cbs = document.querySelectorAll('input[type=checkbox]:not(:checked)');
            cbs.forEach(function(cb) { cb.click(); });
            var divCbs = document.querySelectorAll('div[role="checkbox"]:not([aria-checked="true"])');
            divCbs.forEach(function(cb) { cb.click(); });
        """)
    except Exception:
        pass

    # Click advance/accept/continue
    clicked = click_advance(driver)
    if clicked:
        log(f"Clicked advance on consent page")
        time.sleep(4)
    else:
        log(f"No advance button found on consent page")
        time.sleep(2)


# ── Kiro IDE OAuth Flow ─────────────────────────────────
def perform_kiro_login(driver, account, log_fn=None, script_dir=None):
    """
    Full PKCE OAuth flow:
    1. Generate PKCE
    2. Navigate ke Kiro login URL (Google)
    3. Handle Google login (email + password + CAPTCHA + 2FA)
    4. Capture kiro:// callback
    5. Exchange code -> tokens
    """
    log = log_fn or (lambda x: None)
    if script_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))

    code_verifier, code_challenge, state = generate_pkce()

    params = urlencode({
        "idp": "Google",
        "redirect_uri": KIRO_REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "select_account",
    })
    login_url = f"{KIRO_LOGIN_URL}?{params}"

    log(f"Navigating: {login_url[:80]}...")

    # Navigate
    try:
        driver.get(login_url)
    except Exception as e:
        err_msg = str(e)
        if not any(x in err_msg for x in ["ERR_UNKNOWN_URL_SCHEME", "ERR_ABORTED", "Navigation"]):
            raise

    # Main loop
    start = time.time()
    stable_count = 0
    last_url = ""
    timeout_sec = 180
    captured_callback = None
    google_login_done = False

    email = account["email"]
    if account.get("totp_secret"):
        driver._kiro_totp = account["totp_secret"]
    else:
        driver._kiro_totp = None

    while time.time() - start < timeout_sec:
        # Check for kiro:// callback in URL
        try:
            current_url = driver.current_url
        except Exception:
            time.sleep(1)
            continue

        if current_url and current_url.startswith("kiro://"):
            captured_callback = current_url
            log(f"Callback captured from URL: {current_url[:100]}...")
            break

        # Check performance logs for kiro:// callback
        try:
            logs = driver.get_log("performance")
            for entry in logs:
                try:
                    log_data = json.loads(entry["message"])
                    if log_data.get("message", {}).get("method") == "Network.requestWillBeSent":
                        req_url = log_data["message"]["params"]["request"]["url"]
                        if req_url.startswith("kiro://"):
                            captured_callback = req_url
                            log(f"Callback captured from logs: {req_url[:100]}...")
                            break
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
            if captured_callback:
                break
        except Exception:
            pass

        try:
            txt = driver.execute_script("return document.body ? document.body.innerText : '';")
        except Exception:
            txt = ""
        if "accounts.google.com" in current_url:
            if not google_login_done:
                log("Google login form detected")
                handle_google_login(driver, account, log, script_dir)
                google_login_done = True
                time.sleep(3)
            else:
                handle_google_consent(driver, log, script_dir, email)
                time.sleep(2)
            continue

        # Kiro Cognito hosted UI - click Google
        if "auth.desktop.kiro.dev" in current_url or "amazoncognito.com" in current_url:
            if any(k in txt for k in ["Google", "Sign in with Google", "Continue with Google"]):
                log("Click Google on Kiro login")
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, "button, a, div[role='button']")
                    for btn in btns:
                        if not btn.is_displayed():
                            continue
                        t = btn.text or ""
                        if "Google" in t:
                            btn.click()
                            break
                except Exception:
                    pass
                time.sleep(3.5)
                continue

        # Stable check
        if current_url == last_url:
            stable_count += 1
            if stable_count >= 12:
                log(f"Page stuck at {current_url}")
                break
        else:
            stable_count = 0
            last_url = current_url

        time.sleep(1.5)

    if not captured_callback:
        raise Exception(f"Callback URL not captured (timeout {timeout_sec}s). Last URL: {current_url}")

    # Parse code
    callback_params = parse_qs(urlparse(captured_callback).query)
    code = callback_params.get("code", [None])[0]
    returned_state = callback_params.get("state", [None])[0]

    if not code:
        raise Exception(f"No code in callback: {captured_callback}")
    if returned_state != state:
        log(f"State mismatch (expected={state}, got={returned_state}) - continuing")

    # Exchange code -> token (with retry)
    log("Exchanging code for token...")
    last_token_error = None
    for token_attempt in range(1, 4):
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    KIRO_TOKEN_URL,
                    json={
                        "code": code,
                        "code_verifier": code_verifier,
                        "redirect_uri": KIRO_REDIRECT_URI,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "AWS-SDK-JS/3.0.0 kiro-ide/1.0.0",
                    },
                )

            if resp.status_code == 200:
                break
            else:
                last_token_error = f"/oauth/token {resp.status_code}: {resp.text[:300]}"
                log(f"Token exchange attempt {token_attempt}/3 failed: {resp.status_code}")
                time.sleep(2 * token_attempt)
        except Exception as te:
            last_token_error = str(te)
            log(f"Token exchange attempt {token_attempt}/3 error: {te}")
            time.sleep(2 * token_attempt)
    else:
        raise Exception(f"Token exchange failed after 3 retries: {last_token_error}")

    data = resp.json()
    access_token = data.get("accessToken") or data.get("access_token")
    refresh_token = data.get("refreshToken") or data.get("refresh_token")
    expires_at = data.get("expiresAt") or data.get("expires_at")

    if not access_token or not refresh_token:
        raise Exception(f"Token response incomplete: {json.dumps(data)[:300]}")

    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at,
        "profileArn": SOCIAL_PROFILE_ARN,
        "authMethod": "social",
        "provider": "Google",
    }


# ── Browser Setup ───────────────────────────────────────
_file_lock = threading.RLock()
_driver_lock = threading.RLock()
_vdisplay = None


def create_driver(headless=True):
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=en-US,en")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-sync")
    options.add_argument("--window-size=1280,800")

    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    last_error = None
    for attempt in range(1, DRIVER_MAX_RETRIES + 1):
        try:
            with _driver_lock:
                kwargs = {
                    "options": options,
                    "use_subprocess": True,
                }
                if CHROME_VERSION:
                    kwargs["version_main"] = CHROME_VERSION
                driver = uc.Chrome(**kwargs)

            driver.set_page_load_timeout(90)
            driver.set_script_timeout(15)
            driver.implicitly_wait(3)
            return driver
        except Exception as e:
            last_error = e
            log_to_file(f"Driver create attempt {attempt}/{DRIVER_MAX_RETRIES} failed: {e}")
            time.sleep(3 * attempt)

    raise Exception(f"Failed to create driver after {DRIVER_MAX_RETRIES} retries: {last_error}")


# ── Process Account ──────────────────────────────────────
def process_account(acc, headless, output_path, results, success_counter):
    email = acc["email"]
    line = acc["line"]
    script_dir = os.path.dirname(os.path.abspath(__file__))

    with _print_lock:
        console.print()
        console.print(f"  [bold blue]{'─' * 56}[/]")
        console.print(f"  [bold white on blue] #{line} [/] [bold bright_white]{email}[/]")
        console.print(f"  [bold blue]{'─' * 56}[/]")

    driver = None
    result = {
        "line": line,
        "email": email,
        "ok": False,
        "refreshToken": None,
        "accessToken": None,
        "expiresAt": None,
        "profileArn": None,
        "authMethod": None,
        "error": None,
    }

    acc_start = time.time()

    def log_fn(msg):
        log_line(line, msg, "info")

    try:
        driver = create_driver(headless=headless)
        tok = perform_kiro_login(driver, acc, log_fn=log_fn, script_dir=script_dir)
        result["ok"] = True
        result["refreshToken"] = tok["refreshToken"]
        result["accessToken"] = tok["accessToken"]
        result["expiresAt"] = tok["expiresAt"]
        result["profileArn"] = tok["profileArn"]
        result["authMethod"] = tok["authMethod"]

        acc_elapsed = time.time() - acc_start
        with _file_lock:
            success_counter[0] += 1
            token_preview = tok['refreshToken'][:24] + "..." if len(tok['refreshToken']) > 24 else tok['refreshToken']
            with _print_lock:
                console.print(f"    [bold green]{'│'}[/] [bold green]✓ SUCCESS[/] [dim]│[/] [dim]{acc_elapsed:.1f}s[/]")
                console.print(f"    [bold green]{'│'}[/] [dim]Token:[/] [bold green]{token_preview}[/]")
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(tok["refreshToken"] + "\n")
            log_to_file(f"[{line}] SUCCESS: {email} token_len={len(tok['refreshToken'])}")

    except Exception as e:
        result["error"] = str(e)
        with _print_lock:
            console.print(f"    [bold red]{'│'}[/] [bold red]✗ FAILED[/] [dim]│[/] [bold red]{e}[/]")
        log_to_file(f"[{line}] FAILED: {email} error={e}")
        if driver:
            try:
                screenshot_path = os.path.join(
                    script_dir,
                    f"debug_{line}_{email.split('@')[0]}.png",
                )
                driver.save_screenshot(screenshot_path)
                with _print_lock:
                    console.print(f"    [bold red]{'│'}[/] [dim]Screenshot: {screenshot_path}[/]")
                log_to_file(f"[{line}] Screenshot: {screenshot_path}")
            except Exception:
                pass

    finally:
        with _file_lock:
            results.append(result)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            try:
                import gc
                gc.collect()
            except Exception:
                pass


# ── Main ────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Kiro Refresh Token Generator v3.0 Premium",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python kiro.py                               # All accounts, 1 thread
  python kiro.py 5                             # 5 accounts, 1 thread
  python kiro.py all 3                         # All accounts, 3 threads
  python kiro.py 10 5 --visible                # 10 accounts, 5 threads, visible
  python kiro.py 10 5 -f my_accounts.txt       # Custom file
  python kiro.py 10 5 -o tokens.txt            # Custom output
  python kiro.py 10 5 --out-json results.json  # JSON output
        """,
    )
    parser.add_argument("jumlah", nargs="?", default="all", help="Jumlah akun (default: all)")
    parser.add_argument("thread", nargs="?", type=int, default=1, help="Thread paralel (default: 1)")
    parser.add_argument("-f", "--file", type=str, default="accounts.txt", help="File akun")
    parser.add_argument("-o", "--output", type=str, default="refresh_tokens.txt", help="Output file")
    parser.add_argument("--visible", action="store_true", help="Tampilkan browser")
    parser.add_argument("--out-json", type=str, default=None, help="Output JSON")

    args = parser.parse_args()
    num_workers = max(1, args.thread)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    init_log_file(script_dir)
    log_to_file(f"Script started: {len(args.file)} threads={num_workers}")

    # Cleanup zombie chrome processes
    try:
        import subprocess
        subprocess.run(["pkill", "-f", "chrome.*--no-sandbox"], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True, timeout=5)
    except Exception:
        pass

    # Banner
    print_banner()

    # Check dependencies
    deps_ok = True
    dep_rows = []

    if CHROME_VERSION:
        dep_rows.append(("Chrome Version", f"[bold green]✓ v{CHROME_VERSION} (auto-detected)[/]"))
    else:
        dep_rows.append(("Chrome Version", "[bold red]✗ NOT FOUND (run install.sh)[/]"))
        deps_ok = False

    if HAS_DDDDOCR:
        dep_rows.append(("CAPTCHA Engine", "[bold green]✓ ddddocr (ML-based)[/]"))
    else:
        dep_rows.append(("CAPTCHA Engine", "[bold red]✗ NOT INSTALLED[/]"))
        deps_ok = False

    if HAS_TESSERACT:
        dep_rows.append(("OCR Fallback", "[bold green]✓ pytesseract[/]"))
    else:
        dep_rows.append(("OCR Fallback", "[bold red]✗ NOT INSTALLED[/]"))
        deps_ok = False

    if not deps_ok:
        print_config_table(dep_rows)
        fail("Missing dependencies! Run: bash install.sh")
        return

    # Check Litensi OTP
    otp_check = LitensiOTP(LITENSI_API_KEY)
    otp_balance = otp_check.get_balance()
    if otp_balance is not None:
        dep_rows.append(("OTP Provider", f"[bold green]✓ Litensi.id[/]  [dim]Balance:[/] [bold yellow]{otp_balance} IDR[/]"))
    else:
        dep_rows.append(("OTP Provider", "[bold yellow]⚠ Litensi.id (balance check failed)[/]"))
    dep_rows.append(("OTP Config", "[dim]service=Google(go)  country=Indonesia(6)  operator=any[/]"))

    print_config_table(dep_rows)

    # Read accounts
    file_path = args.file
    if not os.path.isabs(file_path):
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_path)

    all_accounts = read_accounts(file_path)
    if not all_accounts:
        fail(f"Tidak ada akun valid di {file_path}")
        console.print("  [dim]Format: email:password[:totp_secret][/]")
        return

    if args.jumlah != "all":
        try:
            limit = int(args.jumlah)
            accounts = all_accounts[:limit]
        except ValueError:
            fail(f"Jumlah tidak valid: {args.jumlah}")
            return
    else:
        accounts = all_accounts

    # Config table
    config_rows = [
        ("Input File", file_path),
        ("Output File", args.output),
        ("Accounts", f"{len(accounts)}" + (f" (of {len(all_accounts)} total)" if args.jumlah != "all" and len(all_accounts) > len(accounts) else "")),
        ("Threads", str(num_workers)),
        ("Mode", "Visible" if args.visible else "Headless (Xvfb)"),
    ]
    print_config_table(config_rows)

    headless = not args.visible
    results = []
    success_counter = [0]
    start_time = time.time()

    # Prepare output path
    output_path = args.output
    if not os.path.isabs(output_path):
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_path)

    with open(output_path, "w", encoding="utf-8") as f:
        pass

    # Start virtual display
    global _vdisplay
    if headless and HAS_VDISPLAY:
        _vdisplay = Display(visible=False, size=(1280, 800))
        _vdisplay.start()
        info("Virtual display (Xvfb) started")
    elif headless and not HAS_VDISPLAY:
        fail("pyvirtualdisplay not installed. Run: pip install pyvirtualdisplay")
        return

    # Init CAPTCHA solver
    if HAS_DDDDOCR:
        step("Initializing CAPTCHA solver...")
        get_ddddocr()
        ok("CAPTCHA solver ready")
    console.print()

    # Progress bar
    total_accounts = len(accounts)
    completed = [0]

    def update_progress():
        completed[0] += 1
        pct = completed[0] / total_accounts * 100
        bar_len = 30
        filled = int(bar_len * completed[0] / total_accounts)
        bar = "█" * filled + "░" * (bar_len - filled)
        with _print_lock:
            console.print(f"\r  [bold cyan]Progress:[/] [bold green]{bar}[/] [bold white]{completed[0]}/{total_accounts}[/] [dim]({pct:.0f}%)[/]")

    try:
        if num_workers == 1:
            for acc in accounts:
                process_account(acc, headless, output_path, results, success_counter)
                update_progress()
        else:
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = {
                    executor.submit(process_account, acc, headless, output_path, results, success_counter): acc
                    for acc in accounts
                }
                for future in as_completed(futures):
                    future.result()
                    update_progress()
    finally:
        if _vdisplay:
            _vdisplay.stop()

    elapsed = time.time() - start_time

    # Summary
    failed_count = total_accounts - success_counter[0]
    print_summary_panel(total_accounts, success_counter[0], failed_count, output_path, elapsed, num_workers)

    # JSON output
    if args.out_json:
        json_path = args.out_json
        if not os.path.isabs(json_path):
            json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), json_path)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        info(f"JSON output: {json_path}")
        console.print()

    # Done
    with _print_lock:
        console.print(Align.center(Text("━" * 56, style="bold blue")))
        console.print(Align.center(Text("  ✓ EXECUTION COMPLETE  ", style="bold white on blue")))
        console.print(Align.center(Text("━" * 56, style="bold blue")))
        console.print()

    # Close log file
    global _log_file_handle
    if _log_file_handle:
        try:
            _log_file_handle.close()
        except Exception:
            pass
        _log_file_handle = None

    # Cleanup zombie processes
    try:
        import subprocess
        subprocess.run(["pkill", "-f", "chrome.*--no-sandbox"], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True, timeout=5)
    except Exception:
        pass


if __name__ == "__main__":
    main()
