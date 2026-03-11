import os
import shutil
from PyQt6.QtWidgets import QTreeView, QMenu, QInputDialog, QMessageBox
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtCore import pyqtSignal, Qt


class OphirFileExplorer(QTreeView):
    """
    A native OS file explorer docked into the IDE.
    Emits a signal containing the file's text when double-clicked.
    """
    file_loaded = pyqtSignal(str, str)
    # Emitted when a file/folder is deleted so the main window can close open tabs
    path_deleted = pyqtSignal(str)

    def __init__(self, workspace_dir="./strategies"):
        super().__init__()

        # 1. Ensure the workspace directory exists on the hard drive
        self.workspace_dir = workspace_dir
        if not os.path.exists(self.workspace_dir):
            os.makedirs(self.workspace_dir)

        # 2. Hook into the Operating System
        self.model = QFileSystemModel()
        self.model.setRootPath(self.workspace_dir)

        # 3. Configure the Tree View
        self.setModel(self.model)
        self.setRootIndex(self.model.index(self.workspace_dir))

        # Hide the size, type, and date columns for a cleaner, VS Code-style look
        for col in range(1, 4):
            self.setColumnHidden(col, True)
        self.setHeaderHidden(True)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        # 4. Wire up the double-click event
        self.doubleClicked.connect(self._on_double_click)

    def update_workspace(self, new_dir: str):
        """Refreshes the tree view to point at a new workspace directory."""
        self.workspace_dir = new_dir
        if not os.path.exists(new_dir):
            os.makedirs(new_dir)
        self.model.setRootPath(new_dir)
        self.setRootIndex(self.model.index(new_dir))

    # ------------------------------------------------------------------
    # Public helpers (called by main window for File menu actions)
    # ------------------------------------------------------------------

    def action_new_folder(self):
        """Prompts for a folder name and creates it inside the selected directory."""
        parent_dir = self._get_selected_dir()
        name, ok = QInputDialog.getText(None, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        new_path = os.path.join(parent_dir, name.strip())
        try:
            os.makedirs(new_path, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(None, "Error", f"Could not create folder:\n{e}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_selected_dir(self) -> str:
        """Returns the directory of the currently selected item, or the workspace root."""
        indexes = self.selectedIndexes()
        if indexes:
            path = self.model.filePath(indexes[0])
            return path if os.path.isdir(path) else os.path.dirname(path)
        return self.workspace_dir

    def _on_context_menu(self, pos):
        index = self.indexAt(pos)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1e1e2e; color: #cdd6f4; border: 1px solid #313244; }
            QMenu::item:selected { background-color: #313244; }
            QMenu::separator { background-color: #313244; height: 1px; margin: 2px 0; }
        """)

        act_new_folder = menu.addAction("New Folder")
        act_new_file = menu.addAction("New File")

        if index.isValid():
            menu.addSeparator()
            act_delete = menu.addAction("Delete")
        else:
            act_delete = None

        action = menu.exec(self.viewport().mapToGlobal(pos))

        if action == act_new_folder:
            self.action_new_folder()
        elif action == act_new_file:
            self._action_new_file()
        elif act_delete and action == act_delete:
            self._action_delete(index)

    def _action_new_file(self):
        """Creates a new .py file in the selected directory."""
        parent_dir = self._get_selected_dir()
        name, ok = QInputDialog.getText(None, "New File", "File name (without .py):")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not name.endswith(".py"):
            name += ".py"
        new_path = os.path.join(parent_dir, name)
        if os.path.exists(new_path):
            QMessageBox.warning(None, "File Exists", f"{name} already exists.")
            return
        try:
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write(
                    'class CustomAlpha:\n'
                    '    """OphirTrade - Blank Alpha Template"""\n'
                    '    def __init__(self):\n'
                    '        self.REQUIRED_BUFFER = 200\n\n'
                    '    def evaluate(self, raw_candles: list, **kwargs) -> dict:\n'
                    '        return {"action": 0, "confidence": 0.0, "direction": "FLAT", "level": 0.0, "type": "NONE"}\n'
                )
            # Load the new file into the editor
            with open(new_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.file_loaded.emit(new_path, content)
        except OSError as e:
            QMessageBox.critical(None, "Error", f"Could not create file:\n{e}")

    def _action_delete(self, index):
        """Confirms then deletes the selected file or folder."""
        path = self.model.filePath(index)
        name = os.path.basename(path)
        is_dir = os.path.isdir(path)
        kind = "folder and all its contents" if is_dir else "file"

        msg = QMessageBox()
        msg.setWindowTitle("Confirm Delete")
        msg.setText(f"Delete {kind} <b>{name}</b>?")
        msg.setInformativeText("This cannot be undone.")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        msg.setStyleSheet("""
            QMessageBox { background-color: #1e1e2e; color: #cdd6f4; }
            QLabel { color: #cdd6f4; font-family: Consolas; }
            QPushButton { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; padding: 5px 16px; }
            QPushButton:hover { background-color: #45475a; }
            QPushButton[text="Yes"] { color: #f38ba8; border-color: #f38ba8; }
        """)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        try:
            if is_dir:
                # Emit delete signal for every file inside so open tabs can be closed
                for root, _, files in os.walk(path):
                    for fname in files:
                        self.path_deleted.emit(os.path.join(root, fname))
                shutil.rmtree(path)
            else:
                self.path_deleted.emit(path)
                os.remove(path)
        except OSError as e:
            QMessageBox.critical(None, "Error", f"Could not delete {name}:\n{e}")

    def _on_double_click(self, index):
        """Fires when the user double-clicks a file in the dock."""
        file_path = self.model.filePath(index)

        # Only open Python files to prevent crashing the editor with binary data
        if os.path.isfile(file_path) and file_path.endswith('.py'):
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Emit the data up to the main window
            self.file_loaded.emit(file_path, content)
