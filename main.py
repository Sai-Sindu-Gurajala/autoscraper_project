# -*- coding: utf-8 -*-
"""
Autoscraper — single-button Auto Detect + robust table backfill for export.

- Override Container… removed
- Focused Detect merged into Auto Detect internally
- FIX: back-fill earlier rows whenever new columns appear so Excel shows
       Field 1/2/… for the first products too.
"""

import sys, os, datetime
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import QHeaderView, QToolBar, QAction, QStyle
from PyQt5.QtCore import QSize

from autoscraper_core import core
from autoscraper_core.pathing import resource_path

EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
NO_COL_KEY = "__row_no__"


def load_icon(qapp: QtWidgets.QApplication, name: str) -> QtGui.QIcon:
    candidates = [
        resource_path(os.path.join("assets", "icons", f"{name}.svg")),
        resource_path(os.path.join("assets", "icons", f"{name}.png")),
        resource_path(os.path.join("assets", f"{name}.ico")),
    ]
    for p in candidates:
        if os.path.exists(p):
            return QtGui.QIcon(p)
    style = qapp.style()
    fallback = {
        "start": QStyle.SP_MediaPlay,
        "stop": QStyle.SP_BrowserStop,
        "detect": QStyle.SP_DialogYesButton,
        "pagination": QStyle.SP_ArrowForward,
        "card": QStyle.SP_FileDialogListView,
        "open": QStyle.SP_DirOpenIcon,
        "capture": QStyle.SP_DialogApplyButton,
        "done": QStyle.SP_DialogOkButton,
        "scrape": QStyle.SP_BrowserReload,
        "export": QStyle.SP_DialogSaveButton,
        "fit": QStyle.SP_ComputerIcon,
    }.get(name, QStyle.SP_FileIcon)
    return style.standardIcon(fallback)


