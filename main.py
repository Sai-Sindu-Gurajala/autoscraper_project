import sys
import os
import json
import datetime
import pyperclip
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import QThread, pyqtSignal
from autoscraper_core import core, utils
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait

EXPORT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Autoscraper")

class ScraperThread(QThread):
    log = pyqtSignal(str)
    finished = pyqtSignal()
    data_preview = pyqtSignal(list)
    step_update = pyqtSignal(str, int, int)  # msg, step_num, total_steps
    progress = pyqtSignal(int, int)  # current, total

    def __init__(self, url, mode="manual", max_pages=None, workflow=None):
        super().__init__()
        self.url = url
        self.mode = mode.lower().strip()
        self._stop_requested = False
        import threading
        self._product_selected_event = threading.Event()
        self._next_selected_event = threading.Event()
        self._fields_done_event = threading.Event()
        self.nested_selectors = workflow.get("fields", {}) if workflow else {}
        self.driver = None
        self.max_pages = max_pages
        self.workflow = workflow

    def request_stop(self):
        self._stop_requested = True
        self._product_selected_event.set()
        self._next_selected_event.set()
        self._fields_done_event.set()

    def product_selected(self):
        self._product_selected_event.set()

    def next_selected(self):
        self._next_selected_event.set()

    def fields_selection_done(self, nested_selectors):
        self.nested_selectors = nested_selectors or {}
        self._fields_done_event.set()

    def run(self):
        data = []
        try:
            self.driver = core.launch_browser(self.url)
        except Exception as e:
            self.log.emit(f"Error launching browser: {e}")
            self.finished.emit()
            return

        self.step_update.emit("Select a product card/item in Chrome.", 1, 4)
        self.log.emit("STEP 1: Click on a product card/item in the browser, then click 'Continue' in the GUI.")
        core.inject_highlight_script(self.driver)
        self._product_selected_event.wait()
        if self._stop_requested:
            self.driver.quit()
            self.finished.emit()
            return
        elem_info = core.get_selected_element_info(self.driver)
        self.log.emit(f"Selected product element: {elem_info}")

        self.step_update.emit("Select the 'Next page' button in Chrome.", 2, 4)
        core.inject_highlight_script(self.driver)
        self._next_selected_event.wait()
        if self._stop_requested:
            self.driver.quit()
            self.finished.emit()
            return
        next_selector = core.get_selected_element_selector(self.driver)
        core.remove_highlight_script(self.driver)
        if next_selector:
            if "rel" not in next_selector:
                try:
                    if self.driver.find_elements(By.CSS_SELECTOR, "a[rel='next']"):
                        next_selector = "a[rel='next']"
                except Exception:
                    pass
        self.log.emit(f"Next button selector: {next_selector}")

        first_product_url = None
        try:
            if elem_info and elem_info.get('class'):
                elements = self.driver.find_elements(By.CLASS_NAME, elem_info['class'].split()[0])
                if elements:
                    first_product_url = elements[0].get_attribute('href')
            if first_product_url:
                self.log.emit("Opening first product detail page for field selection...")
                self.driver.get(first_product_url)
            else:
                self.log.emit("Could not determine a product detail URL automatically.")
        except Exception as e:
            self.log.emit(f"Error opening detail page: {e}")

        self.step_update.emit("Add fields on detail page, or finish.", 3, 4)
        self.log.emit("If you want to extract additional fields from the detail page, click 'Add Field' for each field and 'Done Fields' when finished.")
        self._fields_done_event.wait()
        if self._stop_requested:
            self.driver.quit()
            self.finished.emit()
            return
        nested_selectors = self.nested_selectors

        try:
            self.driver.get(self.url)
        except Exception as e:
            self.log.emit(f"Warning: could not return to listing page: {e}")

        page = 1
        item_count = 0
        self.step_update.emit("Scraping and previewing data...", 4, 4)
        try:
            while self.max_pages is None or page <= self.max_pages:
                if self._stop_requested:
                    break
                self.log.emit(f"Scraping page {page}...")
                items = core.extract_current_page_items(self.driver, elem_info)
                if not items:
                    self.log.emit("No items found on this page. Stopping.")
                    break

                current_page_url = self.driver.current_url

                for product in items:
                    if self._stop_requested:
                        break
                    product["Product Link"] = product.get("href") or ""
                    if nested_selectors and product.get('href'):
                        try:
                            detail_data = core.extract_nested_fields_manual(self.driver, product['href'], nested_selectors)
                        except Exception as err:
                            self.log.emit(f"Error extracting details for {product.get('href')}: {err}")
                            detail_data = {}
                        for field, value in detail_data.items():
                            product[field] = value
                        try:
                            self.driver.get(current_page_url)
                        except Exception:
                            pass
                    data.append(product)
                    item_count += 1
                    self.progress.emit(item_count, 0)
                    self.data_preview.emit(data.copy())
                if self._stop_requested:
                    break

                try:
                    next_button = self.driver.find_element(By.CSS_SELECTOR, next_selector)
                except NoSuchElementException:
                    self.log.emit("Next page button not found. Ending pagination.")
                    break
                aria_disabled = next_button.get_attribute("aria-disabled")
                btn_class = (next_button.get_attribute("class") or "").lower()
                if aria_disabled == "true" or "disabled" in btn_class:
                    self.log.emit("Next button is disabled. Reached last page.")
                    break

                first_href = None
                if elem_info and elem_info.get('tag', '').lower() == 'a' and elem_info.get('class'):
                    try:
                        first_elem = self.driver.find_elements(By.CLASS_NAME, elem_info['class'].split()[0])[0]
                        first_href = first_elem.get_attribute("href")
                    except Exception:
                        first_href = None

                self.log.emit("Navigating to the next page...")
                next_page_url = next_button.get_attribute("href")
                try:
                    next_button.click()
                    if first_href:
                        WebDriverWait(self.driver, 10).until(
                            lambda d: d.find_elements(By.CLASS_NAME, elem_info['class'].split()[0])[0].get_attribute("href") != first_href
                        )
                except Exception:
                    if next_page_url:
                        try:
                            self.driver.get(next_page_url)
                        except Exception as nav_err:
                            self.log.emit(f"Failed to navigate to next page: {nav_err}")
                            break
                    else:
                        self.log.emit("No next page link available. Stopping.")
                        break

                page += 1

            if self._stop_requested:
                self.log.emit("Scraping stopped by user.")
            else:
                if data:
                    self.log.emit(f"Extracted {len(data)} items across {page-1} pages. Saving results...")
                    try:
                        utils.export_data(data)
                    except Exception as e:
                        self.log.emit(f"Error exporting data: {e}")
                    else:
                        self.log.emit("Data export completed. (Check the output/ folder for the file.)")
                else:
                    self.log.emit("No data found to export.")
        finally:
            self.driver.quit()
        self.finished.emit()

