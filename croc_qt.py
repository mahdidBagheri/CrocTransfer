import sys
import subprocess
import os
import random
import string
import logging
import tempfile
import shutil
import time
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTextEdit,
                             QFileDialog, QGroupBox, QMessageBox, QTabWidget,
                             QSpinBox, QFormLayout, QListWidget)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont

# --- SETUP LOGGING ---
logging.basicConfig(
    filename='croc_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("=== Croc GUI Started ===")


def get_7z_path():
    if sys.platform == 'win32':
        paths = [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]
        for p in paths:
            if os.path.exists(p):
                return p
    try:
        subprocess.run(["7z"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "7z"
    except FileNotFoundError:
        return None


# --- SENDER: ZIP WORKER ---
class ZipWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str, str)

    def __init__(self, source_path, _7z_path):
        super().__init__()
        self.source_path = source_path
        self._7z_path = _7z_path

    def run(self):
        try:
            self.log_signal.emit("🗜️ Preparing files for transfer (Zipping)...")
            temp_base_dir = tempfile.mkdtemp(prefix="croc_send_")
            is_dir = os.path.isdir(self.source_path)

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            if is_dir:
                folder_name = os.path.basename(os.path.normpath(self.source_path))
                staged_path = os.path.join(temp_base_dir, folder_name)
                os.makedirs(staged_path)

                items = os.listdir(self.source_path)
                for item in items:
                    item_full = os.path.join(self.source_path, item)
                    out_7z = os.path.join(staged_path, item + ".7z")
                    self.log_signal.emit(f"  -> Zipping: {item}")

                    cmd = [self._7z_path, "a", "-mx=3", out_7z, item_full]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)
            else:
                out_7z = os.path.join(temp_base_dir, os.path.basename(self.source_path) + ".7z")
                staged_path = out_7z
                self.log_signal.emit(f"  -> Zipping file...")
                cmd = [self._7z_path, "a", "-mx=3", out_7z, self.source_path]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo)

            self.log_signal.emit("✅ Zipping complete.")
            self.finished_signal.emit(True, staged_path, temp_base_dir)

        except Exception as e:
            self.log_signal.emit(f"❌ Zip Error: {e}")
            logging.error(f"Zip Error: {e}")
            self.finished_signal.emit(False, "", "")


# --- RECEIVER: LIVE UNZIP WORKER ---
class LiveUnzipWorker(QThread):
    log_signal = pyqtSignal(str)
    file_extracted_signal = pyqtSignal()

    def __init__(self, download_dir, _7z_path):
        super().__init__()
        self.download_dir = download_dir
        self._7z_path = _7z_path
        self.is_running = True

    def run(self):
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        while self.is_running:
            self.process_files(startupinfo)
            time.sleep(1.5)

        self.process_files(startupinfo)

    def process_files(self, startupinfo):
        for root, dirs, files in os.walk(self.download_dir):
            for f in files:
                if f.endswith(".7z"):
                    filepath = os.path.join(root, f)

                    is_ready = False
                    if os.name == 'nt':
                        try:
                            with open(filepath, 'a'):
                                pass
                            is_ready = True
                        except IOError:
                            is_ready = False
                    else:
                        is_ready = True

                    if is_ready:
                        test_cmd = [self._7z_path, "t", filepath]
                        test_result = subprocess.run(test_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                     startupinfo=startupinfo)

                        if test_result.returncode == 0:
                            extract_cmd = [self._7z_path, "x", "-y", filepath, f"-o{root}"]
                            extract_result = subprocess.run(extract_cmd, stdout=subprocess.DEVNULL,
                                                            stderr=subprocess.DEVNULL, startupinfo=startupinfo)

                            if extract_result.returncode == 0:
                                try:
                                    os.remove(filepath)
                                    original_name = f[:-3]
                                    self.log_signal.emit(f"📦 Extracted & Ready: {original_name}")
                                    self.file_extracted_signal.emit()
                                except OSError:
                                    pass

    def stop(self):
        self.is_running = False


