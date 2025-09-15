# -*- coding: utf-8 -*-

"""
Core scraping utilities for Autoscraper (hardened).

Public API is unchanged:
- launch_browser
- auto_detect_and_highlight_cards
- find_product_cards
- extract_cards_from_container
- wait_for_next_button_click
- wait_for_product_card_click
- begin_detail_field_capture / finish_detail_field_capture
- extract_fields_from_card / extract_fields_from_detail_page
- ensure_on_listing_page
- scrape_with_locked_container
"""

import os
import time
from typing import List, Dict, Tuple, Callable, Optional, Any

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    StaleElementReferenceException,
    NoSuchElementException,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

from autoscraper_core.pathing import resource_path


# =========================
# Browser launcher
# =========================

def launch_browser(url: str, headless: bool = False) -> webdriver.Chrome:
    """Launch Chrome tuned for scraping speed/stability."""
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--start-maximized")
    opts.add_argument("--log-level=3")
    opts.set_capability("pageLoadStrategy", "eager")
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
    })

    driver_path = resource_path(os.path.join("assets", "chromedriver.exe"))
    if not os.path.exists(driver_path):
        raise FileNotFoundError(f"ChromeDriver not found at: {driver_path}")

    service = Service(executable_path=driver_path, log_path=os.devnull)
    driver = webdriver.Chrome(service=service, options=opts)
    driver.get(url)

    # Best-effort: hide sticky overlays & cookie bars
    try:
        driver.execute_script("""
            try {
              const kill = (sel) => document.querySelectorAll(sel).forEach(el => {
                const pos = getComputedStyle(el).position;
                if (pos === 'fixed' || pos === 'sticky') el.style.display='none';
              });
              ['[style*="z-index"]', '.modal', '.popup', '.banner', '.cookie', '.ads', '.sticky', '.fixed'].forEach(kill);
            } catch (e) {}
        """)
    except Exception:
        pass
    return driver


# =========================
# Generic helpers
# =========================

def _js_unique_selector() -> str:
    return r"""
        function cssPath(el) {
            if (!el || !(el instanceof Element)) return "";
            if (el.id) return el.tagName.toLowerCase() + '#' + el.id;
            let path = [];
            while (el && el.nodeType === Node.ELEMENT_NODE) {
                let sel = el.tagName.toLowerCase();
                if (el.className) {
                    let cls = ("" + el.className).trim().split(/\s+/).slice(0,4).join('.');
                    if (cls) sel += '.' + cls;
                }
                let sib = el, nth = 1;
                while ((sib = sib.previousElementSibling)) nth++;
                sel += ":nth-child(" + nth + ")";
                path.unshift(sel);
                if (el.parentNode && el.parentNode.id) {
                    path.unshift(el.parentNode.tagName.toLowerCase() + '#' + el.parentNode.id);
                    break;
                }
                el = el.parentNode;
            }
            return path.join(" > ");
        }
    """


def get_unique_selector(driver, element) -> str:
    return driver.execute_script(f"""
        {_js_unique_selector()}
        return cssPath(arguments[0]);
    """, element)


def highlight_element_by_selector(driver, selector: str, color: str = "#e05050", width: int = 4):
    driver.execute_script(
        """
        try {
            var el = document.querySelector(arguments[0]);
            if (el) {
                el.scrollIntoView({behavior: 'auto', block: 'center', inline: 'nearest'});
                el.style.outline = arguments[2] + 'px solid ' + arguments[1];
                el.style.boxShadow = '0 0 0 2px rgba(224,80,80,0.25)';
            }
        } catch (e) {}
        """,
        selector, color, int(width)
    )


def _outline_card(driver, card):
    try:
        driver.execute_script("""
            arguments[0].style.outline='3px solid red';
            let colors = ['#39d353','#e6b700','#e05050','#3898fc','#9a59b5','#ff8800'];
            let k=0;
            for (let el of arguments[0].querySelectorAll('*')) {
                if (el.tagName==='IMG') el.style.outline='2px dashed #3898fc';
                else if (el.tagName==='A') el.style.outline='2px dashed #e6b700';
                else if ((el.innerText||'').trim().length>2) el.style.outline='2px solid '+colors[k++%colors.length];
            }
        """, card)
    except Exception:
        pass


