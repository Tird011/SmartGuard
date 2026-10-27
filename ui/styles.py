"""Look of the app, taken from the UI mockup: light grey page, dark video panel,
monospace type, green Confirm / red Cancel, pale-blue audit table."""

QSS = """
* { font-family: 'JetBrains Mono', 'Consolas', 'Courier New', monospace; font-size: 13px; color: #111; }
QMainWindow, QDialog, QWidget#page { background: #f4f4f4; }
QLabel#video { background: #1f1f1f; color: #aaa; }
QLabel#heading { font-size: 22px; }
QLabel#error { color: #8b0a0a; }
QPushButton { background: #2b2b2b; color: #fff; border: none; padding: 7px 16px; }
QPushButton:hover { background: #444; }
QPushButton:disabled { background: #999; }
QPushButton#confirm { background: #005a2b; }
QPushButton#confirm:hover { background: #0a7a3c; }
QPushButton#cancel { background: #8b0a0a; }
QPushButton#cancel:hover { background: #ad1414; }
QPushButton#pill { background: #e6e6e6; color: #111; border-radius: 12px; padding: 7px 28px; }
QPushButton#link { background: transparent; color: #111; padding: 4px 8px; }
QPushButton#link:hover { background: #e0e0e0; }
QLineEdit, QComboBox { background: #d9d9d9; border: none; padding: 7px; }
QFrame#card { background: #d9d9d9; }
QTableWidget { background: #eef5fd; border: none; gridline-color: #dfe6ef; }
QTableWidget::item:selected { background: #cfe0f5; color: #111; }
QHeaderView::section { background: #e6e6e6; border: none; padding: 10px; font-weight: normal; }
QScrollArea { border: none; background: transparent; }
QStatusBar QLabel { padding: 0 10px; }
"""

SCAN_QSS = """
ScanDialog { background: #2b2b2b; }
ScanDialog QLabel { color: #fff; }
ScanDialog QPushButton { background: #5a5a5a; }
ScanDialog QPushButton:hover { background: #707070; }
ScanDialog QLabel#heading { font-size: 24px; }
"""