# --- MAIN CROC WORKER ---
class CrocWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, bool)

    def __init__(self, command_args):
        super().__init__()
        self.command_args = command_args
        self.process = None
        self.is_killed = False

    def run(self):
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        cmd_string = " ".join(self.command_args)
        logging.info(f"Executing command: {cmd_string}")

        try:
            self.process = subprocess.Popen(
                self.command_args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',  # <--- FIX: Forces Python to read UTF-8 progress blocks
                errors='replace',  # <--- FIX: Prevents crashes if weird characters do appear
                bufsize=1,
                startupinfo=startupinfo
            )

            for line in self.process.stdout:
                clean_line = line.strip()
                if clean_line:
                    logging.debug(f"Croc output: {clean_line}")
                    self.log_signal.emit(clean_line)

            self.process.wait()
            is_success = (self.process.returncode == 0)

            if self.is_killed:
                self.log_signal.emit("\n⏸️ Transfer Paused manually.")
            else:
                if is_success:
                    self.log_signal.emit("\n✅ Transfer Completed Successfully!")
                else:
                    self.log_signal.emit(f"\n⚠️ Connection dropped. (Code {self.process.returncode})")

            self.finished_signal.emit(self.is_killed, is_success)

        except FileNotFoundError:
            self.log_signal.emit("❌ Error: 'croc' command not found.")
            self.finished_signal.emit(False, False)
        except Exception as e:
            self.log_signal.emit(f"❌ System Error: {str(e)}")
            self.finished_signal.emit(False, False)

    def stop(self):
        self.is_killed = True
        if self.process:
            self.process.terminate()