class ScraperThread(QtCore.QThread):
    log = QtCore.pyqtSignal(str)
    browser_ready = QtCore.pyqtSignal()

    detect_ready = QtCore.pyqtSignal(list, str, str, str)
    pagination_ready = QtCore.pyqtSignal(str)
    product_card_ready = QtCore.pyqtSignal(str)
    product_opened = QtCore.pyqtSignal(bool)
    detail_capture_started = QtCore.pyqtSignal()
    detail_fields_ready = QtCore.pyqtSignal(list)
    detail_capture_progress = QtCore.pyqtSignal(list, dict)
    preview_ready = QtCore.pyqtSignal(list, int)
    scrape_finished = QtCore.pyqtSignal(list)

    do_auto_detect = QtCore.pyqtSignal()
    do_learn_pagination = QtCore.pyqtSignal()
    do_learn_product_card = QtCore.pyqtSignal()
    do_open_first_product = QtCore.pyqtSignal()
    do_start_field_capture = QtCore.pyqtSignal()
    do_finish_field_capture = QtCore.pyqtSignal()
    do_scrape = QtCore.pyqtSignal()

    def __init__(self, url: str, max_pages: int, max_preview_cards: int = 20):
        super().__init__()
        self.url = url
        self.max_pages = max_pages
        self.max_preview_cards = max_preview_cards

        self.driver = None
        self._capture_timer: QtCore.QTimer = None
        self._last_capture_sig = ""

        self.container_selector = None
        self.card_tag = None
        self.card_class = None
        self.pagination_selector = None
        self.product_card_selector = None
        self.detail_selectors = []
        self.scraped_data = []

        self.do_auto_detect.connect(self._auto_detect)
        self.do_learn_pagination.connect(self._learn_pagination)
        self.do_learn_product_card.connect(self._learn_product_card)
        self.do_open_first_product.connect(self._open_first_product)
        self.do_start_field_capture.connect(self._start_field_capture)
        self.do_finish_field_capture.connect(self._finish_field_capture)
        self.do_scrape.connect(self._scrape)

    def run(self):
        try:
            self.driver = core.launch_browser(self.url, headless=False)
            self.log.emit("Browser launched. Click Auto Detect to highlight products.")
            self.browser_ready.emit()
        except Exception as e:
            self.log.emit(f"Error launching browser: {e}")
            return
        self.exec_()

    def stop(self):
        try:
            if self._capture_timer:
                self._capture_timer.stop()
                self._capture_timer.deleteLater()
                self._capture_timer = None
            if self.driver:
                self.driver.quit()
                self.driver = None
                self.log.emit("Browser closed.")
        except Exception:
            pass

    @QtCore.pyqtSlot()
    def _auto_detect(self):
        if not self.driver:
            self.log.emit("Browser not running.")
            return

        def _detect_once():
            self.log.emit("Scanning page for product cards...")
            return core.auto_detect_and_highlight_cards(
                self.driver, max_preview_cards=self.max_preview_cards
            )

        try:
            preview, container_sel, card_tag, card_class = _detect_once()
        except Exception as e:
            self.log.emit(f"Error in auto detect: {e}")
            return

        if not preview or len(preview) < 2:
            try:
                self.driver.execute_script("""
                    try {
                      for (const sel of ['[style*="z-index"]','.modal','.popup','.banner','.cookie',
                                         '.ads','.sticky','.fixed','.header','.footer','#cookie']) {
                        document.querySelectorAll(sel).forEach(el => {
                          const pos = getComputedStyle(el).position;
                          if (pos === 'fixed' || pos === 'sticky') el.style.display='none';
                        });
                      }
                      const hints = [
                        '#productsContainer','[id*="products"]','[id*="product"]',
                        '.product-list','.product-grid','.list','.grid','.items','.cards'
                      ];
                      for (const h of hints) {
                        const el = document.querySelector(h);
                        if (el) { el.scrollIntoView({behavior:'instant', block:'start'}); break; }
                      }
                    } catch(e){}
                """)
                self.log.emit("Auto Detect: focused fallback engaged. Retrying…")
                preview, container_sel, card_tag, card_class = _detect_once()
            except Exception as e:
                self.log.emit(f"Focused retry failed: {e}")

        if preview:
            self.log.emit(f"Detected {len(preview)} product cards.")
        else:
            self.log.emit("No product cards detected.")

        self.container_selector = container_sel
        self.card_tag = card_tag
        self.card_class = card_class
        self.detect_ready.emit(preview, container_sel, card_tag, card_class)

    @QtCore.pyqtSlot()
    def _learn_pagination(self):
        if not self.driver:
            self.log.emit("Browser not running.")
            return
        self.log.emit("Waiting for you to click Next/Load More in the browser...")
        try:
            selector = core.wait_for_next_button_click(self.driver)
            core.highlight_element_by_selector(self.driver, selector)
            self.pagination_selector = selector
            self.log.emit(f"Pagination selector captured:\n{selector}")
            self.pagination_ready.emit(selector)
        except Exception as e:
            self.log.emit(f"Error learning pagination: {e}")

    @QtCore.pyqtSlot()
    def _learn_product_card(self):
        if not self.driver:
            self.log.emit("Browser not running.")
            return
        self.log.emit("Please click a product card (or its link/button) in the browser to learn how to open details...")
        try:
            selector = core.wait_for_product_card_click(self.driver)
            self.product_card_selector = selector
            self.log.emit(f"Product card opener selector captured:\n{selector}")
            self.product_card_ready.emit(selector)
        except Exception as e:
            self.log.emit(f"Error learning product card: {e}")

    @QtCore.pyqtSlot()
    def _open_first_product(self):
        if not self.driver:
            self.log.emit("Browser not running.")
            self.product_opened.emit(False)
            return
        if not all([self.container_selector, self.card_tag]):
            self.log.emit("Run Auto Detect first to lock container and card tag/class.")
            self.product_opened.emit(False)
            return
        if not self.product_card_selector:
            self.log.emit("Learn a product card selector first.")
            self.product_opened.emit(False)
            return
        try:
            cards = core.extract_cards_from_container(
                self.driver, self.container_selector, self.card_tag, self.card_class or ""
            )
            if not cards:
                self.log.emit("Couldn't find any product cards in the locked container.")
                self.product_opened.emit(False)
                return
            ok = core.open_product_from_card(self.driver, cards[0], self.product_card_selector)
            if ok:
                self.log.emit("Opened product detail page. You can now start field capture.")
                self.product_opened.emit(True)
            else:
                self.log.emit("Failed to open product detail page.")
                self.product_opened.emit(False)
        except Exception as e:
            self.log.emit(f"Error opening first product: {e}")
            self.product_opened.emit(False)

    def _poll_capture_progress(self):
        if not self.driver:
            return
        try:
            fields = self.driver.execute_script("""
                try { return window.top._autoscraper_detail_fields || []; }
                catch(e) { return window._autoscraper_detail_fields || []; }
            """)
            sig = repr(fields)
            if sig != self._last_capture_sig:
                self._last_capture_sig = sig
                sample = {}
                if fields:
                    sample = core.extract_fields_from_detail_page(self.driver, fields)
                self.detail_capture_progress.emit(list(fields), dict(sample))
        except Exception:
            pass

    @QtCore.pyqtSlot()
    def _start_field_capture(self):
        if not self.driver:
            self.log.emit("Browser not running.")
            return
        try:
            core.begin_detail_field_capture(self.driver)
            self.log.emit("Field capture started: click fields on the detail page (they’ll highlight in green). When done, click 'Done Fields'.")
            self._last_capture_sig = ""
            self._capture_timer = QtCore.QTimer()
            self._capture_timer.setInterval(250)
            self._capture_timer.timeout.connect(self._poll_capture_progress)
            self._capture_timer.start()
            self.detail_capture_started.emit()
        except Exception as e:
            self.log.emit(f"Could not start field capture: {e}")

    @QtCore.pyqtSlot()
    def _finish_field_capture(self):
        if not self.driver:
            self.log.emit("Browser not running.")
            return
        try:
            if self._capture_timer:
                self._capture_timer.stop()
                self._capture_timer.deleteLater()
                self._capture_timer = None
            fields = core.finish_detail_field_capture(self.driver)
            self.detail_selectors = fields or []
            core.ensure_on_listing_page(self.driver, self.container_selector, self.url, log_callback=self.log.emit)
            if self.detail_selectors:
                self.log.emit(f"Captured {len(self.detail_selectors)} fields from the detail page.")
            else:
                self.log.emit("No fields captured.")
            self.detail_fields_ready.emit(list(self.detail_selectors))
        except Exception as e:
            self.log.emit(f"Error finishing field capture: {e}")

    @QtCore.pyqtSlot()
    def _scrape(self):
        if not self.driver:
            self.log.emit("Browser not running.")
            return
        if not all([self.container_selector, self.card_tag]):
            self.log.emit("Run Auto Detect first.")
            return
        if not self.pagination_selector:
            self.log.emit("Learn pagination first.")
            return
        if not self.product_card_selector:
            self.log.emit("Learn product card first.")
            return

        core.ensure_on_listing_page(self.driver, self.container_selector, self.url, log_callback=self.log.emit)

        self.log.emit("Scraping all pages with learned selectors...")
        self.scraped_data = []

        def preview_cb(all_rows_so_far, page_num):
            self.preview_ready.emit(list(all_rows_so_far), page_num)
            QtWidgets.QApplication.processEvents()

        try:
            self.scraped_data = core.scrape_with_locked_container(
                driver=self.driver,
                container_selector=self.container_selector,
                card_tag=self.card_tag,
                card_class=self.card_class or "",
                pagination_selector=self.pagination_selector,
                max_pages=self.max_pages,
                update_callback=preview_cb,
                log_callback=self.log.emit,
                detail_selectors=list(self.detail_selectors),
                product_card_selector=self.product_card_selector,
            )
            self.preview_ready.emit(list(self.scraped_data), -1)
            self.scrape_finished.emit(list(self.scraped_data))
            self.log.emit("Scraping done! You can now export the data.")
        except Exception as e:
            self.log.emit(f"Error during scraping: {e}")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Autoscraper")
        self.resize(1240, 780)

        w = QtWidgets.QWidget()
        self.setCentralWidget(w)
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(0,0,0,0)

        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(24, 24))
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        tb.setStyleSheet("""
            QToolBar { background: #F2C01D; border: none; padding: 4px; }
            QToolButton { font-weight: 600; padding: 6px 10px; border-radius: 8px; }
            QToolButton:hover { background: rgba(0,0,0,0.06); }
            QToolButton:pressed { background: rgba(0,0,0,0.12); }
        """)
        self.addToolBar(QtCore.Qt.TopToolBarArea, tb)

        app_ref = QtWidgets.QApplication.instance()

        def act(text, icon_name, slot, shortcut=None, tip=None):
            a = QAction(load_icon(app_ref, icon_name), text, self)
            if shortcut: a.setShortcut(shortcut)
            if tip: a.setToolTip(tip); a.setStatusTip(tip)
            a.triggered.connect(slot); tb.addAction(a); return a

        self.act_start   = act("Start",            "start",        self.start,               "Ctrl+R",      "Launch browser on the URL")
        self.act_stop    = act("Stop",             "stop",         self.stop,                "Esc",         "Stop and close browser")
        tb.addSeparator()
        self.act_detect  = act("Auto Detect",      "detect",       self.on_auto_detect,      None,          "Detect product cards (with smart fallback)")
        self.act_pagi    = act("Learn Pagination", "pagination",   self.on_learn_pagination, None,          "Click the real Next/Load More")
        self.act_card    = act("Learn Product Card","card",        self.on_learn_product_card,None,          "Tell me how to open details")
        self.act_open    = act("Open First Product","open",        self.on_open_first_product,None,          "Test opening a detail page")
        self.act_capture = act("Start Capture",    "capture",      self.on_start_field_capture,None,         "Click fields on detail page")
        self.act_done    = act("Done Fields",      "done",         self.on_done_fields,      None,          "Finish field capture")
        tb.addSeparator()
        self.act_scrape  = act("Scrape",           "scrape",       self.on_scrape,           "Ctrl+Enter",  "Run with learned selectors")
        self.act_export  = act("Export",           "export",       self.export_data,         "Ctrl+S",      "Export to Excel")
        tb.addSeparator()
        self.act_fit     = act("Fit Columns",      "fit",          self._autosize_columns,   None,          "Auto fit the result columns")

        row_url = QtWidgets.QHBoxLayout(); row_url.setContentsMargins(6,6,6,4)
        url_label = QtWidgets.QLabel("URL:"); url_label.setMinimumWidth(28)
        self.url_input = QtWidgets.QLineEdit(); self.url_input.setPlaceholderText("https://example.com/products …"); self.url_input.setMinimumHeight(30)
        row_url.addWidget(url_label); row_url.addWidget(self.url_input, 1)
        row_url.addSpacing(10); row_url.addWidget(QtWidgets.QLabel("Max Pages:"))
        self.max_pages = QtWidgets.QSpinBox(); self.max_pages.setRange(1, 999); self.max_pages.setValue(10); self.max_pages.setButtonSymbols(QtWidgets.QAbstractSpinBox.PlusMinus); self.max_pages.setMinimumWidth(64)
        row_url.addWidget(self.max_pages)
        v.addLayout(row_url)

        self.rail = QtWidgets.QListWidget()
        self.rail.setFixedWidth(160); self.rail.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.rail.setIconSize(QSize(18,18))
        self.rail.setStyleSheet("""
            QListWidget { border-right: 1px solid #e7e7ea; background: #faf9f5; }
            QListWidget::item { padding: 8px 8px; border-radius: 6px; }
            QListWidget::item:selected { background: #ffe58a; }
        """)
        def rail_item(text, icon_name): self.rail.addItem(QtWidgets.QListWidgetItem(load_icon(app_ref, icon_name), text))
        for label, icon in [
            ("Start",            "start"),
            ("Auto Detect",      "detect"),
            ("Learn Pagination", "pagination"),
            ("Learn Product Card","card"),
            ("Open First Prod.", "open"),
            ("Capture Fields",   "capture"),
            ("Scrape",           "scrape"),
            ("Export",           "export"),
        ]: rail_item(label, icon)
        self.rail.setCurrentRow(0)

        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMinimumHeight(120)
        self.live_label = QtWidgets.QLabel("Live Field Preview (capturing…)"); self.live_label.setVisible(False)
        self.live_table = QtWidgets.QTableWidget(); self.live_table.setVisible(False); self.live_table.setSortingEnabled(False)
        log_stack = QtWidgets.QVBoxLayout(); log_stack.setContentsMargins(0,0,0,0)
        log_stack.addWidget(self.log); log_stack.addWidget(self.live_label); log_stack.addWidget(self.live_table)
        log_wrap = QtWidgets.QWidget(); log_wrap.setLayout(log_stack)

        self.table = QtWidgets.QTableWidget()
        self.table.setSortingEnabled(False); self.table.setAlternatingRowColors(True); self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader(); hh.setStretchLastSection(True); hh.setSectionResizeMode(QHeaderView.Interactive)

        split = QtWidgets.QSplitter(QtCore.Qt.Vertical); split.addWidget(log_wrap); split.addWidget(self.table); split.setSizes([220, 600]); split.setHandleWidth(6)
        hmain = QtWidgets.QHBoxLayout(); hmain.setContentsMargins(0,0,0,0)
        hmain.addWidget(self.rail); hmain.addWidget(split, 1); v.addLayout(hmain)

        sb = QtWidgets.QStatusBar(); sb.setStyleSheet("QStatusBar{background:#fff;border-top:1px solid #e7e7ea;}"); self.setStatusBar(sb)
        self.status = QtWidgets.QLabel("Total Items: 0"); self.progress = QtWidgets.QProgressBar(); self.progress.setFixedWidth(180); self.progress.setVisible(False); self.progress.setTextVisible(False); self.progress.setMaximumHeight(12)
        sb.addPermanentWidget(self.status); sb.addPermanentWidget(self.progress)

        self.thread: ScraperThread = None
        self.scraped_data = []
        self.container_selector = ""
        self.card_tag = ""
        self.card_class = ""
        self.pagination_selector = ""
        self.product_card_selector = ""
        self.detail_selectors = []

        self.no_col_key = NO_COL_KEY
        self.preview_cols_keys = []
        self.preview_cols_titles = []
        self.deleted_keys = set()
        self.preview_row_count = 0
        self.table.setColumnCount(0); self.table.setRowCount(0)

        hh2 = self.table.horizontalHeader(); hh2.setContextMenuPolicy(QtCore.Qt.CustomContextMenu); hh2.customContextMenuRequested.connect(self._on_header_menu)

        self.apply_styles()
        self._set_enabled(start=True, stop=False, auto_detect=False, learn_pagination=False, learn_card=False, open_first=False, start_fields=False, done_fields=False, scrape=False, export=False)

    def apply_styles(self):
        BORDER = "#e7e7ea"
        self.setStyleSheet(f"""
        * {{
            font-family: "Segoe UI", "Noto Sans", Arial;
            font-size: 13px;
        }}
        QMainWindow {{ background: #ffffff; }}
        QLabel {{ color: #1a1f36; }}
        QLineEdit {{
            background: #ffffff;
            border: 1px solid {BORDER};
            border-radius: 6px;
            padding: 6px 8px;
        }}
        QPlainTextEdit {{
            background: #ffffff;
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 6px;
        }}
        QTableView {{
            background: #ffffff;
            border: 1px solid {BORDER};
            border-radius: 8px;
            gridline-color: #eef2f7;
            selection-background-color: #ffe58a;
            selection-color: #0d1b2a;
            alternate-background-color: #fafbfe;
        }}
        QHeaderView::section {{
            background: #f7f7f9;
            color: #1a1f36;
            border: none;
            border-right: 1px solid #e3e8ef;
            padding: 8px;
            font-weight: 600;
        }}
        QTableWidget::item {{ padding: 6px; }}
        QProgressBar {{
            background: #e9edf3;
            border: none;
            border-radius: 6px;
            height: 10px;
            text-align: center;
            color: #1a1f36;
        }}
        QProgressBar::chunk {{ background-color: #F2C01D; border-radius: 6px; }}
        """)

    def _set_enabled(self, **kwargs):
        actmap = {
            "start": self.act_start,
            "stop": self.act_stop,
            "auto_detect": self.act_detect,
            "learn_pagination": self.act_pagi,
            "learn_card": self.act_card,
            "open_first": self.act_open,
            "start_fields": self.act_capture,
            "done_fields": self.act_done,
            "scrape": self.act_scrape,
            "export": self.act_export,
        }
        for key, val in kwargs.items():
            if key in actmap: actmap[key].setEnabled(bool(val))

    def start(self):
        url = self.url_input.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "Missing URL", "Please enter a category/listing URL.")
            return
        self.log.clear(); self.status.setText("Total Items: 0")
        self.table.setRowCount(0); self.table.setColumnCount(0)
        self.live_table.setRowCount(0); self.live_table.setColumnCount(0)
        self.live_label.setVisible(False); self.live_table.setVisible(False)
        self.progress.setVisible(False); self.scraped_data = []

        self.container_selector = self.card_tag = self.card_class = self.pagination_selector = ""
        self.product_card_selector = ""; self.detail_selectors = []

        self.preview_cols_keys = []; self.preview_cols_titles = []; self.deleted_keys.clear(); self.preview_row_count = 0
        self._ensure_no_column_present(); self._rebuild_table_from_data()

        self.thread = ScraperThread(url, self.max_pages.value(), max_preview_cards=20)
        self.thread.log.connect(self.log.appendPlainText)
        self.thread.browser_ready.connect(self.on_browser_ready)
        self.thread.detect_ready.connect(self.on_detect_ready)
        self.thread.pagination_ready.connect(self.on_pagination_ready)
        self.thread.product_card_ready.connect(self.on_product_card_ready)
        self.thread.product_opened.connect(self.on_product_opened)
        self.thread.detail_capture_started.connect(self.on_detail_capture_started)
        self.thread.detail_capture_progress.connect(self.on_capture_progress)
        self.thread.detail_fields_ready.connect(self.on_detail_fields_ready)
        self.thread.preview_ready.connect(self.show_preview)
        self.thread.scrape_finished.connect(self.on_scrape_finished)

        self.thread.start()

        self._set_enabled(start=False, stop=True,
                          auto_detect=False, learn_pagination=False, learn_card=False,
                          open_first=False, start_fields=False, done_fields=False,
                          scrape=False, export=False)
        self.rail.setCurrentRow(0)

    def stop(self):
        if self.thread:
            self.thread.stop(); self.thread.quit(); self.thread.wait(1000); self.thread = None
        self._set_enabled(start=True, stop=False,
                          auto_detect=False, learn_pagination=False, learn_card=False,
                          open_first=False, start_fields=False, done_fields=False,
                          scrape=False, export=bool(self.scraped_data))
        self.status.setText("Stopped."); self.progress.setVisible(False)
        self.live_label.setVisible(False); self.live_table.setVisible(False)

    def on_browser_ready(self):
        self._set_enabled(start=False, stop=True, auto_detect=True, learn_pagination=False,
                          learn_card=False, open_first=False, start_fields=False, done_fields=False,
                          scrape=False, export=False)
        self.rail.setCurrentRow(1)

    def on_detect_ready(self, preview, container_sel, card_tag, card_class):
        self.container_selector = container_sel; self.card_tag = card_tag; self.card_class = card_class
        self.show_preview(preview, 1)
        self.progress.setVisible(False)
        self._set_enabled(start=False, stop=True, auto_detect=True, learn_pagination=True,
                          learn_card=False, open_first=False, start_fields=False, done_fields=False,
                          scrape=False, export=bool(preview))
        self.rail.setCurrentRow(2)
        QtWidgets.QMessageBox.information(self, "Next step",
            "Auto-detect complete.\n\nClick **Learn Pagination**, then in the browser click the real Next / Load More button.")

    def on_pagination_ready(self, selector):
        self.pagination_selector = selector
        self._set_enabled(start=False, stop=True, auto_detect=True, learn_pagination=True,
                          learn_card=True, open_first=False, start_fields=False, done_fields=False,
                          scrape=False, export=bool(self.scraped_data))
        self.rail.setCurrentRow(3)
        QtWidgets.QMessageBox.information(self, "Next step",
            "Pagination learned.\n\nClick **Learn Product Card**, then click one product card in the browser (or its link/button).")

    def on_product_card_ready(self, selector):
        self.product_card_selector = selector
        self._set_enabled(start=False, stop=True, auto_detect=True, learn_pagination=True,
                          learn_card=True, open_first=True, start_fields=False, done_fields=False,
                          scrape=False, export=bool(self.scraped_data))
        self.rail.setCurrentRow(4)
        QtWidgets.QMessageBox.information(self, "Open a Product",
            "Product opener learned.\n\nClick **Open First Product** to open a product page, then click **Start Field Capture**.")

    def on_product_opened(self, ok: bool):
        if ok:
            self._set_enabled(start=False, stop=True, auto_detect=True, learn_pagination=True,
                              learn_card=True, open_first=True, start_fields=True, done_fields=False,
                              scrape=False, export=bool(self.scraped_data))
            self.rail.setCurrentRow(5)

    def on_detail_capture_started(self):
        self.log.appendPlainText("Capture mode ON.")
        self.live_label.setVisible(True); self.live_table.setVisible(True)
        self.live_table.setRowCount(0); self.live_table.setColumnCount(0)
        self._set_enabled(done_fields=True)

    def on_capture_progress(self, fields, sample_values: dict):
        names = [f.get("name") or "Field" for f in (fields or [])]
        self.live_table.setColumnCount(len(names)); self.live_table.setHorizontalHeaderLabels(names)
        self.live_table.setRowCount(1 if names else 0)
        for c, name in enumerate(names):
            val = str(sample_values.get(name, "")); self.live_table.setItem(0, c, QtWidgets.QTableWidgetItem(val))
        self.live_table.resizeColumnsToContents()

    def on_detail_fields_ready(self, fields):
        self.detail_selectors = list(fields or [])
        self.live_label.setVisible(False); self.live_table.setVisible(False)
        if self.detail_selectors:
            self._set_enabled(start=False, stop=True, auto_detect=True, learn_pagination=True,
                              learn_card=True, open_first=True, start_fields=True, done_fields=True,
                              scrape=True, export=bool(self.scraped_data))
            QtWidgets.QMessageBox.information(self, "Fields captured",
                f"Captured {len(self.detail_selectors)} fields.\n\nClick **Scrape** to extract all pages.")
        else:
            QtWidgets.QMessageBox.warning(self, "No fields", "No detail fields were captured. You can try again.")

    def on_scrape_finished(self, all_rows):
        self.scraped_data = list(all_rows or [])
        self._set_enabled(start=False, stop=True, auto_detect=True, learn_pagination=True,
                          learn_card=True, open_first=True, start_fields=True, done_fields=True,
                          scrape=True, export=bool(self.scraped_data))
        self.rail.setCurrentRow(6)

    # ---------- header ctx menu ----------
    def _on_header_menu(self, pos: QtCore.QPoint):
        hh = self.table.horizontalHeader()
        col = hh.logicalIndexAt(pos)
        if col < 0: return
        key = self.preview_cols_keys[col] if col < len(self.preview_cols_keys) else ""

        menu = QtWidgets.QMenu(self)
        actRename = menu.addAction("Rename…"); actDelete = menu.addAction("Delete Column")
        menu.addSeparator()
        actRestore = menu.addAction("Restore All Columns"); actFit = menu.addAction("Fit Columns")

        if key == self.no_col_key or col == 0:
            actRename.setEnabled(False); actDelete.setEnabled(False)

        chosen = menu.exec_(hh.mapToGlobal(pos))
        if chosen == actRename: self._on_header_rename(col)
        elif chosen == actDelete: self._delete_column(col)
        elif chosen == actRestore: self._restore_all_columns()
        elif chosen == actFit: self._autosize_columns()

    def _on_header_rename(self, col_index: int):
        if col_index == 0 or self.preview_cols_keys[col_index] == self.no_col_key: return
        current = self.preview_cols_titles[col_index]
        new, ok = QtWidgets.QInputDialog.getText(self, "Rename column", "Header:", text=current)
        if ok and new.strip():
            self.preview_cols_titles[col_index] = new.strip()
            self.table.setHorizontalHeaderLabels(self.preview_cols_titles)

    def _delete_column(self, col_index: int):
        if col_index == 0 or self.preview_cols_keys[col_index] == self.no_col_key: return
        key = self.preview_cols_keys[col_index]; self.deleted_keys.add(key)
        del self.preview_cols_keys[col_index]; del self.preview_cols_titles[col_index]
        self.table.removeColumn(col_index); self._autosize_columns()

    def _restore_all_columns(self):
        self.deleted_keys.clear()
        keys = sorted({k for row in self.scraped_data for k in row.keys()})
        self.preview_cols_keys = [self.no_col_key] + keys
        self.preview_cols_titles = ["No."] + keys
        self._rebuild_table_from_data(); self._autosize_columns()

    def _autosize_columns(self):
        self.table.resizeColumnsToContents()
        try: self.table.setColumnWidth(0, 64)
        except Exception: pass

    def _ensure_no_column_present(self):
        if not self.preview_cols_keys:
            self.preview_cols_keys = [NO_COL_KEY]; self.preview_cols_titles = ["No."]
            self.table.setColumnCount(1); self.table.setHorizontalHeaderLabels(self.preview_cols_titles); return
        if NO_COL_KEY not in self.preview_cols_keys:
            self.preview_cols_keys.insert(0, NO_COL_KEY); self.preview_cols_titles.insert(0, "No.")
        else:
            idx = self.preview_cols_keys.index(NO_COL_KEY)
            if idx != 0:
                self.preview_cols_keys.pop(idx); self.preview_cols_titles.pop(idx)
                self.preview_cols_keys.insert(0, NO_COL_KEY); self.preview_cols_titles.insert(0, "No.")

    def _merge_columns(self, rows):
        self._ensure_no_column_present()
        col_set, added = set(self.preview_cols_keys), False
        for r in rows:
            for k in r.keys():
                if k in self.deleted_keys: continue
                if k not in col_set:
                    self.preview_cols_keys.append(k); self.preview_cols_titles.append(k)
                    col_set.add(k); added = True
        if added:
            self.table.setColumnCount(len(self.preview_cols_keys))
            self.table.setHorizontalHeaderLabels(self.preview_cols_titles)

    def _rebuild_table_from_data(self):
        self._ensure_no_column_present()
        self.table.setUpdatesEnabled(False); self.table.clear()
        self.table.setColumnCount(len(self.preview_cols_keys)); self.table.setHorizontalHeaderLabels(self.preview_cols_titles)
        self.table.setRowCount(len(self.scraped_data))
        for r, row in enumerate(self.scraped_data):
            for c, key in enumerate(self.preview_cols_keys):
                val = str(r+1) if key == NO_COL_KEY else str(row.get(key, ""))
                it = QtWidgets.QTableWidgetItem(val); it.setToolTip(val); self.table.setItem(r, c, it)
        self.preview_row_count = len(self.scraped_data)
        self.table.setUpdatesEnabled(True)
        try: self.table.setColumnWidth(0, 64)
        except Exception: pass

    # ---------- FIXED preview writer with guaranteed back-fill ----------
    def show_preview(self, data, page_num):
        self.scraped_data = list(data or [])
        if page_num and page_num > 0:
            self.progress.setMaximum(max(self.progress.maximum(), page_num)); self.progress.setValue(page_num)
            self.status.setText(f"Total Items: {len(self.scraped_data)} (Page {page_num})")
        elif page_num == -1:
            self.status.setText(f"Total Items: {len(self.scraped_data)}"); self.progress.setVisible(False)
        else:
            self.status.setText(f"Total Items: {len(self.scraped_data)}")

        if not self.scraped_data:
            self.table.setRowCount(0); self.table.setColumnCount(0); self.preview_row_count = 0; return

        # Add any new columns discovered (Field 1/2/… etc.)
        self._merge_columns(self.scraped_data)

        self.table.setUpdatesEnabled(False)

        total_rows = len(self.scraped_data)
        if total_rows > self.table.rowCount():
            self.table.setRowCount(total_rows)

        # Append newly arrived rows since last call
        start_r = self.preview_row_count
        for r in range(start_r, total_rows):
            row_dict = self.scraped_data[r]
            for c, key in enumerate(self.preview_cols_keys):
                sval = str(r+1) if key == NO_COL_KEY else str(row_dict.get(key, ""))
                it = QtWidgets.QTableWidgetItem(sval); it.setToolTip(sval); self.table.setItem(r, c, it)

        # >>> KEY FIX: Back-fill ALL earlier rows for any columns that were added later
        # (don’t rely on column-count conditions; just fill any missing cells)
        for r in range(0, total_rows):
            row_dict = self.scraped_data[r]
            for c, key in enumerate(self.preview_cols_keys):
                if self.table.item(r, c) is None:
                    sval = str(r+1) if key == NO_COL_KEY else str(row_dict.get(key, ""))
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem(sval))

        self.preview_row_count = total_rows
        self.table.setHorizontalHeaderLabels(self.preview_cols_titles)
        self.table.setUpdatesEnabled(True)
        try: self.table.setColumnWidth(0, 64)
        except Exception: pass
        QtWidgets.QApplication.processEvents()

    # ---------- actions ----------
    def on_auto_detect(self):
        if not self.thread:
            self.log.appendPlainText("Please click Start first."); return
        self.progress.setVisible(True); self.progress.setMaximum(0); self.progress.setValue(0)
        self.thread.do_auto_detect.emit()

    def on_learn_pagination(self):
        if not self.thread: return
        QtWidgets.QMessageBox.information(self, "Learn Pagination",
            "In the browser, click the real **Next** / **Load More** button.\n\nI’ll record the selector from your click.")
        self.thread.do_learn_pagination.emit()

    def on_learn_product_card(self):
        if not self.thread: return
        QtWidgets.QMessageBox.information(self, "Learn Product Card",
            "In the browser, click a **product card or its link/button** to tell me how to open details.\n\nI’ll use the same generic selector inside every card.")
        self.thread.do_learn_product_card.emit()

    def on_open_first_product(self):
        if not self.thread: return
        self.thread.do_open_first_product.emit()

    def on_start_field_capture(self):
        if not self.thread: return
        QtWidgets.QMessageBox.information(self, "Start Field Capture",
            "On the product detail page: click the fields you want (Title, Price, SKU, etc.).\nEach clicked element will highlight in green.\n\nWhen finished, click **Done Fields**.")
        self.thread.do_start_field_capture.emit()

    def on_done_fields(self):
        if not self.thread: return
        self.thread.do_finish_field_capture.emit()

    def on_scrape(self):
        if not self.thread: return
        self.progress.setVisible(True); self.progress.setMaximum(self.max_pages.value()); self.progress.setValue(0)
        self.thread.do_scrape.emit()

    def closeEvent(self, event: QtGui.QCloseEvent):
        try: self.stop()
        except Exception: pass
        event.accept()

    def export_data(self):
        if self.table.rowCount() == 0 or self.table.columnCount() == 0:
            QtWidgets.QMessageBox.warning(self, "No data", "Nothing to export yet!"); return
        if not os.path.exists(EXPORT_DIR): os.makedirs(EXPORT_DIR)
        base = "autoscraper"
        try: base = self.url_input.text().split("/")[2].replace(".", "_")
        except Exception: pass
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(EXPORT_DIR, f"{base}_{ts}.xlsx")
        try:
            import pandas as pd
            headers = self.preview_cols_titles[:]; rows = []
            for r in range(self.table.rowCount()):
                row_vals = {}
                for c, head in enumerate(headers):
                    item = self.table.item(r, c); row_vals[head] = item.text() if item else ""
                rows.append(row_vals)
            pd.DataFrame(rows, columns=headers).to_excel(filename, index=False)

            msg = QtWidgets.QMessageBox(self); msg.setIcon(QtWidgets.QMessageBox.Information)
            msg.setWindowTitle("Exported"); msg.setText(f"Exported data to:\n{filename}\n\nOpen this file now?")
            open_btn = msg.addButton("Open", QtWidgets.QMessageBox.AcceptRole); msg.addButton("Close", QtWidgets.QMessageBox.RejectRole)
            msg.exec_()
            if msg.clickedButton() == open_btn:
                try: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(filename))
                except Exception:
                    try: os.startfile(filename)
                    except Exception: pass
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Failed", f"Could not export data:\n{e}")


def main():
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.fonts.debug=false"
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(resource_path("assets/icon.ico")))
    win = MainWindow(); win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
