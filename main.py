import sys
import os
import sqlite3
import datetime
import threading
from typing import List, Optional

from PyQt6.QtCore import (
    Qt, QTimer, QDateTime, QTime, QDate, pyqtSignal, QObject, QStandardPaths
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox, QDateTimeEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QDialog,
    QSystemTrayIcon, QMenu, QCheckBox, QFrame, QMessageBox
)
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction, QKeySequence, QShortcut

# Windows Registry for System Startup
try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

# Global Hotkey monitoring via pynput
try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


# ==============================================================================
# DATABASE MANAGER
# ==============================================================================
class DatabaseManager:
    """Handles local SQLite storage in the user's AppData directory."""
    def __init__(self, db_name: str = "anydo_tracker.db"):
        app_data_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        app_folder = os.path.join(app_data_dir, "TaskFlow")
        os.makedirs(app_folder, exist_ok=True)
        self.db_path = os.path.join(app_folder, db_name)
        self._init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT DEFAULT 'General',
                    due_datetime TEXT NOT NULL,
                    notes TEXT,
                    is_completed INTEGER DEFAULT 0,
                    snoozed_until TEXT,
                    recurrence TEXT DEFAULT 'None'
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

    def add_task(self, title: str, category: str, due_dt: str, notes: str, recurrence: str = "None") -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tasks (title, category, due_datetime, notes, recurrence) VALUES (?, ?, ?, ?, ?)",
                (title, category, due_dt, notes, recurrence)
            )
            conn.commit()
            return cursor.lastrowid

    def update_task(self, task_id: int, title: str, category: str, due_dt: str, notes: str, recurrence: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET title=?, category=?, due_datetime=?, notes=?, recurrence=? WHERE id=?",
                (title, category, due_dt, notes, recurrence, task_id)
            )
            conn.commit()

    def set_task_completed(self, task_id: int, completed: bool = True):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tasks SET is_completed=? WHERE id=?", (1 if completed else 0, task_id))
            conn.commit()

    def set_snooze(self, task_id: int, snooze_until_dt: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tasks SET snoozed_until=? WHERE id=?", (snooze_until_dt, task_id))
            conn.commit()

    def delete_task(self, task_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            conn.commit()

    def get_tasks(self, completed: bool = False) -> List[dict]:
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tasks WHERE is_completed=? ORDER BY due_datetime ASC",
                (1 if completed else 0,)
            )
            return [dict(r) for r in cursor.fetchall()]

    def get_due_or_overdue_tasks(self) -> List[dict]:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tasks 
                WHERE is_completed = 0 
                AND due_datetime <= ? 
                AND (snoozed_until IS NULL OR snoozed_until <= ?)
            """, (now_str, now_str))
            return [dict(r) for r in cursor.fetchall()]

    def set_setting(self, key: str, value: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default


# ==============================================================================
# GLOBAL HOTKEY SIGNAL HELPER
# ==============================================================================
class HotkeySignals(QObject):
    trigger_add_task = pyqtSignal()

hotkey_signals = HotkeySignals()


# ==============================================================================
# ANY.DO STYLESHEETS (LIGHT & DARK THEMES)
# ==============================================================================
ANYDO_LIGHT_STYLE = """
QMainWindow, QDialog {
    background-color: #FAFAFA;
    color: #172B4D;
}
QWidget {
    font-family: 'Segoe UI', -apple-system, sans-serif;
    font-size: 13px;
    color: #172B4D;
}
QFrame#Card {
    background-color: #FFFFFF;
    border-radius: 10px;
    border: 1px solid #E6E8EC;
}
QLineEdit, QTextEdit, QDateTimeEdit, QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #DFE1E6;
    border-radius: 8px;
    padding: 8px;
    color: #172B4D;
}
QLineEdit:focus, QTextEdit:focus, QDateTimeEdit:focus, QComboBox:focus {
    border: 1.5px solid #007AFF;
}
QPushButton {
    background-color: #007AFF;
    color: #FFFFFF;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    border: none;
}
QPushButton:hover {
    background-color: #0056B3;
}
QPushButton#SecondaryButton {
    background-color: #F4F5F7;
    color: #172B4D;
    border: 1px solid #DFE1E6;
}
QPushButton#SecondaryButton:hover {
    background-color: #EBECF0;
}
QPushButton#DangerButton {
    background-color: #FF3B30;
    color: #FFFFFF;
}
QPushButton#DangerButton:hover {
    background-color: #D70015;
}
QTableWidget {
    background-color: #FFFFFF;
    gridline-color: #F4F5F7;
    border-radius: 10px;
    border: 1px solid #E6E8EC;
}
QHeaderView::section {
    background-color: #FAFAFA;
    color: #5E6C84;
    padding: 8px;
    font-weight: 600;
    border: none;
}
QTabWidget::pane {
    border: 1px solid #E6E8EC;
    border-radius: 10px;
    background-color: #FFFFFF;
}
QTabBar::tab {
    background: #F4F5F7;
    color: #5E6C84;
    padding: 10px 24px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #007AFF;
    color: #FFFFFF;
}
"""

ANYDO_DARK_STYLE = """
QMainWindow, QDialog {
    background-color: #121212;
    color: #E3E3E3;
}
QWidget {
    font-family: 'Segoe UI', -apple-system, sans-serif;
    font-size: 13px;
    color: #E3E3E3;
}
QFrame#Card {
    background-color: #1E1E1E;
    border-radius: 10px;
    border: 1px solid #2C2C2C;
}
QLineEdit, QTextEdit, QDateTimeEdit, QComboBox {
    background-color: #2C2C2C;
    border: 1px solid #3D3D3D;
    border-radius: 8px;
    padding: 8px;
    color: #E3E3E3;
}
QLineEdit:focus, QTextEdit:focus, QDateTimeEdit:focus, QComboBox:focus {
    border: 1.5px solid #00A3FF;
}
QPushButton {
    background-color: #007AFF;
    color: #FFFFFF;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    border: none;
}
QPushButton:hover {
    background-color: #00A3FF;
}
QPushButton#SecondaryButton {
    background-color: #2C2C2C;
    color: #E3E3E3;
    border: 1px solid #3D3D3D;
}
QPushButton#SecondaryButton:hover {
    background-color: #3D3D3D;
}
QPushButton#DangerButton {
    background-color: #FF453A;
    color: #FFFFFF;
}
QPushButton#DangerButton:hover {
    background-color: #FF6961;
}
QTableWidget {
    background-color: #1E1E1E;
    gridline-color: #2C2C2C;
    border-radius: 10px;
    border: 1px solid #2C2C2C;
}
QHeaderView::section {
    background-color: #121212;
    color: #8E8E93;
    padding: 8px;
    font-weight: 600;
    border: none;
}
QTabWidget::pane {
    border: 1px solid #2C2C2C;
    border-radius: 10px;
    background-color: #1E1E1E;
}
QTabBar::tab {
    background: #2C2C2C;
    color: #8E8E93;
    padding: 10px 24px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #007AFF;
    color: #FFFFFF;
}
"""


# ==============================================================================
# ADD / EDIT TASK DIALOG
# ==============================================================================
class TaskDialog(QDialog):
    """Clean Any.do dialog to add or edit a task."""
    def __init__(self, parent=None, task_data: Optional[dict] = None):
        super().__init__(parent)
        self.task_data = task_data
        self.setWindowTitle("Edit Task" if task_data else "New Task")
        self.setMinimumWidth(440)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Title
        layout.addWidget(QLabel("Task Title:"))
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("e.g. Finish Math homework, Call client, Pay bills...")
        layout.addWidget(self.title_input)

        # Category Tag
        layout.addWidget(QLabel("Category / Subject:"))
        self.category_input = QComboBox()
        self.category_input.setEditable(True)
        self.category_input.addItems(["General", "Math", "Science", "English", "History", "Work", "Personal"])
        layout.addWidget(self.category_input)

        # Due Date & Time
        layout.addWidget(QLabel("Due Date & Time:"))
        self.due_picker = QDateTimeEdit()
        self.due_picker.setCalendarPopup(True)
        self.due_picker.setDateTime(QDateTime.currentDateTime().addDays(1))
        self.due_picker.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addWidget(self.due_picker)

        # Recurrence
        layout.addWidget(QLabel("Recurrence:"))
        self.recurrence_combo = QComboBox()
        self.recurrence_combo.addItems(["None", "Daily", "Weekdays", "Hourly"])
        layout.addWidget(self.recurrence_combo)

        # Notes / Links
        layout.addWidget(QLabel("Notes & Reference Links:"))
        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Add relevant links or instructions here...")
        self.notes_input.setMaximumHeight(90)
        layout.addWidget(self.notes_input)

        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Task")
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("SecondaryButton")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        # Populate if editing
        if self.task_data:
            self.title_input.setText(self.task_data.get('title', ''))
            self.category_input.setCurrentText(self.task_data.get('category', 'General'))
            dt = QDateTime.fromString(self.task_data.get('due_datetime', ''), "yyyy-MM-dd HH:mm:ss")
            if dt.isValid():
                self.due_picker.setDateTime(dt)
            self.notes_input.setText(self.task_data.get('notes', ''))
            self.recurrence_combo.setCurrentText(self.task_data.get('recurrence', 'None'))

    def get_data(self) -> dict:
        return {
            'title': self.title_input.text().strip(),
            'category': self.category_input.currentText().strip(),
            'due_datetime': self.due_picker.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            'notes': self.notes_input.toPlainText().strip(),
            'recurrence': self.recurrence_combo.currentText()
        }


# ==============================================================================
# SETTINGS DIALOG
# ==============================================================================
class SettingsDialog(QDialog):
    """Configuration dialog for auto-start and daily alert time."""
    def __init__(self, parent, db: DatabaseManager):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # Auto-start on boot
        self.autostart_cb = QCheckBox("Run automatically when computer starts")
        is_autostart = self.db.get_setting("autostart", "0") == "1"
        self.autostart_cb.setChecked(is_autostart)
        layout.addWidget(self.autostart_cb)

        # Scheduled Daily Alert Time
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Daily Reminder Time:"))
        self.daily_time_picker = QDateTimeEdit()
        self.daily_time_picker.setDisplayFormat("HH:mm")
        saved_time = self.db.get_setting("daily_alert_time", "16:00")
        qtime = QTime.fromString(saved_time, "HH:mm")
        self.daily_time_picker.setTime(qtime if qtime.isValid() else QTime(16, 0))
        time_layout.addWidget(self.daily_time_picker)
        layout.addLayout(time_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def save_settings(self):
        enable_startup = self.autostart_cb.isChecked()
        self.db.set_setting("autostart", "1" if enable_startup else "0")

        if HAS_WINREG:
            self.set_windows_autostart(enable_startup)

        self.db.set_setting("daily_alert_time", self.daily_time_picker.time().toString("HH:mm"))
        self.accept()

    def set_windows_autostart(self, enable: bool):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "AnyDoTaskTracker"
        exe_path = f'"{sys.executable}"' if getattr(sys, 'frozen', False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print("Error updating registry:", e)


# ==============================================================================
# SMART NOTIFICATION POPUP (ANY.DO TOAST)
# ==============================================================================
class NotificationPopup(QWidget):
    """Unobtrusive floating desktop notification window."""
    def __init__(self, task: dict, db: DatabaseManager, main_win: 'MainWindow'):
        super().__init__(None)
        self.task = task
        self.db = db
        self.main_win = main_win

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(340)

        self.init_ui()
        self.position_at_bottom_right()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)

        # Header
        hdr_layout = QHBoxLayout()
        cat_lbl = QLabel(f"[{self.task.get('category', 'Task')}]")
        cat_lbl.setStyleSheet("font-weight: bold; color: #007AFF;")
        hdr_layout.addWidget(cat_lbl)
        hdr_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.close)
        hdr_layout.addWidget(close_btn)
        card_layout.addLayout(hdr_layout)

        # Title
        title_lbl = QLabel(self.task.get('title', 'Task Due!'))
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        title_lbl.setWordWrap(True)
        card_layout.addWidget(title_lbl)

        # Due Info
        due_lbl = QLabel(f"Due: {self.task.get('due_datetime', '')}")
        due_lbl.setStyleSheet("color: #8E8E93; font-size: 11px;")
        card_layout.addWidget(due_lbl)

        # Actions
        btn_layout = QHBoxLayout()

        done_btn = QPushButton("Mark Done")
        done_btn.clicked.connect(self.mark_done)

        snooze_combo = QComboBox()
        snooze_combo.addItems(["Snooze...", "15 Mins", "1 Hour", "Tomorrow"])
        snooze_combo.activated.connect(lambda idx: self.handle_snooze(snooze_combo, idx))

        open_btn = QPushButton("Open")
        open_btn.setObjectName("SecondaryButton")
        open_btn.clicked.connect(self.open_full_list)

        btn_layout.addWidget(done_btn)
        btn_layout.addWidget(snooze_combo)
        btn_layout.addWidget(open_btn)

        card_layout.addLayout(btn_layout)
        layout.addWidget(card)

        is_dark = self.db.get_setting("theme", "dark") == "dark"
        self.setStyleSheet(ANYDO_DARK_STYLE if is_dark else ANYDO_LIGHT_STYLE)

    def position_at_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.width() - self.width() - 20
        y = screen.height() - self.height() - 40
        self.move(x, y)

    def mark_done(self):
        self.db.set_task_completed(self.task['id'], True)
        self.main_win.load_tasks()
        self.close()

    def handle_snooze(self, combo, index):
        if index == 0:
            return
        now = datetime.datetime.now()
        if index == 1:
            snooze_dt = now + datetime.timedelta(minutes=15)
        elif index == 2:
            snooze_dt = now + datetime.timedelta(hours=1)
        else:
            snooze_dt = now + datetime.timedelta(days=1)

        self.db.set_snooze(self.task['id'], snooze_dt.strftime("%Y-%m-%d %H:%M:%S"))
        self.main_win.load_tasks()
        self.close()

    def open_full_list(self):
        self.main_win.show_and_activate()
        self.close()


# ==============================================================================
# MAIN APPLICATION WINDOW
# ==============================================================================
class MainWindow(QMainWindow):
    """Main desktop interface."""
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.last_tick_time = datetime.datetime.now()

        self.setWindowTitle("TaskFlow - Any.do Smart Tracker")

        self.init_ui()
        self.init_tray()
        self.init_scheduler()
        self.apply_theme()

        # Connect global hotkey signal
        hotkey_signals.trigger_add_task.connect(self.open_add_dialog)

        # Launch in windowed full screen (maximized)
        self.showMaximized()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # Header Bar
        hdr_layout = QHBoxLayout()
        title = QLabel("TaskFlow")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #007AFF;")
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        add_btn = QPushButton("+ New Task")
        add_btn.clicked.connect(self.open_add_dialog)
        hdr_layout.addWidget(add_btn)

        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setObjectName("SecondaryButton")
        settings_btn.clicked.connect(self.open_settings)
        hdr_layout.addWidget(settings_btn)

        # Dark Mode Toggle Button
        self.theme_toggle_btn = QPushButton("🌙 Dark Mode")
        self.theme_toggle_btn.setObjectName("SecondaryButton")
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)
        hdr_layout.addWidget(self.theme_toggle_btn)

        main_layout.addLayout(hdr_layout)

        # Search / Category Filter Bar
        filter_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search tasks...")
        self.search_input.textChanged.connect(self.load_tasks)
        filter_layout.addWidget(self.search_input)

        self.category_filter = QComboBox()
        self.category_filter.addItems(["All Categories", "General", "Math", "Science", "English", "History", "Work", "Personal"])
        self.category_filter.currentTextChanged.connect(self.load_tasks)
        filter_layout.addWidget(self.category_filter)

        main_layout.addLayout(filter_layout)

        # Tabs: Active Tasks vs Completed Tasks
        self.tabs = QTabWidget()

        self.active_table = QTableWidget()
        self.setup_table(self.active_table)
        self.tabs.addTab(self.active_table, "Active Tasks")

        self.completed_table = QTableWidget()
        self.setup_table(self.completed_table)
        self.tabs.addTab(self.completed_table, "Completed Tasks")

        main_layout.addWidget(self.tabs)

        # Global Hotkey Shortcut (Ctrl+Shift+H)
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+H"), self)
        shortcut.activated.connect(self.open_add_dialog)

        self.load_tasks()

    def setup_table(self, table: QTableWidget):
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["Done", "Task Title", "Category", "Due Date", "Recurrence", "Actions"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)

    def toggle_theme(self):
        is_dark = self.db.get_setting("theme", "dark") == "dark"
        new_theme = "light" if is_dark else "dark"
        self.db.set_setting("theme", new_theme)
        self.apply_theme()

    def apply_theme(self):
        is_dark = self.db.get_setting("theme", "dark") == "dark"
        if is_dark:
            self.setStyleSheet(ANYDO_DARK_STYLE)
            self.theme_toggle_btn.setText("☀️ Light Mode")
        else:
            self.setStyleSheet(ANYDO_LIGHT_STYLE)
            self.theme_toggle_btn.setText("🌙 Dark Mode")

    def load_tasks(self):
        query = self.search_input.text().lower()
        selected_cat = self.category_filter.currentText()

        active_tasks = self.db.get_tasks(completed=False)
        self.populate_table(self.active_table, active_tasks, is_active=True, query=query, category=selected_cat)

        completed_tasks = self.db.get_tasks(completed=True)
        self.populate_table(self.completed_table, completed_tasks, is_active=False, query=query, category=selected_cat)

    def populate_table(self, table: QTableWidget, tasks: List[dict], is_active: bool, query: str, category: str):
        table.setRowCount(0)

        for task in tasks:
            if query and query not in task['title'].lower() and query not in task['notes'].lower():
                continue
            if category != "All Categories" and task['category'] != category:
                continue

            row = table.rowCount()
            table.insertRow(row)

            # Done Checkbox
            chk = QCheckBox()
            chk.setChecked(not is_active)
            chk.stateChanged.connect(lambda state, t_id=task['id']: self.toggle_task_complete(t_id, state))

            cell_widget = QWidget()
            layout = QHBoxLayout(cell_widget)
            layout.addWidget(chk)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            table.setCellWidget(row, 0, cell_widget)

            # Title
            table.setItem(row, 1, QTableWidgetItem(task['title']))
            # Category
            table.setItem(row, 2, QTableWidgetItem(task['category']))
            # Due Date
            table.setItem(row, 3, QTableWidgetItem(task['due_datetime']))
            # Recurrence
            table.setItem(row, 4, QTableWidgetItem(task['recurrence']))

            # Actions
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)

            edit_btn = QPushButton("Edit")
            edit_btn.setObjectName("SecondaryButton")
            edit_btn.setFixedSize(50, 24)
            edit_btn.clicked.connect(lambda _, t=task: self.open_edit_dialog(t))

            del_btn = QPushButton("Delete")
            del_btn.setObjectName("DangerButton")
            del_btn.setFixedSize(55, 24)
            del_btn.clicked.connect(lambda _, t_id=task['id']: self.delete_task(t_id))

            act_layout.addWidget(edit_btn)
            act_layout.addWidget(del_btn)
            table.setCellWidget(row, 5, act_widget)

    def toggle_task_complete(self, task_id: int, state: int):
        is_done = (state == Qt.CheckState.Checked.value or state == 2)
        self.db.set_task_completed(task_id, is_done)
        self.load_tasks()

    def open_add_dialog(self):
        dlg = TaskDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            if data['title']:
                self.db.add_task(data['title'], data['category'], data['due_datetime'], data['notes'], data['recurrence'])
                self.load_tasks()

    def open_edit_dialog(self, task: dict):
        dlg = TaskDialog(self, task)
        if dlg.exec():
            data = dlg.get_data()
            if data['title']:
                self.db.update_task(task['id'], data['title'], data['category'], data['due_datetime'], data['notes'], data['recurrence'])
                self.load_tasks()

    def delete_task(self, task_id: int):
        res = QMessageBox.question(self, "Confirm Delete", "Are you sure you want to delete this task?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res == QMessageBox.StandardButton.Yes:
            self.db.delete_task(task_id)
            self.load_tasks()

    def open_settings(self):
        dlg = SettingsDialog(self, self.db)
        if dlg.exec():
            self.apply_theme()

    def show_and_activate(self):
        self.showMaximized()
        self.activateWindow()
        self.raise_()

    # System Tray Integration
    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#007AFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, 32, 32, 8, 8)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        painter.drawText(0, 0, 32, 32, Qt.AlignmentFlag.AlignCenter, "✓")
        painter.end()

        icon = QIcon(pixmap)
        self.setWindowIcon(icon)
        self.tray_icon.setIcon(icon)

        tray_menu = QMenu()
        show_action = QAction("Open TaskFlow", self)
        show_action.triggered.connect(self.show_and_activate)
        add_action = QAction("+ Quick Add Task", self)
        add_action.triggered.connect(self.open_add_dialog)
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(show_action)
        tray_menu.addAction(add_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.show()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_and_activate()

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            self.hide()
            self.tray_icon.showMessage(
                "TaskFlow",
                "App is running in the background system tray.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
            event.ignore()

    # Background Scheduler & Wake Detector
    def init_scheduler(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.scheduler_tick)
        self.timer.start(10000)

    def scheduler_tick(self):
        now = datetime.datetime.now()

        elapsed = (now - self.last_tick_time).total_seconds()
        if elapsed > 60:
            self.on_system_wake()
        self.last_tick_time = now

        due_tasks = self.db.get_due_or_overdue_tasks()
        for task in due_tasks:
            self.trigger_popup(task)

        daily_time_str = self.db.get_setting("daily_alert_time", "16:00")
        current_time_str = now.strftime("%H:%M")
        last_daily_trigger = self.db.get_setting("last_daily_trigger", "")

        if current_time_str == daily_time_str and last_daily_trigger != now.strftime("%Y-%m-%d"):
            self.db.set_setting("last_daily_trigger", now.strftime("%Y-%m-%d"))
            active_tasks = self.db.get_tasks(completed=False)
            if active_tasks:
                self.trigger_popup({
                    'id': active_tasks[0]['id'],
                    'title': f"Daily Summary: You have {len(active_tasks)} active task(s)!",
                    'category': 'Daily Alert',
                    'due_datetime': active_tasks[0]['due_datetime']
                })

    def on_system_wake(self):
        active_tasks = self.db.get_tasks(completed=False)
        if active_tasks:
            self.trigger_popup({
                'id': active_tasks[0]['id'],
                'title': f"Welcome back! You have {len(active_tasks)} active task(s).",
                'category': 'Wake Reminder',
                'due_datetime': active_tasks[0]['due_datetime']
            })

    def trigger_popup(self, task: dict):
        popup = NotificationPopup(task, self.db, self)
        popup.show()


# Global Hotkey Thread
def start_global_hotkey():
    if not HAS_PYNPUT:
        return

    def on_activate():
        hotkey_signals.trigger_add_task.emit()

    try:
        hotkey = keyboard.GlobalHotKeys({'<ctrl>+<shift>+h': on_activate})
        hotkey.start()
    except Exception as e:
        print("Global hotkey error:", e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    db = DatabaseManager()
    main_window = MainWindow(db)

    hotkey_thread = threading.Thread(target=start_global_hotkey, daemon=True)
    hotkey_thread.start()

    sys.exit(app.exec())