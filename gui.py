import os
import sys
import subprocess
import shutil
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTextEdit,
                             QFileDialog, QGroupBox, QMessageBox, QTabWidget,
                             QSpinBox, QFormLayout, QListWidget, QAbstractItemView, QCheckBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from utils import get_7z_path, generate_transfer_code, load_config, save_config
from workers import ZipWorker, LiveUnzipWorker, CrocWorker, AutoSendWorker, AutoRecvWorker


class CrocApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Croc Transfer Ultimate + Live Sync")
        self.resize(900, 750)

        self.config = load_config()

        self._7z_path = get_7z_path()
        self.download_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "received")
        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

        self.croc_worker = None
        self.zip_worker = None
        self.live_unzip_worker = None
        self.auto_send_worker = None
        self.auto_recv_workers = []

        self.code_length = self.config.get("code_length", 6)
        self.current_state = "IDLE"
        self.staged_path_to_send = None
        self.staged_base_temp_dir = None

        self.init_ui()
        self.refresh_file_list()
        self.set_ui_state("IDLE")

        self.txt_code.setText(generate_transfer_code(self.code_length))

        if not self._7z_path:
            QMessageBox.critical(self, "Dependency Missing", "7-Zip is missing!")

    def init_ui(self):
        main_layout = QVBoxLayout()
        self.tabs = QTabWidget()

        self.tab_transfer = QWidget()
        self.tab_auto_recv = QWidget()
        self.tab_auto_send = QWidget()
        self.tab_downloads = QWidget()
        self.tab_settings = QWidget()

        self.tabs.addTab(self.tab_transfer, "📂 Manual Transfer")
        self.tabs.addTab(self.tab_auto_recv, "🖥️ Receiver (Server)")
        self.tabs.addTab(self.tab_auto_send, "📤 Sender (Watcher)")
        self.tabs.addTab(self.tab_downloads, "📥 Files")
        self.tabs.addTab(self.tab_settings, "⚙️ Settings")

        self.setup_transfer_tab()
        self.setup_auto_recv_tab()
        self.setup_auto_send_tab()
        self.setup_downloads_tab()
        self.setup_settings_tab()

        main_layout.addWidget(self.tabs)

        self.log_group = QGroupBox("📜 Activity Log")
        log_layout = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Consolas", 10))
        self.log_area.setStyleSheet("background-color: #1e1e1e; color: #4CAF50; border-radius: 5px;")
        log_layout.addWidget(self.log_area)
        self.log_group.setLayout(log_layout)

        main_layout.addWidget(self.log_group)
        self.setLayout(main_layout)

    # --- TAB 1: MANUAL (UNCHANGED) ---
    def setup_transfer_tab(self):
        layout = QVBoxLayout()
        code_group = QGroupBox("🔑 Transfer Code")
        code_layout = QHBoxLayout()
        self.txt_code = QLineEdit()
        self.txt_code.setFont(QFont("Arial", 14, QFont.Bold))
        self.txt_code.setAlignment(Qt.AlignCenter)
        self.txt_code.setStyleSheet("padding: 5px; background-color: #e3f2fd;")

        btn_regen = QPushButton("Regenerate 🔄")
        btn_regen.clicked.connect(lambda: self.txt_code.setText(generate_transfer_code(self.code_length)))
        btn_copy = QPushButton("Copy 📋")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.txt_code.text()))

        code_layout.addWidget(self.txt_code)
        code_layout.addWidget(btn_regen)
        code_layout.addWidget(btn_copy)
        code_group.setLayout(code_layout)

        send_group = QGroupBox("📤 Manual Sender")
        send_layout = QVBoxLayout()
        file_row = QHBoxLayout()
        self.file_path_input = QLineEdit()
        self.file_path_input.setPlaceholderText("Select a file or folder to send...")
        btn_browse_file = QPushButton("📄 File...")
        btn_browse_file.clicked.connect(lambda: self.browse_path(self.file_path_input, is_folder=False))
        btn_browse_folder = QPushButton("📁 Folder...")
        btn_browse_folder.clicked.connect(lambda: self.browse_path(self.file_path_input, is_folder=True))
        file_row.addWidget(self.file_path_input)
        file_row.addWidget(btn_browse_file)
        file_row.addWidget(btn_browse_folder)

        send_btn_row = QHBoxLayout()
        self.btn_send = QPushButton("🚀 Send")
        self.btn_send.clicked.connect(self.handle_send_click)
        self.btn_pause_send = QPushButton("⏸️ Pause")
        self.btn_pause_send.clicked.connect(self.handle_pause_send_click)
        send_btn_row.addWidget(self.btn_send)
        send_btn_row.addWidget(self.btn_pause_send)
        send_layout.addLayout(file_row)
        send_layout.addLayout(send_btn_row)
        send_group.setLayout(send_layout)

        recv_group = QGroupBox("📥 Manual Receiver")
        recv_layout = QVBoxLayout()
        code_layout = QHBoxLayout()
        self.recv_code_input = QLineEdit()
        self.recv_code_input.setPlaceholderText("Paste code here to receive...")
        self.btn_recv = QPushButton("⬇️ Download")
        self.btn_recv.clicked.connect(self.handle_recv_click)
        self.btn_pause_recv = QPushButton("⏸️ Pause")
        self.btn_pause_recv.clicked.connect(self.handle_pause_recv_click)
        code_layout.addWidget(self.recv_code_input)
        code_layout.addWidget(self.btn_recv)
        code_layout.addWidget(self.btn_pause_recv)
        recv_layout.addLayout(code_layout)
        recv_group.setLayout(recv_layout)

        layout.addWidget(code_group)
        layout.addWidget(send_group)
        layout.addWidget(recv_group)
        layout.addStretch()
        self.tab_transfer.setLayout(layout)

    # --- TAB: AUTO SENDER (WATCHER) ---
    def setup_auto_send_tab(self):
        layout = QVBoxLayout()
        info = QLabel(
            "<i><b>Watcher Mode:</b> Monitors folders. If a file is added/changed, it is sent to the Server.</i>")
        layout.addWidget(info)

        self.auto_send_list = QListWidget()
        self.auto_send_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Load persisted folders
        for f in self.config.get("sender_folders", []):
            self.auto_send_list.addItem(f)
        layout.addWidget(self.auto_send_list)

        btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ Add Folder to Watch")
        btn_add.clicked.connect(self.add_watch_folder)
        btn_remove = QPushButton("❌ Remove Selected")
        btn_remove.clicked.connect(self.remove_watch_folder)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_remove)
        layout.addLayout(btn_layout)

        code_group = QGroupBox("Server Connection")
        code_layout = QHBoxLayout()
        code_layout.addWidget(QLabel("Server Code:"))
        self.auto_send_code = QLineEdit()
        self.auto_send_code.setFont(QFont("Arial", 12, QFont.Bold))
        self.auto_send_code.setText(self.config.get("sender_code", ""))
        self.auto_send_code.textChanged.connect(self._save_state)

        btn_regen_send = QPushButton("Regenerate 🔄")
        btn_regen_send.clicked.connect(lambda: self.auto_send_code.setText(generate_transfer_code(self.code_length)))

        code_layout.addWidget(self.auto_send_code)
        code_layout.addWidget(btn_regen_send)
        code_group.setLayout(code_layout)
        layout.addWidget(code_group)

        self.btn_start_auto_send = QPushButton("🚀 Start Watching & Syncing")
        self.btn_start_auto_send.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 15px; font-weight:bold; font-size:14px;")
        self.btn_start_auto_send.clicked.connect(self.toggle_auto_send)
        layout.addWidget(self.btn_start_auto_send)
        layout.addStretch()
        self.tab_auto_send.setLayout(layout)

    # --- TAB: AUTO RECEIVER (SERVER) ---
    def setup_auto_recv_tab(self):
        layout = QVBoxLayout()
        info = QLabel(
            "<i><b>Server Mode:</b> Listen continuously. Downloads files inside the 'received' directory using your chosen Folder Name.</i>")
        layout.addWidget(info)

        self.auto_recv_list = QListWidget()
        self.auto_recv_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Load persisted listeners
        for l in self.config.get("receiver_listeners", []):
            self.auto_recv_list.addItem(l)
        layout.addWidget(self.auto_recv_list)

        input_group = QGroupBox("Add Server Listener")
        input_layout = QHBoxLayout()

        self.auto_recv_name_input = QLineEdit()
        self.auto_recv_name_input.setPlaceholderText("Folder Name (e.g. 'Photos')")
        self.auto_recv_name_input.setFixedWidth(200)

        self.auto_recv_code_input = QLineEdit()
        self.auto_recv_code_input.setPlaceholderText("Code to Listen On")

        btn_add = QPushButton("➕ Add")
        btn_add.clicked.connect(self.add_recv_listener)

        input_layout.addWidget(self.auto_recv_name_input)
        input_layout.addWidget(self.auto_recv_code_input)
        input_layout.addWidget(btn_add)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        btn_remove = QPushButton("❌ Remove Selected")
        btn_remove.clicked.connect(self.remove_recv_listener)
        layout.addWidget(btn_remove)

        self.btn_start_auto_recv = QPushButton("📡 Start Server Listeners")
        self.btn_start_auto_recv.setStyleSheet(
            "background-color: #2196F3; color: white; padding: 15px; font-weight:bold; font-size:14px;")
        self.btn_start_auto_recv.clicked.connect(self.toggle_auto_recv)
        layout.addWidget(self.btn_start_auto_recv)

        self.tab_auto_recv.setLayout(layout)

    # --- TAB: DOWNLOADS & SETTINGS ---
    def setup_downloads_tab(self):
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()
        self.lbl_dl_path = QLabel(f"Viewing: <b>{self.download_folder}</b>")
        btn_open = QPushButton("📂 Open Directory")
        btn_open.clicked.connect(
            lambda: os.startfile(self.download_folder) if sys.platform == "win32" else subprocess.Popen(
                ["open" if sys.platform == "darwin" else "xdg-open", self.download_folder]))
        btn_refresh = QPushButton("🔄 Refresh List")
        btn_refresh.clicked.connect(self.refresh_file_list)
        btn_change = QPushButton("⚙️ Change Dir...")
        btn_change.clicked.connect(self.change_download_dir)
        header_layout.addWidget(self.lbl_dl_path)
        header_layout.addStretch()
        header_layout.addWidget(btn_change)
        header_layout.addWidget(btn_refresh)
        header_layout.addWidget(btn_open)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setStyleSheet("font-size: 14px; padding: 5px;")
        self.file_list_widget.itemDoubleClicked.connect(self.open_specific_file)

        layout.addLayout(header_layout)
        layout.addWidget(self.file_list_widget)
        self.tab_downloads.setLayout(layout)

    def setup_settings_tab(self):
        layout = QFormLayout()

        # 1. Option to remove sent files
        self.chk_delete_sent = QCheckBox("Delete original files after successfully sending (Watcher Mode)")
        self.chk_delete_sent.setChecked(self.config.get("delete_after_send", True))
        self.chk_delete_sent.stateChanged.connect(self._save_state)
        layout.addRow("", self.chk_delete_sent)

        # 2. Option for time interval
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 3600)
        self.spin_interval.setValue(self.config.get("check_interval", 3))
        self.spin_interval.setSuffix(" seconds")
        self.spin_interval.valueChanged.connect(self._save_state)
        layout.addRow("Folder Check Interval:", self.spin_interval)

        # 3. Code length
        self.spin_length = QSpinBox()
        self.spin_length.setRange(4, 20)
        self.spin_length.setValue(self.config.get("code_length", 6))
        self.spin_length.valueChanged.connect(self.update_code_length)
        layout.addRow("Auto-Code Length:", self.spin_length)

        self.tab_settings.setLayout(layout)

    # ==========================
    # PERSISTENCE (Saving state)
    # ==========================
    def _save_state(self):
        """Extracts UI values and saves to config.json"""
        self.config["sender_code"] = self.auto_send_code.text().strip()
        self.config["sender_folders"] = [self.auto_send_list.item(i).text() for i in range(self.auto_send_list.count())]
        self.config["receiver_listeners"] = [self.auto_recv_list.item(i).text() for i in
                                             range(self.auto_recv_list.count())]
        self.config["delete_after_send"] = self.chk_delete_sent.isChecked()
        self.config["check_interval"] = self.spin_interval.value()
        self.config["code_length"] = self.spin_length.value()
        save_config(self.config)

    def update_code_length(self):
        self.code_length = self.spin_length.value()
        self._save_state()

    # ==========================
    # LOGIC: AUTO SENDER (WATCHER)
    # ==========================
    def add_watch_folder(self):
        dname = QFileDialog.getExistingDirectory(self, 'Select Folder to Watch')
        if dname:
            items = [self.auto_send_list.item(i).text() for i in range(self.auto_send_list.count())]
            if dname not in items:
                self.auto_send_list.addItem(dname)
                self._save_state()

    def remove_watch_folder(self):
        for item in self.auto_send_list.selectedItems():
            self.auto_send_list.takeItem(self.auto_send_list.row(item))
        self._save_state()

    def toggle_auto_send(self):
        if self.auto_send_worker and self.auto_send_worker.is_running:
            self.auto_send_worker.stop()
            self.btn_start_auto_send.setText("🚀 Start Watching & Syncing")
            self.btn_start_auto_send.setStyleSheet(
                "background-color: #4CAF50; color: white; padding: 15px; font-weight:bold; font-size:14px;")
            self.auto_send_list.setEnabled(True)
            self.auto_send_code.setReadOnly(False)
            self.log("[Watcher] 🛑 Stopped.")
        else:
            folders = [self.auto_send_list.item(i).text() for i in range(self.auto_send_list.count())]
            code = self.auto_send_code.text().strip()

            if not folders:
                QMessageBox.warning(self, "Error", "Add at least one folder to watch.")
                return
            if not code:
                QMessageBox.warning(self, "Error", "Please enter a Server Code.")
                return

            self.btn_start_auto_send.setText("🛑 Stop Watcher")
            self.btn_start_auto_send.setStyleSheet(
                "background-color: #F44336; color: white; padding: 15px; font-weight:bold; font-size:14px;")
            self.auto_send_list.setEnabled(False)
            self.auto_send_code.setReadOnly(True)

            self.auto_send_worker = AutoSendWorker(
                folders, code, self._7z_path,
                delete_after_send=self.chk_delete_sent.isChecked(),
                check_interval=self.spin_interval.value()
            )
            self.auto_send_worker.log_signal.connect(self.log)
            self.auto_send_worker.finished_signal.connect(self.on_auto_send_finished)
            self.auto_send_worker.start()

    def on_auto_send_finished(self):
        self.btn_start_auto_send.setText("🚀 Start Watching & Syncing")
        self.btn_start_auto_send.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 15px; font-weight:bold; font-size:14px;")
        self.auto_send_list.setEnabled(True)
        self.auto_send_code.setReadOnly(False)

    # ==========================
    # LOGIC: SERVER (RECEIVER)
    # ==========================
    def add_recv_listener(self):
        name = self.auto_recv_name_input.text().strip()
        code = self.auto_recv_code_input.text().strip()
        if not name or not code:
            QMessageBox.warning(self, "Missing Info", "Name and Code are required.")
            return

        safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip()
        display_str = f"{safe_name}  ::  {code}"

        existing = [self.auto_recv_list.item(i).text() for i in range(self.auto_recv_list.count())]
        if display_str not in existing:
            self.auto_recv_list.addItem(display_str)
            self._save_state()

        self.auto_recv_name_input.clear()
        self.auto_recv_code_input.clear()

    def remove_recv_listener(self):
        for item in self.auto_recv_list.selectedItems():
            self.auto_recv_list.takeItem(self.auto_recv_list.row(item))
        self._save_state()

    def toggle_auto_recv(self):
        if self.auto_recv_workers:
            for worker in self.auto_recv_workers:
                worker.stop()
            self.auto_recv_workers.clear()
            self.btn_start_auto_recv.setText("📡 Start Server Listeners")
            self.btn_start_auto_recv.setStyleSheet(
                "background-color: #2196F3; color: white; padding: 15px; font-weight:bold; font-size:14px;")
            self.auto_recv_list.setEnabled(True)
            self.log("[Server] 🛑 All listeners stopped.")
        else:
            if self.auto_recv_list.count() == 0:
                QMessageBox.warning(self, "Empty", "Add at least one listener.")
                return

            self.btn_start_auto_recv.setText("🛑 Stop Server Listeners")
            self.btn_start_auto_recv.setStyleSheet(
                "background-color: #F44336; color: white; padding: 15px; font-weight:bold; font-size:14px;")
            self.auto_recv_list.setEnabled(False)

            self.log("=" * 40)
            self.log("[Server] Initializing...")

            for i in range(self.auto_recv_list.count()):
                text = self.auto_recv_list.item(i).text()
                parts = text.split("  ::  ")
                if len(parts) == 2:
                    folder_name = parts[0]
                    code = parts[1]

                    worker = AutoRecvWorker(code, self.download_folder, folder_name, self._7z_path)
                    worker.log_signal.connect(self.log)
                    worker.extracted_signal.connect(self.refresh_file_list)
                    self.auto_recv_workers.append(worker)
                    worker.start()

    # ==========================
    # UTILS & MANUAL UI
    # ==========================
    def set_ui_state(self, state):
        self.current_state = state
        if state == "IDLE":
            self.btn_send.setText("🚀 Send")
            self.btn_send.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight:bold;")
            self.btn_send.setEnabled(True)
            self.btn_pause_send.setEnabled(False)
            self.btn_recv.setText("⬇️ Download")
            self.btn_recv.setStyleSheet("background-color: #2196F3; color: white; padding: 10px; font-weight:bold;")
            self.btn_recv.setEnabled(True)
            self.btn_pause_recv.setEnabled(False)
            self.file_path_input.setReadOnly(False)
            self.recv_code_input.setReadOnly(False)
        elif state in ["ZIPPING", "SENDING"]:
            self.btn_send.setEnabled(False)
            self.btn_pause_send.setText("⏸️ Pause")
            self.btn_pause_send.setStyleSheet(
                "background-color: #FF9800; color: white; padding: 10px; font-weight:bold;")
            self.btn_pause_send.setEnabled(state == "SENDING")
            self.btn_recv.setEnabled(False)
            self.file_path_input.setReadOnly(True)
        elif state == "PAUSED_SEND":
            self.btn_send.setText("🛑 Cancel")
            self.btn_send.setStyleSheet("background-color: #F44336; color: white; padding: 10px; font-weight:bold;")
            self.btn_send.setEnabled(True)
            self.btn_pause_send.setText("▶️ Resume")
            self.btn_pause_send.setStyleSheet(
                "background-color: #4CAF50; color: white; padding: 10px; font-weight:bold;")
            self.btn_pause_send.setEnabled(True)
        elif state == "RECEIVING":
            self.btn_send.setEnabled(False)
            self.btn_recv.setEnabled(False)
            self.btn_pause_recv.setText("⏸️ Pause")
            self.btn_pause_recv.setStyleSheet(
                "background-color: #FF9800; color: white; padding: 10px; font-weight:bold;")
            self.btn_pause_recv.setEnabled(True)
            self.recv_code_input.setReadOnly(True)
        elif state == "PAUSED_RECV":
            self.btn_recv.setText("🛑 Cancel")
            self.btn_recv.setStyleSheet("background-color: #F44336; color: white; padding: 10px; font-weight:bold;")
            self.btn_recv.setEnabled(True)
            self.btn_pause_recv.setText("▶️ Resume")
            self.btn_pause_recv.setStyleSheet(
                "background-color: #4CAF50; color: white; padding: 10px; font-weight:bold;")
            self.btn_pause_recv.setEnabled(True)

    def handle_send_click(self):
        if self.current_state == "IDLE":
            path = self.file_path_input.text()
            code = self.txt_code.text().strip()
            if not path or not code: return
            self.cleanup_staged_files()
            self.set_ui_state("ZIPPING")
            self.zip_worker = ZipWorker(path, self._7z_path)
            self.zip_worker.log_signal.connect(self.log)
            self.zip_worker.finished_signal.connect(self.on_zip_finished)
            self.zip_worker.start()
        elif self.current_state == "PAUSED_SEND":
            if self.croc_worker: self.croc_worker.stop()
            self.cleanup_staged_files()
            self.set_ui_state("IDLE")

    def handle_pause_send_click(self):
        if self.current_state == "SENDING":
            if self.croc_worker: self.croc_worker.stop()
            self.set_ui_state("PAUSED_SEND")
        elif self.current_state == "PAUSED_SEND":
            self.set_ui_state("SENDING")
            code = self.txt_code.text().strip()
            self.croc_worker = CrocWorker(["croc", "send", "--code", code, self.staged_path_to_send])
            self.croc_worker.log_signal.connect(self.log)
            self.croc_worker.finished_signal.connect(self.on_croc_send_finished)
            self.croc_worker.start()

    def on_zip_finished(self, success, staged_path, temp_base_dir):
        if success:
            self.staged_path_to_send = staged_path
            self.staged_base_temp_dir = temp_base_dir
            self.handle_pause_send_click()
        else:
            self.cleanup_staged_files()
            self.set_ui_state("IDLE")

    def on_croc_send_finished(self, was_paused, is_success):
        if is_success:
            self.cleanup_staged_files()
            self.set_ui_state("IDLE")
        else:
            self.set_ui_state("PAUSED_SEND")

    def cleanup_staged_files(self):
        if self.staged_base_temp_dir and os.path.exists(self.staged_base_temp_dir):
            shutil.rmtree(self.staged_base_temp_dir, ignore_errors=True)
        self.staged_base_temp_dir = None
        self.staged_path_to_send = None

    def handle_recv_click(self):
        if self.current_state == "IDLE":
            code = self.recv_code_input.text().strip()
            if not code: return
            self.set_ui_state("RECEIVING")
            self.croc_worker = CrocWorker(["croc", "--yes", "--out", self.download_folder, code])
            self.croc_worker.log_signal.connect(self.log)
            self.croc_worker.finished_signal.connect(self.on_croc_recv_finished)
            self.croc_worker.start()
            if self._7z_path:
                self.live_unzip_worker = LiveUnzipWorker(self.download_folder, self._7z_path)
                self.live_unzip_worker.file_extracted_signal.connect(self.refresh_file_list)
                self.live_unzip_worker.start()
        elif self.current_state == "PAUSED_RECV":
            if self.croc_worker: self.croc_worker.stop()
            self.set_ui_state("IDLE")

    def handle_pause_recv_click(self):
        if self.current_state == "RECEIVING":
            if self.croc_worker: self.croc_worker.stop()
            self.set_ui_state("PAUSED_RECV")
        elif self.current_state == "PAUSED_RECV":
            self.handle_recv_click()

    def on_croc_recv_finished(self, was_paused, is_success):
        self.refresh_file_list()
        if self.live_unzip_worker: self.live_unzip_worker.stop()
        if not is_success:
            self.set_ui_state("PAUSED_RECV")
        else:
            self.set_ui_state("IDLE")

    def browse_path(self, line_edit, is_folder):
        if is_folder:
            path = QFileDialog.getExistingDirectory(self, 'Select Folder')
        else:
            path, _ = QFileDialog.getOpenFileName(self, 'Select File')
        if path: line_edit.setText(path)

    def change_download_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Folder", self.download_folder)
        if directory:
            self.download_folder = os.path.abspath(directory)
            self.lbl_dl_path.setText(f"Viewing: <b>{self.download_folder}</b>")
            self.refresh_file_list()

    def refresh_file_list(self):
        self.file_list_widget.clear()
        if os.path.exists(self.download_folder):
            items = os.listdir(self.download_folder)
            items.sort(key=lambda x: os.path.getmtime(os.path.join(self.download_folder, x)), reverse=True)
            for item in items:
                p = os.path.join(self.download_folder, item)
                self.file_list_widget.addItem(f"📁 {item}" if os.path.isdir(p) else f"📄 {item}")

    def open_specific_file(self, item):
        target = os.path.join(self.download_folder, item.text().split(" ", 1)[-1])
        if sys.platform == "win32":
            os.startfile(target)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target])

    def log(self, message):
        self.log_area.append(message)
        cursor = self.log_area.textCursor()
        cursor.movePosition(cursor.End)
        self.log_area.setTextCursor(cursor)