def _area_ok(el) -> bool:
    try:
        return el.size.get("width", 0) >= 60 and el.size.get("height", 0) >= 60
    except Exception:
        return False


def _has_link_or_img(el) -> bool:
    try:
        if el.find_elements(By.XPATH, ".//a[@href]"):
            return True
    except Exception:
        pass
    try:
        if el.find_elements(By.XPATH, ".//img[@src]"):
            return True
    except Exception:
        pass
    return False


# =========================
# Auto-detect: container + cards
# =========================

def _score_card_like(children: List[Any]) -> List[Any]:
    """Keep elements that look like cards: size + link/img or some text."""
    out = []
    for c in children:
        try:
            if not _area_ok(c):
                continue
            if _has_link_or_img(c) or (c.text or "").strip():
                out.append(c)
        except Exception:
            continue
    return out


def _most_common_tag_and_class(elems: List[Any]) -> Tuple[str, str]:
    """
    From a set of candidate tiles, derive a (tag, classString) pair to use for CSS selection.
    Stable classes are those without digits and not obviously stateful.
    """
    freq: Dict[Tuple[str, str], int] = {}
    for e in elems:
        try:
            tag = e.tag_name.lower()
            classes = (e.get_attribute("class") or "").strip().split()
            keep = []
            for cls in classes:
                if any(k in cls.lower() for k in ("active", "selected", "current", "hover", "focus")):
                    continue
                if any(ch.isdigit() for ch in cls):
                    continue
                keep.append(cls)
            key = (tag, " ".join(keep))
            freq[key] = freq.get(key, 0) + 1
        except Exception:
            continue
    if not freq:
        # fallback: just use tag of first
        try:
            e0 = elems[0]
            return e0.tag_name.lower(), (e0.get_attribute("class") or "")
        except Exception:
            return "div", ""
    # pick by max frequency, then by length of class string (prefer specific)
    best = sorted(freq.items(), key=lambda kv: (kv[1], len(kv[0][1])), reverse=True)[0][0]
    return best[0], best[1]


def _visible_region_y(driver) -> int:
    """Approx y position where main content likely starts (below header)."""
    try:
        y = driver.execute_script("""
            try {
              const hdr = document.querySelector('header, .header, [class*="header"]');
              if (!hdr) return 0;
              const r = hdr.getBoundingClientRect();
              return Math.max(0, Math.floor(r.bottom + window.scrollY));
            } catch(e) { return 0; }
        """)
        return int(y or 0)
    except Exception:
        return 0