# --- MainWindow and all features ---

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Autoscraper")
        self.resize(1000, 750)
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        vbox = QtWidgets.QVBoxLayout(central_widget)

        # --- Step Banner + Progress ---
        self.step_banner = QtWidgets.QLabel("Welcome! Enter URL and Click Start to begin.")
        self.step_banner.setAlignment(QtCore.Qt.AlignCenter)
        self.step_banner.setStyleSheet("background:#edf3ff;font-size:16pt;padding:8px;border-radius:9px;margin:4px;")
        vbox.addWidget(self.step_banner)
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        vbox.addWidget(self.progress_bar)

        # --- URL/Mode/Page controls, "card" style box ---
        card = QtWidgets.QGroupBox("Scraping Setup")
        card.setStyleSheet("QGroupBox { font-weight: bold; border:2px solid #357ded; border-radius:10px; margin-top:20px; padding:8px;}")
        form = QtWidgets.QHBoxLayout(card)
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText("Enter the product/list page URL...")
        self.mode_select = QtWidgets.QComboBox()
        self.mode_select.addItems(["manual", "auto"])
        self.mode_select.setCurrentText("manual")
        self.page_count_spin = QtWidgets.QSpinBox()
        self.page_count_spin.setMinimum(1)
        self.page_count_spin.setMaximum(999)
        self.page_count_spin.setValue(3)
        self.all_pages_checkbox = QtWidgets.QCheckBox("All pages")
        self.all_pages_checkbox.stateChanged.connect(self.toggle_page_count_spin)
        form.addWidget(QtWidgets.QLabel("URL:"))
        form.addWidget(self.url_input)
        form.addWidget(QtWidgets.QLabel("Mode:"))
        form.addWidget(self.mode_select)
        form.addWidget(QtWidgets.QLabel("Pages:"))
        form.addWidget(self.page_count_spin)
        form.addWidget(self.all_pages_checkbox)
        vbox.addWidget(card)

        # --- Buttons: Start/Stop/Continue ---
        btns = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.continue_btn = QtWidgets.QPushButton("Continue")
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.continue_btn)
        vbox.addLayout(btns)
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)

        # --- Nested field controls + field list ---
        field_box = QtWidgets.QGroupBox("Captured Fields (Detail Page)")
        field_box.setStyleSheet("QGroupBox { border:1px solid #777; border-radius:8px; margin-top:19px; }")
        field_layout = QtWidgets.QVBoxLayout(field_box)
        self.field_list = QtWidgets.QTableWidget(0, 2)
        self.field_list.setHorizontalHeaderLabels(["Field Name", "Selector"])
        self.field_list.horizontalHeader().setStretchLastSection(True)
        self.field_list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.field_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.field_list.setFixedHeight(120)
        self.add_field_btn = QtWidgets.QPushButton("Add Field")
        self.capture_field_btn = QtWidgets.QPushButton("Capture Field")
        self.done_fields_btn = QtWidgets.QPushButton("Done Fields")
        field_btns = QtWidgets.QHBoxLayout()
        field_btns.addWidget(self.add_field_btn)
        field_btns.addWidget(self.capture_field_btn)
        field_btns.addWidget(self.done_fields_btn)
        self.add_field_btn.setVisible(False)
        self.capture_field_btn.setVisible(False)
        self.done_fields_btn.setVisible(False)
        field_layout.addWidget(self.field_list)
        field_layout.addLayout(field_btns)
        vbox.addWidget(field_box)

        # --- Log output area ---
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        vbox.addWidget(self.log_text)

        # --- Data preview table ---
        self.data_table = QtWidgets.QTableWidget()
        self.data_table.setColumnCount(0)
        self.data_table.setRowCount(0)
        self.data_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.data_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.data_table.setSortingEnabled(True)
        self.data_table.verticalHeader().hide()
        vbox.addWidget(self.data_table)

        # --- Export button, format dropdown, open folder ---
        export_box = QtWidgets.QHBoxLayout()
        self.export_btn = QtWidgets.QPushButton("Export")
        self.export_btn.setEnabled(False)
        self.export_format = QtWidgets.QComboBox()
        self.export_format.addItems(["Excel (.xlsx)", "CSV (.csv)", "JSON (.json)"])
        self.open_folder_btn = QtWidgets.QPushButton("Open Export Folder")
        export_box.addWidget(self.export_btn)
        export_box.addWidget(self.export_format)
        export_box.addWidget(self.open_folder_btn)
        vbox.addLayout(export_box)
        self.export_btn.clicked.connect(self.export_data)
        self.open_folder_btn.clicked.connect(self.open_export_folder)

        # --- Data inspector on row double click ---
        self.data_table.cellDoubleClicked.connect(self.show_data_inspector)

        # --- Right click: copy row/cell/column in table ---
        self.data_table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.data_table.customContextMenuRequested.connect(self.show_data_context_menu)

        # --- Connect all logic buttons ---
        self.start_btn.clicked.connect(self.start_scraping)
        self.stop_btn.clicked.connect(self.stop_scraping)
        self.continue_btn.clicked.connect(self.continue_scraping)
        self.add_field_btn.clicked.connect(self.add_field)
        self.capture_field_btn.clicked.connect(self.capture_field)
        self.done_fields_btn.clicked.connect(self.done_fields)
        self.field_list.cellDoubleClicked.connect(self.rename_field)
        self.field_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.field_list.customContextMenuRequested.connect(self.show_field_context_menu)

        # --- Data state ---
        self.scraped_data = []
        self.field_order = []
        self._nested_selectors = {}
        self.workflow_loaded = None
        self.thread = None
        self._continue_stage = 0

        # --- UI Polish ---
        self.data_table.setStyleSheet("QTableWidget {background:#fff;font-size:11pt;}")
        self.field_list.setStyleSheet("QTableWidget {background:#f7f9fc;}")

    def show_field_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        rm = menu.addAction("Remove Field")
        idx = self.field_list.indexAt(pos)
        if idx.isValid():
            action = menu.exec_(self.field_list.mapToGlobal(pos))
            if action == rm:
                row = idx.row()
                fname = self.field_list.item(row, 0).text()
                self.field_order = [f for f in self.field_order if f != fname]
                self._nested_selectors.pop(fname, None)
                self.update_field_list()

    def rename_field(self, row, col):
        fname = self.field_list.item(row, 0).text()
        selector = self.field_list.item(row, 1).text()
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Rename Field", "Enter new name:", text=fname)
        if ok and new_name and new_name != fname:
            self._nested_selectors[new_name] = self._nested_selectors.pop(fname)
            self.field_order[row] = new_name
            self.update_field_list()

    def update_field_list(self):
        self.field_list.setRowCount(len(self.field_order))
        for i, fname in enumerate(self.field_order):
            self.field_list.setItem(i, 0, QtWidgets.QTableWidgetItem(fname))
            self.field_list.setItem(i, 1, QtWidgets.QTableWidgetItem(self._nested_selectors.get(fname, "")))

    def toggle_page_count_spin(self):
        self.page_count_spin.setEnabled(not self.all_pages_checkbox.isChecked())

    def start_scraping(self):
        url = self.url_input.text().strip()
        if not url:
            self.set_status("Please enter a URL.", "error")
            return
        mode = self.mode_select.currentText().lower().strip()
        if mode != "manual":
            QtWidgets.QMessageBox.information(self, "Note", "Auto mode is not fully supported for pagination; defaulting to manual mode.")

        if self.all_pages_checkbox.isChecked():
            max_pages = None
            self.set_status("Will scrape all pages.", "info")
        else:
            max_pages = self.page_count_spin.value()
            self.set_status(f"Will scrape {max_pages} pages.", "info")

        self.url_input.setEnabled(False)
        self.mode_select.setEnabled(False)
        self.page_count_spin.setEnabled(False)
        self.all_pages_checkbox.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.continue_btn.setEnabled(True)
        self.add_field_btn.setVisible(False)
        self.capture_field_btn.setVisible(False)
        self.done_fields_btn.setVisible(False)
        self._nested_selectors = {}
        self.field_order = []
        self.update_field_list()

        self.scraped_data = []
        self.update_data_preview([])

        self.thread = ScraperThread(url, mode, max_pages)
        self.thread.log.connect(self.append_log)
        self.thread.finished.connect(self.scrape_finished)
        self.thread.data_preview.connect(self.update_data_preview, QtCore.Qt.QueuedConnection)
        self.thread.step_update.connect(self.set_step)
        self.thread.progress.connect(self.set_progress)
        self.thread.start()

        self._continue_stage = 1
        self.log_text.clear()
        self.append_log("Starting scraping...")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

    def set_status(self, msg, style="info"):
        color = {"info":"#357ded", "ok":"#22bb55", "error":"#d22"}[style]
        self.step_banner.setStyleSheet(
            f"background:{color}10; color:{color}; font-size:15pt; padding:8px; border-radius:8px;")
        self.step_banner.setText(msg)

    def set_step(self, msg, step, total):
        self.set_status(f"Step {step}/{total}: {msg}", "info")

    def set_progress(self, val, total):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(val)
        else:
            self.progress_bar.setMaximum(0)  # indeterminate
            self.progress_bar.setValue(val)

    def append_log(self, message):
        self.log_text.appendPlainText(message)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def continue_scraping(self):
        if not self.thread:
            return
        if self._continue_stage == 1:
            self.thread.product_selected()
            self._continue_stage = 2
        elif self._continue_stage == 2:
            self.thread.next_selected()
            self.continue_btn.setEnabled(False)
            self.add_field_btn.setVisible(True)
            self.done_fields_btn.setVisible(True)
            self.add_field_btn.setEnabled(True)
            self.done_fields_btn.setEnabled(True)

    def add_field(self):
        if not self.thread or not self.thread.driver:
            return
        core.inject_highlight_script(self.thread.driver)
        self.set_status("Select a field on the detail page, then click 'Capture Field' or press C.", "info")
        self.capture_field_btn.setVisible(True)
        self.capture_field_btn.setEnabled(True)
        self.add_field_btn.setEnabled(False)

    def capture_field(self):
        if not self.thread or not self.thread.driver:
            return
        selector = core.get_selected_element_selector(self.thread.driver)
        core.remove_highlight_script(self.thread.driver)
        self.add_field_btn.setEnabled(True)
        self.capture_field_btn.setVisible(False)
        if not selector:
            self.set_status("No element selected, try again.", "error")
            return
        field_name, ok = QtWidgets.QInputDialog.getText(self, "Field Name", "Enter field name:")
        if not ok or not field_name.strip():
            self.set_status("Field name cannot be empty.", "error")
            return
        field_name = field_name.strip()
        self._nested_selectors[field_name] = selector
        if field_name not in self.field_order:
            self.field_order.append(field_name)
        self.update_field_list()
        self.set_status(f"Captured field '{field_name}'", "ok")

    def done_fields(self):
        if self.thread:
            self.thread.fields_selection_done(self._nested_selectors)
        self.add_field_btn.setEnabled(False)
        self.add_field_btn.setVisible(False)
        self.capture_field_btn.setVisible(False)
        self.done_fields_btn.setEnabled(False)
        self.done_fields_btn.setVisible(False)
        self.set_status("Proceeding with scraping pages...", "ok")

    def stop_scraping(self):
        if self.thread:
            self.thread.request_stop()
            self.set_status("Stop requested. Waiting...", "error")

    def scrape_finished(self):
        self.url_input.setEnabled(True)
        self.mode_select.setEnabled(True)
        self.page_count_spin.setEnabled(True)
        self.all_pages_checkbox.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.continue_btn.setEnabled(False)
        self.add_field_btn.setVisible(False)
        self.capture_field_btn.setVisible(False)
        self.done_fields_btn.setVisible(False)
        self.thread = None
        self.progress_bar.setVisible(False)
        self.set_status("Scraping finished.", "ok")

    def update_data_preview(self, data):
        self.scraped_data = data or []
        if not data:
            self.data_table.setColumnCount(0)
            self.data_table.setRowCount(0)
            self.export_btn.setEnabled(False)
            return
        all_cols = []
        seen = set()
        all_cols.append("Product Link")
        seen.add("Product Link")
        for k in self.field_order:
            if k and k != "Product Link" and k not in seen:
                all_cols.append(k)
                seen.add(k)
        for row in data:
            for k in row.keys():
                if k and k not in seen:
                    all_cols.append(k)
                    seen.add(k)
        self.data_table.setColumnCount(len(all_cols))
        self.data_table.setHorizontalHeaderLabels(all_cols)
        self.data_table.setRowCount(len(data))
        for row_idx, row_data in enumerate(data):
            for col_idx, col_name in enumerate(all_cols):
                val = str(row_data.get(col_name, ""))
                item = QtWidgets.QTableWidgetItem(val)
                if col_name == "Product Link" and val:
                    item.setForeground(QtGui.QColor("#357ded"))
                self.data_table.setItem(row_idx, col_idx, item)
        self.data_table.resizeColumnsToContents()
        self.export_btn.setEnabled(True)
        # Highlight last row for a moment
        if len(data) > 0:
            for col in range(self.data_table.columnCount()):
                self.data_table.item(len(data)-1, col).setBackground(QtGui.QColor("#e6f0ff"))
        QtCore.QTimer.singleShot(700, self.clear_highlight)

    def clear_highlight(self):
        for row in range(self.data_table.rowCount()):
            for col in range(self.data_table.columnCount()):
                self.data_table.item(row, col).setBackground(QtGui.QColor("white"))

    def show_data_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        cell_action = menu.addAction("Copy Cell")
        row_action = menu.addAction("Copy Row")
        col_action = menu.addAction("Copy Column")
        idx = self.data_table.indexAt(pos)
        if not idx.isValid():
            return
        action = menu.exec_(self.data_table.mapToGlobal(pos))
        row, col = idx.row(), idx.column()
        if action == cell_action:
            pyperclip.copy(self.data_table.item(row, col).text())
        elif action == row_action:
            vals = [self.data_table.item(row, c).text() for c in range(self.data_table.columnCount())]
            pyperclip.copy("\t".join(vals))
        elif action == col_action:
            vals = [self.data_table.item(r, col).text() for r in range(self.data_table.rowCount())]
            pyperclip.copy("\n".join(vals))

    def show_data_inspector(self, row, col):
        cols = [self.data_table.horizontalHeaderItem(c).text() for c in range(self.data_table.columnCount())]
        vals = [self.data_table.item(row, c).text() for c in range(self.data_table.columnCount())]
        msg = "\n".join(f"{c}: {v}" for c,v in zip(cols, vals))
        QtWidgets.QMessageBox.information(self, "Product Details", msg)

    def export_data(self):
        if not self.scraped_data:
            QtWidgets.QMessageBox.warning(self, "No data", "Nothing to export yet!")
            return
        fmt = self.export_format.currentText()
        ext = ".xlsx" if "Excel" in fmt else (".csv" if "CSV" in fmt else ".json")
        if not os.path.exists(EXPORT_DIR):
            os.makedirs(EXPORT_DIR)
        base = self.url_input.text().split("/")[2].replace(".", "_") if self.url_input.text() else "autoscraper"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_fn = f"{base}_{timestamp}{ext}"
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save As", os.path.join(EXPORT_DIR, default_fn),
            f"Excel (*.xlsx);;CSV (*.csv);;JSON (*.json);;All Files (*)"
        )
        if not filename:
            return
        try:
            if fmt.startswith("Excel"):
                utils.export_data(self.scraped_data, filename)
            elif fmt.startswith("CSV"):
                utils.export_data(self.scraped_data, filename, filetype="csv")
            elif fmt.startswith("JSON"):
                with open(filename, "w", encoding="utf8") as f:
                    json.dump(self.scraped_data, f, indent=2)
            QtWidgets.QMessageBox.information(self, "Exported", f"Exported data to:\n{filename}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Failed", f"Could not export data:\n{e}")

    def open_export_folder(self):
        if not os.path.exists(EXPORT_DIR):
            os.makedirs(EXPORT_DIR)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(EXPORT_DIR))

    def save_workflow(self):
        fname, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Workflow", os.path.join(EXPORT_DIR, "workflow.json"), "JSON (*.json)")
        if not fname:
            return
        state = {
            "url": self.url_input.text(),
            "fields": self._nested_selectors,
            "field_order": self.field_order
        }
        with open(fname, "w", encoding="utf8") as f:
            json.dump(state, f, indent=2)
        self.set_status(f"Workflow saved: {fname}", "ok")

    def load_workflow(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Workflow", EXPORT_DIR, "JSON (*.json)")
        if not fname:
            return
        with open(fname, "r", encoding="utf8") as f:
            state = json.load(f)
        self.url_input.setText(state.get("url", ""))
        self._nested_selectors = state.get("fields", {})
        self.field_order = state.get("field_order", list(self._nested_selectors.keys()))
        self.update_field_list()
        self.set_status(f"Workflow loaded: {fname}", "ok")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    try:
        import qtmodern.styles
        import qtmodern.windows
        qtmodern.styles.light(app)
    except Exception:
        pass
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