# --- MAIN APP ---
class CrocApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Croc Transfer Ultimate + Live AutoZip")
        self.resize(750, 700)

        self.croc_worker = None
        self.zip_worker = None
        self.live_unzip_worker = None

        self._7z_path = get_7z_path()
        self.staged_path_to_send = None
        self.staged_base_temp_dir = None

        self.code_length = 6
        self.current_state = "IDLE"

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.download_folder = os.path.join(base_dir, "received")
        if not os.path.exists(self.download_folder):
            os.makedirs(self.download_folder)

        self.init_ui()
        self.regenerate_code()
        self.refresh_file_list()
        self.set_ui_state("IDLE")

        if not self._7z_path:
            QMessageBox.critical(self, "Dependency Missing",
                                 "7-Zip was not found on your system!\n\n"
                                 "To use the auto-zip folder feature, please download and install 7-Zip from 7-zip.org")

    def init_ui(self):
        main_layout = QVBoxLayout()

        self.tabs = QTabWidget()
        self.tab_transfer = QWidget()
        self.tab_downloads = QWidget()
        self.tab_settings = QWidget()

        self.tabs.addTab(self.tab_transfer, "📂 Transfer")
        self.tabs.addTab(self.tab_downloads, "📥 Received Items")
        self.tabs.addTab(self.tab_settings, "⚙️ Settings")

        self.setup_transfer_tab()
        self.setup_downloads_tab()
        self.setup_settings_tab()

        main_layout.addWidget(self.tabs)

        self.log_group = QGroupBox("📜 Activity Log")
        log_layout = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        # Using Consolas ensures the progress bar characters align perfectly
        self.log_area.setFont(QFont("Consolas", 10))
        self.log_area.setStyleSheet("background-color: #1e1e1e; color: #4CAF50; border-radius: 5px;")
        log_layout.addWidget(self.log_area)
        self.log_group.setLayout(log_layout)

        main_layout.addWidget(self.log_group)
        self.setLayout(main_layout)

    def setup_transfer_tab(self):
        layout = QVBoxLayout()

        code_group = QGroupBox("🔑 Transfer Code")
        code_layout = QHBoxLayout()

        self.txt_code = QLineEdit()
        self.txt_code.setFont(QFont("Arial", 14, QFont.Bold))
        self.txt_code.setAlignment(Qt.AlignCenter)
        self.txt_code.setStyleSheet("padding: 5px; background-color: #e3f2fd;")

        btn_regen = QPushButton("Regenerate 🔄")
        btn_regen.clicked.connect(self.regenerate_code)

        btn_copy = QPushButton("Copy 📋")
        btn_copy.clicked.connect(self.copy_code_to_clipboard)

        code_layout.addWidget(self.txt_code)
        code_layout.addWidget(btn_regen)
        code_layout.addWidget(btn_copy)
        code_group.setLayout(code_layout)

        send_group = QGroupBox("📤 Sender")
        send_layout = QVBoxLayout()

        file_row = QHBoxLayout()
        self.file_path_input = QLineEdit()
        self.file_path_input.setPlaceholderText("Select a file or folder to send...")

        btn_browse_file = QPushButton("📄 File...")
        btn_browse_file.clicked.connect(self.browse_send_file)

        btn_browse_folder = QPushButton("📁 Folder...")
        btn_browse_folder.clicked.connect(self.browse_send_folder)

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

        recv_group = QGroupBox("📥 Receiver")
        recv_layout = QVBoxLayout()

        dir_layout = QHBoxLayout()
        self.lbl_save_dir = QLabel(f"Save to: <b>{self.download_folder}</b>")
        btn_change_dir = QPushButton("Change Folder...")
        btn_change_dir.clicked.connect(self.change_download_dir)
        dir_layout.addWidget(self.lbl_save_dir)
        dir_layout.addStretch()
        dir_layout.addWidget(btn_change_dir)

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

        recv_layout.addLayout(dir_layout)
        recv_layout.addLayout(code_layout)
        recv_group.setLayout(recv_layout)

        layout.addWidget(code_group)
        layout.addWidget(send_group)
        layout.addSpacing(10)
        layout.addWidget(recv_group)
        layout.addStretch()
        self.tab_transfer.setLayout(layout)

    def setup_downloads_tab(self):
        layout = QVBoxLayout()
        header_layout = QHBoxLayout()
        self.lbl_dl_path = QLabel(f"Viewing: <b>{self.download_folder}</b>")

        btn_open_folder = QPushButton("📂 Open Directory")
        btn_open_folder.clicked.connect(self.open_download_folder_in_os)

        btn_refresh = QPushButton("🔄 Refresh List")
        btn_refresh.clicked.connect(self.refresh_file_list)

        header_layout.addWidget(self.lbl_dl_path)
        header_layout.addStretch()
        header_layout.addWidget(btn_refresh)
        header_layout.addWidget(btn_open_folder)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setStyleSheet("font-size: 14px; padding: 5px;")
        self.file_list_widget.itemDoubleClicked.connect(self.open_specific_file)

        layout.addLayout(header_layout)
        layout.addWidget(self.file_list_widget)
        self.tab_downloads.setLayout(layout)

    def setup_settings_tab(self):
        layout = QFormLayout()
        self.spin_length = QSpinBox()
        self.spin_length.setRange(4, 20)
        self.spin_length.setValue(6)
        self.spin_length.valueChanged.connect(self.update_settings)
        layout.addRow("Auto-Code Length:", self.spin_length)
        self.tab_settings.setLayout(layout)

    # --- STATE MACHINE ---
    def set_ui_state(self, state):
        self.current_state = state

        if state == "IDLE":
            self.btn_send.setText("🚀 Send")
            self.btn_send.setStyleSheet("background-color: #4CAF50; color: white; padding: 10px; font-weight:bold;")
            self.btn_send.setEnabled(True)
            self.btn_pause_send.setText("⏸️ Pause")
            self.btn_pause_send.setStyleSheet("padding: 10px; font-weight:bold;")
            self.btn_pause_send.setEnabled(False)

            self.btn_recv.setText("⬇️ Download")
            self.btn_recv.setStyleSheet("background-color: #2196F3; color: white; padding: 10px; font-weight:bold;")
            self.btn_recv.setEnabled(True)
            self.btn_pause_recv.setText("⏸️ Pause")
            self.btn_pause_recv.setStyleSheet("padding: 10px; font-weight:bold;")
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
            self.btn_pause_recv.setEnabled(False)
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
            self.btn_pause_send.setEnabled(False)

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

            self.btn_pause_recv.setText("▶️ Resume (Ask Sender to Resume too!)")
            self.btn_pause_recv.setStyleSheet(
                "background-color: #4CAF50; color: white; padding: 10px; font-weight:bold;")
            self.btn_pause_recv.setEnabled(True)

    # --- CLICK HANDLERS ---
    def handle_send_click(self):
        if self.current_state == "IDLE":
            self.start_zipping_and_send()
        elif self.current_state == "PAUSED_SEND":
            self.cleanup_and_cancel_send()

    def handle_pause_send_click(self):
        if self.current_state == "SENDING":
            self.pause_transfer("PAUSED_SEND")
        elif self.current_state == "PAUSED_SEND":
            self.log("▶️ Resuming send... Waiting for receiver...")
            self.execute_croc_send()

    def handle_recv_click(self):
        if self.current_state == "IDLE":
            self.start_recv()
        elif self.current_state == "PAUSED_RECV":
            self.cancel_recv()

    def handle_pause_recv_click(self):
        if self.current_state == "RECEIVING":
            self.pause_transfer("PAUSED_RECV")
            self.log("⚠️ Transfer Paused. The Sender was disconnected.")
            self.log("❗ To continue, BOTH Sender and Receiver must click Resume.")
        elif self.current_state == "PAUSED_RECV":
            self.log("▶️ Resuming download... (Ensure Sender has clicked Resume too)")
            self.start_recv()

    # --- SENDER LOGIC ---
    def start_zipping_and_send(self):
        self.cleanup_staged_files()

        path_to_send = self.file_path_input.text()
        code = self.txt_code.text().strip()

        if not path_to_send or not code:
            QMessageBox.warning(self, "Warning", "Please select a file/folder and ensure code is present.")
            return
        if not self._7z_path:
            QMessageBox.critical(self, "Error", "7-Zip is required for this action.")
            return

        self.log("-" * 40)
        self.set_ui_state("ZIPPING")

        self.zip_worker = ZipWorker(path_to_send, self._7z_path)
        self.zip_worker.log_signal.connect(self.log)
        self.zip_worker.finished_signal.connect(self.on_zip_finished)
        self.zip_worker.start()

    def on_zip_finished(self, success, staged_path, temp_base_dir):
        if success:
            self.staged_path_to_send = staged_path
            self.staged_base_temp_dir = temp_base_dir
            self.execute_croc_send()
        else:
            self.cleanup_and_cancel_send()

    def execute_croc_send(self):
        self.set_ui_state("SENDING")
        code = self.txt_code.text().strip()
        cmd = ["croc", "send", "--code", code, self.staged_path_to_send]

        self.croc_worker = CrocWorker(cmd)
        self.croc_worker.log_signal.connect(self.log)
        self.croc_worker.finished_signal.connect(self.on_croc_send_finished)
        self.croc_worker.start()

    def on_croc_send_finished(self, was_paused, is_success):
        if is_success:
            self.cleanup_staged_files()
            self.set_ui_state("IDLE")
        else:
            self.set_ui_state("PAUSED_SEND")
            if not was_paused:
                self.log("⚠️ Disconnected from receiver. Click ▶️ Resume when they are ready.")
                self.log("(Your files are already prepared and ready to instantly resume)")

    def cleanup_and_cancel_send(self):
        if self.croc_worker and self.croc_worker.isRunning():
            self.croc_worker.stop()
        self.cleanup_staged_files()
        self.log("🛑 Transfer Cancelled and Temp Files Cleaned.")
        self.set_ui_state("IDLE")

    def cleanup_staged_files(self):
        if self.staged_base_temp_dir and os.path.exists(self.staged_base_temp_dir):
            try:
                shutil.rmtree(self.staged_base_temp_dir)
            except Exception:
                pass
        self.staged_base_temp_dir = None
        self.staged_path_to_send = None

    # --- RECEIVER LOGIC ---
    def start_recv(self):
        code = self.recv_code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Warning", "Please enter a code to download.")
            return

        if self.current_state == "IDLE":
            self.log("-" * 40)
            self.log("📡 Starting download...")

        self.set_ui_state("RECEIVING")
        cmd = ["croc", "--yes", "--out", self.download_folder, code]

        self.croc_worker = CrocWorker(cmd)
        self.croc_worker.log_signal.connect(self.log)
        self.croc_worker.finished_signal.connect(self.on_croc_recv_finished)
        self.croc_worker.start()

        if self._7z_path:
            self.live_unzip_worker = LiveUnzipWorker(self.download_folder, self._7z_path)
            self.live_unzip_worker.log_signal.connect(self.log)
            self.live_unzip_worker.file_extracted_signal.connect(self.refresh_file_list)
            self.live_unzip_worker.finished.connect(self.on_live_unzip_finished)
            self.live_unzip_worker.start()

    def on_croc_recv_finished(self, was_paused, is_success):
        self.refresh_file_list()

        if self.live_unzip_worker and self.live_unzip_worker.isRunning():
            self.live_unzip_worker.stop()

        if not is_success:
            self.set_ui_state("PAUSED_RECV")
            if not was_paused:
                self.log("⚠️ Connection dropped. Both Sender and Receiver should click Resume.")

    def on_live_unzip_finished(self):
        self.refresh_file_list()
        if self.current_state == "RECEIVING":
            self.set_ui_state("IDLE")

    def pause_transfer(self, target_state):
        if self.croc_worker and self.croc_worker.isRunning():
            self.croc_worker.stop()
        self.set_ui_state(target_state)

    def cancel_recv(self):
        if self.croc_worker and self.croc_worker.isRunning():
            self.croc_worker.stop()
        self.log("🛑 Download Cancelled by user.")
        self.set_ui_state("IDLE")

    # --- UTILS ---
    def update_settings(self):
        self.code_length = self.spin_length.value()

    def regenerate_code(self):
        chars = string.ascii_lowercase + string.digits
        new_code = ''.join(random.choices(chars, k=self.code_length))
        prefixes = ["send", "file", "data", "blue", "red", "fast"]
        self.txt_code.setText(f"{random.choice(prefixes)}-{new_code}")

    def copy_code_to_clipboard(self):
        cb = QApplication.clipboard()
        cb.setText(self.txt_code.text())
        self.log("📋 Copied to clipboard!")

    def browse_send_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Select File', os.path.expanduser("~"))
        if fname: self.file_path_input.setText(fname)

    def browse_send_folder(self):
        dname = QFileDialog.getExistingDirectory(self, 'Select Folder', os.path.expanduser("~"))
        if dname: self.file_path_input.setText(dname)

    def change_download_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Folder", self.download_folder)
        if directory:
            self.download_folder = os.path.abspath(directory)
            self.lbl_save_dir.setText(f"Save to: <b>{self.download_folder}</b>")
            self.lbl_dl_path.setText(f"Viewing: <b>{self.download_folder}</b>")
            self.refresh_file_list()

    def refresh_file_list(self):
        self.file_list_widget.clear()
        if os.path.exists(self.download_folder):
            try:
                items = os.listdir(self.download_folder)
                items.sort(key=lambda x: os.path.getmtime(os.path.join(self.download_folder, x)), reverse=True)
                for item in items:
                    item_path = os.path.join(self.download_folder, item)
                    self.file_list_widget.addItem(f"📁 {item}" if os.path.isdir(item_path) else f"📄 {item}")
            except Exception as e:
                self.log(f"Error reading directory: {e}")

    def open_download_folder_in_os(self):
        if sys.platform == "win32":
            os.startfile(self.download_folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", self.download_folder])
        else:
            subprocess.Popen(["xdg-open", self.download_folder])

    def open_specific_file(self, item):
        target_path = os.path.join(self.download_folder, item.text().split(" ", 1)[-1])
        if sys.platform == "win32":
            os.startfile(target_path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target_path])

    def log(self, message):
        self.log_area.append(message)
        cursor = self.log_area.textCursor()
        cursor.movePosition(cursor.End)
        self.log_area.setTextCursor(cursor)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = CrocApp()
    window.show()
    sys.exit(app.exec_())