def _candidate_containers_first_pass(driver) -> List[Any]:
    selectors = [
        # common ecommerce/listing wrappers
        '[id*="product"]', '[class*="product"]', '[class*="listing"]',
        '[class*="grid"]', '[class*="cards"]', '[class*="results"]',
        '[class*="catalog"]', '[class*="items"]', '[class*="search"]',
        '#products', '#productsContainer',
    ]
    found = []
    for sel in selectors:
        try:
            found.extend(driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception:
            pass
    # de-dupe while preserving order
    seen = set()
    uniq = []
    for el in found:
        try:
            key = el.id
        except Exception:
            key = None
        if key and key not in seen:
            uniq.append(el)
            seen.add(key)
    return uniq


def _children_or_descendants(container: Any) -> List[Any]:
    """
    Prefer direct children; if those are too few or non uniform,
    look one level deeper (grandchildren) and also handle <ul><li>.
    """
    try:
        kids = container.find_elements(By.XPATH, "./*")
    except Exception:
        kids = []

    # Handle <ul>/<ol> grids
    try:
        tag = container.tag_name.lower()
        if tag in ("ul", "ol"):
            lis = container.find_elements(By.XPATH, "./li")
            if len(lis) >= 2:
                return lis
    except Exception:
        pass

    if len(kids) >= 2:
        return kids

    # one level deeper if container uses rows/cols wrappers
    try:
        grand = container.find_elements(By.XPATH, "./*/*")
        if len(grand) >= 3:
            return grand
    except Exception:
        pass

    return kids


def find_product_cards(driver, max_containers: int = 300, early_break_count: int = 8) -> Tuple[List, Optional[object]]:
    """
    Heuristic: find a container that holds many similar, card-like nodes.
    Two passes: (1) targeted selectors, (2) generic structural tags.
    """
    min_y = _visible_region_y(driver)

    # ----- PASS 1: targeted selectors
    candidates = _candidate_containers_first_pass(driver)

    # ----- PASS 2 (fallback): everything structural, bounded by max_containers
    if not candidates:
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, "div, section, article, ul, ol")
        except Exception:
            candidates = []

    best_cards: List = []
    container_element = None
    best_score = (0, 0)  # (count, uniformityBonus)

    for idx, container in enumerate(candidates[:max_containers]):
        try:
            # skip elements fully above header/footer regions
            top = container.location.get("y", 0)
            if min_y and top and top + 20 < min_y:
                continue

            nodes = _children_or_descendants(container)
            if len(nodes) < 2 or len(nodes) > 160:
                continue

            filtered = _score_card_like(nodes)
            if len(filtered) < 2:
                continue

            # crude uniformity: how many share the same tag
            tag_counts: Dict[str, int] = {}
            for n in filtered:
                try:
                    tg = n.tag_name.lower()
                    tag_counts[tg] = tag_counts.get(tg, 0) + 1
                except Exception:
                    pass
            uniformity = max(tag_counts.values()) if tag_counts else 0

            score = (len(filtered), uniformity)
            if score > best_score:
                best_score = score
                best_cards = filtered
                container_element = container

            if len(filtered) >= early_break_count and uniformity >= 2:
                break
        except Exception:
            continue

    return best_cards, container_element


def auto_detect_and_highlight_cards(driver, max_preview_cards: int = 12) -> Tuple[List[Dict], str, str, str]:
    """Detect a plausible container + card family; highlight a preview slice."""
    cards, container_element = find_product_cards(driver)
    if not cards or not container_element:
        return [], "", "", ""

    # Derive a robust card family (tag + stable class set)
    card_tag, stable_classes = _most_common_tag_and_class(cards)
    container_selector = get_unique_selector(driver, container_element)
    card_class = stable_classes

    # Limit preview to avoid heavy UI on very large grids
    preview_data: List[Dict] = []
    for card in cards[: max(1, min(len(cards), max_preview_cards))]:
        _outline_card(driver, card)
        try:
            preview_data.append(extract_fields_from_card(card))
        except Exception:
            preview_data.append({})

    return preview_data, container_selector, card_tag, card_class


# =========================
# Extract cards by locked family
# =========================

def extract_cards_from_container(driver, container_selector: str, card_tag: str, card_class: str):
    try:
        container = driver.find_element(By.CSS_SELECTOR, container_selector)
    except Exception:
        return []

    # if class string is present, build ".a.b.c" selector
    try:
        if card_class and card_class.strip():
            classes = ".".join(card_class.strip().split())
            sel = f"{card_tag}.{classes}"
            cards = container.find_elements(By.CSS_SELECTOR, sel)
            if cards:
                return cards
    except Exception:
        pass

    # fallback: tag only
    try:
        cards = container.find_elements(By.CSS_SELECTOR, card_tag)
        if cards:
            return cards
    except Exception:
        pass

    # last resort: popular inner wrappers under container (defensive)
    for sel in [".product", ".card", ".item", ".tile", "li", "article", "div"]:
        try:
            cards = container.find_elements(By.CSS_SELECTOR, sel)
            if len(cards) >= 2:
                return cards
        except Exception:
            continue
    return []


