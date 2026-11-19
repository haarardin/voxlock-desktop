"""Common, platform-independent Qt visual theme."""

QSS = """
QMainWindow, QWidget#root { background: #10151e; color: #eef3fa; }
QWidget { font-family: "Inter", "Noto Sans", "Segoe UI", sans-serif; font-size: 13px; color: #e8edf3; }
QFrame#sidebar { background: #141b27; border-right: 1px solid #2a3442; }
QFrame#panel { background: #1b232f; border: 1px solid #313c4b; border-radius: 14px; }
QFrame#hero { background: #203038; border: 1px solid #365350; border-radius: 14px; }
QLabel#heading { font-size: 24px; font-weight: 800; color: #f4f8fc; }
QLabel#section { font-size: 16px; font-weight: 700; color: #f4f8fc; }
QLabel#small { color: #95a4b5; font-size: 11px; }
QLabel#muted { color: #a6b3c3; }
QLabel#brand { font-size: 19px; font-weight: 800; color: #f5fafb; }
QLabel#ok { color: #42e6ab; font-weight: 600; }
QLabel#warning { color: #f4c078; }
QPushButton { background: #2c3645; border: 1px solid #475366; border-radius: 9px; padding: 10px 14px; font-weight: 600; color: #f0f4f8; }
QPushButton:hover { background: #37465a; border-color: #698078; }
QPushButton:disabled { background: #232c37; color: #637184; border-color: #354050; }
QPushButton#primary { background: #21b986; color: #071b17; border: 1px solid #45e9ae; }
QPushButton#primary:hover { background: #4bdca8; }
QPushButton#danger { background: #952f42; border: 1px solid #d95568; color: white; }
QPushButton#danger:hover { background: #b84055; }
QPushButton#nav { background: transparent; border: 0; border-radius: 9px; text-align: left; padding: 13px 16px; color: #b4c0ce; }
QPushButton#nav:checked { background: #205148; color: #e1fff0; }
QPushButton#nav:hover { background: #2c3d46; }
QComboBox { background: #171e29; border: 1px solid #536073; border-radius: 9px; padding: 10px 13px; min-height: 19px; }
QComboBox:hover, QComboBox:focus { border-color: #42d7a2; }
QComboBox QAbstractItemView { background: #222c38; color: #f5f8fa; selection-background-color: #275d53; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 19px; height: 19px; }
QCheckBox::indicator:checked { background: #27d49b; border: 1px solid #76f3c8; border-radius: 5px; }
QCheckBox::indicator:unchecked { background: #202c3a; border: 1px solid #637185; border-radius: 5px; }
QProgressBar { background: #111b27; border: 1px solid #3b4b58; border-radius: 6px; color: white; height: 13px; text-align: center; }
QProgressBar::chunk { background: #2fd69e; border-radius: 5px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #19212d; width: 9px; }
QScrollBar::handle:vertical { background: #435364; border-radius: 4px; }
"""
