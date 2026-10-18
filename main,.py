import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
from database.db import init_db

class SmartGuardApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SmartGuard-Vision: Campus Security Gateway")
        self.setGeometry(100, 100, 1280, 720) # Standard desktop resolution
        
        # Initialize Database
        init_db()

        # Central Widget Layout placeholder
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        layout = QVBoxLayout()
        self.label = QLabel("Welcome to SmartGuard-Vision Desktop UI")
        layout.addWidget(self.label)
        self.central_widget.setLayout(layout)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SmartGuardApp()
    window.show()
    sys.exit(app.exec_())