def has_container(driver, container_selector: str) -> bool:
    try:
        driver.find_element(By.CSS_SELECTOR, container_selector)
        return True
    except Exception:
        return False


def ensure_on_listing_page(
    driver,
    container_selector: str,
    listing_url: Optional[str],
    log_callback: Optional[Callable[[str], None]] = None,
    wait: int = 12,
) -> None:
    """Guarantee we’re on a page where the listing container exists."""
    try:
        if has_container(driver, container_selector):
            return

        for handle in list(driver.window_handles):
            try:
                driver.switch_to.window(handle)
                if has_container(driver, container_selector):
                    return
            except Exception:
                pass

        for _ in range(2):
            try:
                driver.back()
                WebDriverWait(driver, wait).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, container_selector))
                )
                return
            except Exception:
                pass

        if listing_url:
            driver.get(listing_url)
            WebDriverWait(driver, wait).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, container_selector))
            )
    except Exception as e:
        if log_callback:
            log_callback(f"Failed to return to listing page: {e}")


# =========================
# Field extraction (card & detail)
# =========================

def extract_fields_from_card(card) -> Dict:
    data: Dict[str, str] = {}

    # Prefer obvious title nodes first
    try:
        title_nodes = card.find_elements(By.CSS_SELECTOR, "h1,h2,h3,h4,h5,h6, a, .title, [class*='title']")
    except Exception:
        title_nodes = []
    titles = []
    for el in title_nodes[:6]:
        try:
            t = (el.text or "").strip()
            if t and t not in titles:
                titles.append(t)
        except Exception:
            pass

    # General text (de-duped)
    try:
        text_els = card.find_elements(By.XPATH, ".//*[normalize-space(string())!='']")
    except Exception:
        text_els = []
    text_values: List[str] = []
    for el in text_els:
        try:
            txt = el.text.strip()
        except Exception:
            continue
        if txt and txt not in text_values and len(txt) > 1:
            text_values.append(txt)

    # Links
    links: List[str] = []
    try:
        for el in card.find_elements(By.XPATH, ".//a[@href]"):
            try:
                href = el.get_attribute("href")
                if href and href not in links:
                    links.append(href)
            except Exception:
                continue
    except Exception:
        pass

    # Images
    imgs: List[str] = []
    try:
        for el in card.find_elements(By.XPATH, ".//img[@src]"):
            try:
                src = el.get_attribute("src")
                if src and src not in imgs:
                    imgs.append(src)
            except Exception:
                continue
    except Exception:
        pass

    # Fill data
    # Title (if found)
    if titles:
        data["Text 1"] = titles[0]
        # keep remaining to preserve original column naming style
        offset = 2
    else:
        offset = 1

    # Add a few more distinct texts
    for i, t in enumerate(text_values[:8], start=offset):
        key = f"Text {i}"
        if key not in data:
            data[key] = t

    for i, l in enumerate(links[:10], start=1):
        data[f"Link {i}"] = l
    for i, s in enumerate(imgs[:10], start=1):
        data[f"Image {i}"] = s

    # Description = longest text
    all_txt = titles + text_values
    if all_txt:
        data["Description"] = max(all_txt, key=len)

    return data


def extract_fields_from_detail_page(driver, selectors: List[Dict[str, str]]) -> Dict:
    out: Dict[str, str] = {}
    for cfg in selectors:
        name = cfg.get("name") or "Field"
        sel = cfg.get("selector") or ""
        attr = (cfg.get("attr") or "text").lower()
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if attr == "text":
                out[name] = (el.text or "").strip()
            else:
                out[name] = el.get_attribute(attr) or ""
        except Exception:
            out[name] = ""
    return out


# =========================
# Learn pagination by real click
# =========================

