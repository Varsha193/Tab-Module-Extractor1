# tab_extractor_backend.py
"""
Tab Module Extractor backend using Selenium.
Provides:
- start_browser(headless=False)
- extract_tabs(driver, url)
- click_tab_and_extract_url(driver, tab_info, wait_timeout=8)
- extract_all_tab_modules(driver, url)
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, ElementClickInterceptedException
)
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import time, os, base64
from PIL import Image
from io import BytesIO

def start_browser(headless=False, window_size=(1366, 768)):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument(f"--window-size={window_size[0]},{window_size[1]}")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(30)
    return driver

# Utility JS to compute an XPath for an element
GET_XPATH_JS = """
function absoluteXPath(element) {
    if (element.id!=='')
        return 'id(\"' + element.id + '\")';
    var comp, comps = [];
    var parent = null;
    var xpath = '';
    var getPos = function(element) {
        var position = 1;
        var sibling = element.previousSibling;
        while (sibling) {
            if (sibling.nodeType === Node.DOCUMENT_TYPE_NODE) {
                sibling = sibling.previousSibling;
                continue;
            }
            if (sibling.nodeName === element.nodeName) {
                position++;
            }
            sibling = sibling.previousSibling;
        }
        return position;
    }

    if (element instanceof Document)
        return '/';

    for (; element && !(element instanceof Document); element = element.nodeType === Node.ATTRIBUTE_NODE ? element.ownerElement : element.parentNode) {
        comp = {};
        switch (element.nodeType) {
            case Node.TEXT_NODE:
                comp.name = 'text()';
                break;
            case Node.ELEMENT_NODE:
                comp.name = element.nodeName;
                break;
            case Node.ATTRIBUTE_NODE:
                comp.name = '@' + element.nodeName;
                break;
            default:
                comp.name = '';
        }
        comp.position = getPos(element);
        comps.push(comp);
    }

    for (var i = comps.length - 1; i >= 0; i--) {
        comp = comps[i];
        xpath += '/' + comp.name.toLowerCase();
        if (comp.position !== 1) {
            xpath += '[' + comp.position + ']';
        }
    }

    return xpath;
}
return absoluteXPath(arguments[0]);
"""

def element_to_xpath(driver, elem):
    try:
        xp = driver.execute_script(GET_XPATH_JS, elem)
        return xp
    except Exception:
        return None

def safe_find_tabs(driver):
    """
    Heuristics for finding tab elements:
    - role="tab"
    - role="tablist" children
    - common classes: nav-tabs, tabs, tablist
    - data-toggle="tab"
    """
    candidates = []
    try:
        # role=tab
        tabs = driver.find_elements(By.XPATH, "//*[translate(@role,'TAB','tab')='tab']")
        candidates += tabs
    except Exception:
        pass

    try:
        # data-toggle=tab (bootstrap)
        tabs = driver.find_elements(By.CSS_SELECTOR, '[data-toggle="tab"], [data-bs-toggle="tab"]')
        candidates += tabs
    except Exception:
        pass

    # common class tokens
    class_queries = [
        "//*[contains(@class,'nav-tabs') or contains(@class,'tab') or contains(@class,'tabs') or contains(@class,'tablist')]"
    ]
    for q in class_queries:
        try:
            elems = driver.find_elements(By.XPATH, q)
            candidates += elems
        except Exception:
            pass

    # De-duplicate by id/outerHTML
    unique = []
    seen = set()
    for e in candidates:
        try:
            outer = e.get_attribute("outerHTML")
            if outer and outer not in seen:
                unique.append(e)
                seen.add(outer)
        except StaleElementReferenceException:
            continue
    return unique

def extract_tabs(driver, url, max_wait=10):
    """
    Load page and find tab elements.
    Returns list of dicts: { 'name': str, 'xpath': str, 'text': str, 'element_preview': str }
    """
    result = []
    driver.get(url)
    WebDriverWait(driver, max_wait).until(lambda d: d.execute_script("return document.readyState") == "complete")
    # heuristic elements
    candidates = safe_find_tabs(driver)
    # Also try to find clickable anchors inside navs etc.
    anchors = driver.find_elements(By.XPATH, "//nav//a | //ul[contains(@class,'nav')]//a | //div[contains(@class,'tab')]//a")
    candidates += anchors

    # Normalize and create locators; prefer role=tab children text
    for elem in candidates:
        try:
            text = elem.text.strip() or elem.get_attribute("aria-label") or elem.get_attribute("title") or ""

            xpath = element_to_xpath(driver, elem)
            preview = elem.get_attribute("outerHTML")[:500]
            if xpath:
                result.append({
                    "name": (text[:40] if text else "tab"),
                    "text": text,
                    "xpath": xpath,
                    "preview": preview
                })
        except StaleElementReferenceException:
            continue
    # De-duplicate by xpath
    seen_x = set()
    dedup = []
    for r in result:
        if r["xpath"] not in seen_x:
            dedup.append(r)
            seen_x.add(r["xpath"])
    return dedup

def _take_screenshot(driver, save_path=None):
    png = driver.get_screenshot_as_png()
    img = Image.open(BytesIO(png))
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        img.save(save_path)
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def click_tab_and_extract_url(driver, tab_info, wait_timeout=8, screenshot_dir=None):
    """
    Click the tab described by tab_info (expects 'xpath') and return a result dict:
    { 'requested_name', 'final_url', 'page_title', 'screenshot_base64', 'status', 'error', 'elapsed' }
    """
    start_url = driver.current_url
    start_ts = time.time()
    xpath = tab_info["xpath"]
    try:
        elem = WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.XPATH, xpath)))
        # attempt to click - prefer JavaScript if normal click fails
        try:
            WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            elem.click()
        except (ElementClickInterceptedException, Exception):
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
            try:
                elem.click()
            except Exception:
                driver.execute_script("arguments[0].click();", elem)

        # Wait for either URL change OR DOM change (with small heuristics)
        try:
            WebDriverWait(driver, wait_timeout).until(lambda d: d.current_url != start_url)
            changed = True
        except TimeoutException:
            # sometimes the URL doesn't change; wait a moment for content to load
            time.sleep(1)
            changed = (driver.current_url != start_url)

        end_url = driver.current_url
        title = driver.title
        screenshot_b64 = _take_screenshot(driver, save_path=(os.path.join(screenshot_dir, f"{int(time.time()*1000)}.png") if screenshot_dir else None))
        elapsed = time.time() - start_ts
        return {
            "requested_name": tab_info.get("name"),
            "requested_text": tab_info.get("text"),
            "xpath": xpath,
            "status": "success",
            "initial_url": start_url,
            "final_url": end_url,
            "url_changed": changed,
            "page_title": title,
            "screenshot_base64": screenshot_b64,
            "elapsed": elapsed,
            "error": None
        }
    except Exception as ex:
        elapsed = time.time() - start_ts
        return {
            "requested_name": tab_info.get("name"),
            "xpath": xpath,
            "status": "error",
            "initial_url": start_url,
            "final_url": driver.current_url if driver else None,
            "url_changed": False,
            "page_title": driver.title if driver else None,
            "screenshot_base64": None,
            "elapsed": elapsed,
            "error": repr(ex)
        }

def extract_all_tab_modules(driver, url, screenshot_dir=None):
    """
    High-level convenience to:
    - navigate to url
    - detect tabs
    - sequentially click each tab and capture results
    Returns: { 'tabs': [tab_info...], 'results': [click_result...] }
    """
    tabs = extract_tabs(driver, url)
    results = []
    # Click each tab; optionally refresh the page before each click to avoid stale references
    for t in tabs:
        try:
            # reload to avoid stale elements (if required)
            driver.get(url)
            WebDriverWait(driver, 6).until(lambda d: d.execute_script("return document.readyState") == "complete")
            res = click_tab_and_extract_url(driver, t, wait_timeout=8, screenshot_dir=screenshot_dir)
            results.append(res)
        except Exception as e:
            results.append({
                "requested_name": t.get("name"),
                "xpath": t.get("xpath"),
                "status": "error",
                "error": repr(e)
            })
    return {"tabs": tabs, "results": results}
