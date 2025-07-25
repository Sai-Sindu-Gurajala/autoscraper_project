from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from .window_utils import move_chrome_window


def launch_browser(url):
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(url)
    return driver

def close_browser(driver):
    driver.quit()

def inject_highlight_script(driver):
    highlight_script = """
    window._autoscraper_highlightListener = function(event) {
        event.preventDefault();
        event.stopPropagation();
        var elem = event.target;
        elem.style.outline = '2px solid red';
        window.selectedElement = elem;
    };
    document.addEventListener('click', window._autoscraper_highlightListener, true);
    """
    driver.execute_script(highlight_script)

def remove_highlight_script(driver):
    remove_script = """
    document.removeEventListener('click', window._autoscraper_highlightListener, true);
    """
    driver.execute_script(remove_script)

def get_selected_element_info(driver):
    selected = driver.execute_script("return window.selectedElement")
    if selected:
        tag = selected.tag_name
        classes = selected.get_attribute('class')
        text = selected.text
        html = selected.get_attribute('outerHTML')
        return {'tag': tag, 'class': classes, 'text': text, 'html': html}
    return None

def get_selected_element_selector(driver):
    selected = driver.execute_script("return window.selectedElement")
    if selected:
        tag = selected.tag_name
        elem_id = selected.get_attribute('id')
        classes = selected.get_attribute('class')
        if elem_id:
            selector = f"#{elem_id}"
        elif classes:
            first_class = classes.split()[0]
            selector = f"{tag}.{first_class}"
        else:
            selector = tag
        return selector
    return None

def extract_current_page_items(driver, elem):
    items = []
    if elem['class']:
        class_name = elem['class'].split()[0]
        elements = driver.find_elements(By.CLASS_NAME, class_name)
        for el in elements:
            if elem['tag'].lower() == 'img':
                items.append({
                    'src': el.get_attribute('src'),
                    'alt': el.get_attribute('alt'),
                    'title': el.get_attribute('title')
                })
            elif elem['tag'].lower() == 'a':
                items.append({
                    'text': el.text.strip(),
                    'href': el.get_attribute('href')
                })
            else:
                text = el.text.strip()
                if text:
                    items.append({'text': text})
    elif elem['tag']:
        tag_name = elem['tag']
        elements = driver.find_elements(By.TAG_NAME, tag_name)
        for el in elements:
            if elem['tag'].lower() == 'img':
                items.append({
                    'src': el.get_attribute('src'),
                    'alt': el.get_attribute('alt'),
                    'title': el.get_attribute('title')
                })
            elif elem['tag'].lower() == 'a':
                items.append({
                    'text': el.text.strip(),
                    'href': el.get_attribute('href')
                })
            else:
                text = el.text.strip()
                if text:
                    items.append({'text': text})
    return items

def extract_nested_fields_manual(driver, detail_url, nested_selectors):
    """
    For each selector (user named), extract .text or .src if it's an image.
    Returns dict: {field_name: value}
    """
    nested_data = {}
    try:
        driver.get(detail_url)
        for field, selector in nested_selectors.items():
            try:
                el = driver.find_element(By.CSS_SELECTOR, selector)
                if el.tag_name.lower() == "img":
                    nested_data[field] = el.get_attribute("src")
                else:
                    nested_data[field] = el.text.strip()
            except Exception:
                nested_data[field] = None
    except Exception:
        for field in nested_selectors:
            nested_data[field] = None
    return nested_data

def launch_browser(url):
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(url)
    # Move Chrome window to the left
    try:
        move_chrome_window()
    except Exception as e:
        print(f"Warning: Could not move Chrome window: {e}")
    return driver