def wait_for_next_button_click(driver, timeout: int = 90) -> str:
    js = f"""
    window._autoscraper_pagination_selector = null;
    (function() {{
        {_js_unique_selector()}
        function pickClickable(target) {{
            if (!target) return null;
            var a = target.closest('a[href]');
            if (a) return a;
            var b = target.closest('button,[role="button"]');
            if (b) return b;
            var c = target.closest('li,div,span') || target;
            return c;
        }}
        function clickHandler(e) {{
            e.preventDefault();
            e.stopPropagation();
            var t = pickClickable(e.target);
            if (!t) t = e.target;
            try {{
                t.scrollIntoView({{behavior:'auto', block:'center'}});
                t.style.outline = '4px solid #e05050';
                t.style.boxShadow = '0 0 0 2px rgba(224,80,80,.25)';
            }} catch(_){{}}
            window._autoscraper_pagination_selector = cssPath(t);
            document.removeEventListener('click', clickHandler, true);
        }}
        document.addEventListener('click', clickHandler, true);
    }})();
    """
    driver.execute_script(js)

    start = time.time()
    while True:
        selector = driver.execute_script("return window._autoscraper_pagination_selector;")
        if selector:
            return selector
        if time.time() - start > timeout:
            raise TimeoutError("Timed out waiting for pagination click.")
        time.sleep(0.1)


# =========================
# Learn product card click (generic descendant selector)
# =========================

def wait_for_product_card_click(driver, timeout: int = 90) -> str:
    js = f"""
    window._autoscraper_open_within_selector = null;
    (function(){{
      function simpleSelector(el){{
        if (!el) return "";
        var tag = el.tagName.toLowerCase();
        var keep = [];
        if (el.classList && el.classList.length){{
          for (var i=0; i<Math.min(3, el.classList.length); i++){{
            var cls = el.classList[i];
            if (!/(active|selected|current|hover|focus)/.test(cls) && !/\\d/.test(cls)){{
              keep.push(cls);
            }}
          }}
        }}
        return keep.length ? (tag + "." + keep.join(".")) : tag;
      }}

      function clickHandler(e){{
        e.preventDefault(); e.stopPropagation();
        var a = e.target.closest('a[href]') || e.target;
        window._autoscraper_open_within_selector = simpleSelector(a);
        document.removeEventListener('click', clickHandler, true);
      }}
      document.addEventListener('click', clickHandler, true);
    }})();
    """
    driver.execute_script(js)

    start = time.time()
    while True:
        sel = driver.execute_script("return window._autoscraper_open_within_selector;")
        if sel:
            return sel
        if time.time() - start > timeout:
            raise TimeoutError("Timed out waiting for product-card click.")
        time.sleep(0.1)


# =========================
# Capture detail fields by real clicks
# =========================

def begin_detail_field_capture(driver):
    js = f"""
    (function(){{
      window._autoscraper_detail_fields = [];
      {_js_unique_selector()}
      function onClick(e){{
        e.preventDefault();
        e.stopPropagation();
        var sel = cssPath(e.target);
        if(sel){{
          window._autoscraper_detail_fields.push({{name: 'Field ' + (window._autoscraper_detail_fields.length+1), selector: sel, attr: 'text'}});
          try {{ e.target.style.outline = '3px solid #39d353'; }} catch(err) {{}}
        }}
      }}
      if (window._autoscraper__onDetailClick) {{
        document.removeEventListener('click', window._autoscraper__onDetailClick, true);
      }}
      window._autoscraper__onDetailClick = onClick;
      document.addEventListener('click', onClick, true);
    }})();
    """
    driver.execute_script(js)


def finish_detail_field_capture(driver) -> List[Dict[str, str]]:
    fields = driver.execute_script("return window._autoscraper_detail_fields || [];")
    driver.execute_script("""
      if (window._autoscraper__onDetailClick) {
        document.removeEventListener('click', window._autoscraper__onDetailClick, true);
        window._autoscraper__onDetailClick = null;
      }
    """)
    seen: set = set()
    out: List[Dict[str, str]] = []
    for f in fields:
        name = f.get("name") or "Field"
        base = name
        n = 1
        while name in seen:
            n += 1
            name = f"{base} {n}"
        seen.add(name)
        out.append({"name": name, "selector": f.get("selector", ""), "attr": f.get("attr", "text")})
    return out


# =========================
# Safe click for pagination
# =========================

def safe_click(driver, selector: str, log_callback: Optional[Callable[[str], None]] = None, timeout: int = 8) -> bool:
    try:
        driver.execute_script("""
            try {
                let overlays = [...document.querySelectorAll('[style*="z-index"], .modal, .popup, .banner, .cookie, .ads, .sticky, .fixed')];
                overlays.forEach(el => { const p = getComputedStyle(el).position; if (p==='fixed'||p==='sticky') el.style.display='none'; });
            } catch(e) {}
        """)

        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        elem = driver.find_element(By.CSS_SELECTOR, selector)

        if not elem.is_displayed():
            if log_callback: log_callback("Pagination ended: button not visible.")
            return False
        if not elem.is_enabled():
            if log_callback: log_callback("Pagination ended: button not enabled.")
            return False
        if elem.get_attribute("disabled") or (elem.get_attribute("aria-disabled") or "").lower() == "true":
            if log_callback: log_callback("Pagination ended: button disabled.")
            return False

        driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", elem)
        driver.execute_script("arguments[0].style.outline='4px solid #e05050';", elem)
        WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))

        try:
            elem.click()
        except Exception as click_exc:
            if log_callback: log_callback(f"Selenium click() failed: {click_exc}; retrying JS click.")
            try:
                driver.execute_script("arguments[0].click();", elem)
            except Exception as js_exc:
                if log_callback: log_callback(f"JS click also failed: {js_exc}")
                return False
        return True

    except NoSuchElementException:
        if log_callback: log_callback("Pagination ended: button is gone.")
        return False
    except Exception as e:
        if log_callback: log_callback(f"Safe click failed: {e}")
        return False


# =========================
# Open a product card
# =========================

def _open_link_in_new_tab(driver, href: str):
    driver.execute_script("window.open(arguments[0], '_blank');", href)
    time.sleep(0.4)
    driver.switch_to.window(driver.window_handles[-1])


def open_product_card(driver, target_element) -> bool:
    """Legacy opener: kept for compatibility."""
    try:
        try:
            a = target_element.find_element(By.XPATH, ".//a[@href]")
            href = a.get_attribute("href")
        except Exception:
            a = None
            href = None

        if href:
            _open_link_in_new_tab(driver, href)
            return True

        try:
            target_element.click()
            time.sleep(0.6)
            return True
        except Exception:
            driver.execute_script("arguments[0].click();", target_element)
            time.sleep(0.6)
            return True
    except Exception:
        return False


def open_product_from_card(driver, card, open_within_selector: Optional[str]) -> bool:
    """Open detail page using learned descendant; fall back to first <a> or card click."""
    try:
        targets: List = []
        if open_within_selector:
            try:
                targets = card.find_elements(By.CSS_SELECTOR, open_within_selector)
            except Exception:
                targets = []

        for t in targets:
            try:
                href = t.get_attribute("href")
                if href:
                    _open_link_in_new_tab(driver, href)
                    return True
            except Exception:
                pass

        if targets:
            try:
                try:
                    targets[0].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", targets[0])
                time.sleep(0.5)
                return True
            except Exception:
                pass

        try:
            a = card.find_element(By.XPATH, ".//a[@href]")
            href = a.get_attribute("href")
            if href:
                _open_link_in_new_tab(driver, href)
                return True
        except Exception:
            pass

        try:
            card.click()
            time.sleep(0.6)
            return True
        except Exception:
            driver.execute_script("arguments[0].click();", card)
            time.sleep(0.6)
            return True
    except Exception:
        return False


# =========================
# Scrape loop (with detail extraction)
# =========================

def extract_main_text(card) -> str:
    try:
        return (card.text or "").strip()
    except Exception:
        return ""


def scrape_with_locked_container(
    driver,
    container_selector: str,
    card_tag: str,
    card_class: str,
    pagination_selector: str,
    max_pages: int,
    update_callback: Optional[Callable[[List[Dict], int], None]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    detail_selectors: Optional[List[Dict[str, str]]] = None,
    product_card_selector: Optional[str] = None,
) -> List[Dict]:
    """
    Main loop. For each page:
      - read cards
      - (optional) open detail pages for extra fields
      - update UI via update_callback
      - paginate via learned selector
    """
    seen_keys: set = set()
    all_data: List[Dict] = []
    prev_card_keys: set = set()
    detail_selectors = detail_selectors or []

    # NEW: light throttle for live row-level UI updates
    last_emit = 0.0
    EMIT_INTERVAL = 0.15  # seconds

    for page in range(max_pages):
        time.sleep(0.4)

        cards = extract_cards_from_container(driver, container_selector, card_tag, card_class)
        page_data: List[Dict] = []
        card_keys: set = set()

        base_window = driver.current_window_handle

        for card in cards:
            try:
                d = extract_fields_from_card(card)
            except StaleElementReferenceException:
                continue

            key = (d.get("Text 1", ""), d.get("Link 1", ""), d.get("Image 1", ""))
            if key in seen_keys:
                continue

            seen_keys.add(key)
            card_keys.add(key)

            if detail_selectors and product_card_selector:
                try:
                    before_handles = set(driver.window_handles)
                    if open_product_from_card(driver, card, product_card_selector):
                        def _nav_happened(drv):
                            now = set(drv.window_handles)
                            if len(now) > len(before_handles):
                                return True
                            return drv.current_url != ''  # cheap same-tab check
                        try:
                            WebDriverWait(driver, 8).until(_nav_happened)
                        except Exception:
                            pass

                        detail_data = extract_fields_from_detail_page(driver, detail_selectors)
                        d.update(detail_data)

                        if len(driver.window_handles) > 1:
                            try: driver.close()
                            except Exception: pass
                            try: driver.switch_to.window(base_window)
                            except Exception: driver.switch_to.window(driver.window_handles[0])
                        else:
                            try:
                                driver.back()
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, container_selector))
                                )
                            except Exception:
                                pass
                except Exception as ex:
                    if log_callback:
                        log_callback(f"Detail extraction failed: {ex}")

            page_data.append(d)
            all_data.append(d)

            # NEW: live per-row preview (throttled)
            if update_callback:
                now = time.time()
                if now - last_emit >= EMIT_INTERVAL:
                    update_callback(list(all_data), page + 1)
                    last_emit = now
                    try:
                        from PyQt5 import QtWidgets
                        QtWidgets.QApplication.processEvents()
                    except Exception:
                        pass

        if not page_data:
            if log_callback:
                log_callback(f"No product cards found at page {page+1}. Stopping.")
            break

        if (card_keys == prev_card_keys and page > 0):
            if log_callback:
                log_callback("Pagination ended: same cards as previous page.")
            break

        prev_card_keys = card_keys

        # still emit a page-level snapshot
        if update_callback:
            update_callback(list(all_data), page + 1)
            try:
                from PyQt5 import QtWidgets
                QtWidgets.QApplication.processEvents()
            except Exception:
                pass

        # paginate
        try:
            prev_first_text = extract_main_text(cards[0]) if cards else ""
            if not safe_click(driver, pagination_selector, log_callback=log_callback):
                break
            WebDriverWait(driver, 12).until(
                lambda d: (
                    extract_cards_from_container(d, container_selector, card_tag, card_class)
                    and extract_main_text(
                        extract_cards_from_container(d, container_selector, card_tag, card_class)[0]
                    ) != prev_first_text
                )
            )
            time.sleep(0.4)
        except Exception as e:
            if log_callback:
                log_callback(f"Couldn't paginate: {e}")
            break

    return all_data
