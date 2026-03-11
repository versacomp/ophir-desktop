import os
import ast
import time
import datetime
import re
import shutil
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QMainWindow, QDockWidget, QTextEdit,
    QToolBar, QPushButton, QToolButton, QMenu, QTabWidget, QWidget, QVBoxLayout, QLabel,
    QLineEdit, QComboBox, QMessageBox, QFileDialog, QInputDialog
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QKeySequence, QShortcut
from ui.editor import OphirCodeEditor
from ui.chart import OphirTradeChart
from ui.explorer import OphirFileExplorer
from engine.worker import OphirExecutionEngine
from ui.blotter import OphirOrderBlotter
from ui.dashboard import OphirPerformanceDashboard
from engine.streamer import MarketDataStreamer
from engine.broker import OphirBroker
from collections import deque
from engine.strategy_loader import load_strategy
from engine.database import OphirDatabase

class OphirTradeIDE(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ophir Desktop - Quant Developer IDE")
        self.resize(1400, 900)

        # Execution Lock: 1 = Long, -1 = Short, 0 = Flat
        self.market_position = 0

        # --- THE RISK MANAGER ---
        self.active_trade = None  # Holds the dictionary of the live position

        # --- EXECUTION STATE ---
        self.is_live_mode = False  # True = Connect to Production API
        self.paper_trade = False  # True = Bypass Broker Routing

        self.active_symbol = "SPY"

        # --- Live Data Buffers ---
        # Keep a rolling window of the last 1000 ticks to prevent memory leaks
        self.live_price_buffer = deque(maxlen=1000)
        self.live_time_buffer = deque(maxlen=1000)
        self.tick_count = 0
        self.tick_counter = 0
        self.live_curve = None  # This will hold our specific pyqtgraph line

        self.recent_files = []  # Max 8 entries, most-recent first

        # Per-tab file path registry  {QsciScintilla instance -> absolute path}
        self._tab_paths = {}

        # Apply the unified, high-contrast dark theme across the entire application
        self.setStyleSheet("""
                    QMainWindow { background-color: #16161e; }
                    QDockWidget { color: #aaaaaa; font-weight: bold; }
                    QDockWidget::title { background: #1a1a22; padding: 6px; border-bottom: 1px solid #2d2d30;}
                    QTextEdit, QListWidget, QTreeView { background-color: #101014; color: #cccccc; border: none; }
                    QToolBar { background-color: #1a1a22; border: none; spacing: 10px; padding: 5px; }
                    QTabWidget::pane { border: none; background: #1e1e2e; }
                    QTabBar { background: #13131a; }
                    QTabBar::tab {
                        background: #13131a; color: #6c7086;
                        padding: 5px 16px; min-width: 100px;
                        border-right: 1px solid #1e1e2e;
                    }
                    QTabBar::tab:selected {
                        background: #1e1e2e; color: #cdd6f4;
                        border-top: 2px solid #bd93f9;
                    }
                    QTabBar::tab:hover:!selected { background: #1a1a2e; color: #a6adc8; }
                    QTabBar::close-button {
                        subcontrol-position: right;
                    }
                """)

        # Central Tabbed Editor
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tab_widget)

        # --- INITIALIZE THE SANDBOX (file setup only — no engine load yet) ---
        self._initialize_sandbox()

        # 1. Initialize the Terminal first (so the toolbar can print to it)
        self._build_terminal()

        # 2. Build the rest of the UI
        self._build_market_explorer()
        self._build_chart_dock()

        # 3. Ignite the Command Center
        self._build_top_toolbar()
        self._build_editor_toolbar()

        # Build the Portfolio Matrix UI
        self._build_position_manager()

        # --- Keyboard Shortcuts ---
        self.save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self.save_shortcut.activated.connect(self.save_current_file)

        self.new_shortcut = QShortcut(QKeySequence.StandardKey.New, self)
        self.new_shortcut.activated.connect(self.action_new_file)

        self.open_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        self.open_shortcut.activated.connect(self.action_open_file)

        self.save_as_shortcut = QShortcut(QKeySequence.StandardKey.SaveAs, self)
        self.save_as_shortcut.activated.connect(self.action_save_as)

        # --- ENGINE LOAD: UI is fully built, feedback will now be visible ---
        self.alpha_engine = None
        self._armed_strategy_path = None  # Absolute path of the currently running engine
        if self.current_file_path:
            self._load_active_strategy(self.current_file_path)

        # The Real-Time Candle Builder (Expanded to 250 for the SMA-200 filter)
        self.live_candles = deque(maxlen=250)

        # --- TIME-BASED AGGREGATOR ---
        self.timeframe_minutes = 1  # We can wire this to a UI dropdown later (1, 5, 15)
        self.current_candle_time = None
        self.current_candle = {'open': None, 'high': None, 'low': None, 'close': None, 'volume': 0}

        # Execution Lock: 1 = Long, -1 = Short, 0 = Flat
        self.market_position = 0

    # ------------------------------------------------------------------
    # Properties — delegate to the active tab so the rest of the class
    # can reference self.editor and self.current_file_path unchanged.
    # ------------------------------------------------------------------

    @property
    def editor(self):
        """Returns the QsciScintilla instance in the currently active tab."""
        return self.tab_widget.currentWidget()

    @property
    def current_file_path(self):
        """Returns the file path associated with the active tab."""
        return self._tab_paths.get(self.tab_widget.currentWidget())

    @current_file_path.setter
    def current_file_path(self, value):
        w = self.tab_widget.currentWidget()
        if w is not None:
            self._tab_paths[w] = value

    # ------------------------------------------------------------------

    def _open_in_tab(self, content: str, file_path: str):
        """
        Opens content in a tab. If the file is already open, switches to it.
        Handles editor creation, signal wiring, and tab path registration.
        """
        abs_path = os.path.abspath(file_path)

        # Switch to existing tab if the file is already open
        for i in range(self.tab_widget.count()):
            w = self.tab_widget.widget(i)
            if self._tab_paths.get(w) == abs_path:
                self.tab_widget.setCurrentIndex(i)
                return

        # Create a fresh editor instance for this tab
        ed = OphirCodeEditor()
        ed.blockSignals(True)
        ed.setText(content)
        ed.setModified(False)
        ed.blockSignals(False)
        ed.modificationChanged.connect(self._on_editor_modified)

        fname = os.path.basename(file_path)
        idx = self.tab_widget.addTab(ed, fname)
        self.tab_widget.setTabToolTip(idx, abs_path)
        self.tab_widget.setCurrentIndex(idx)
        self._tab_paths[ed] = abs_path

    def _on_tab_close_requested(self, index: int):
        """Checks for unsaved changes on the closing tab, then removes it."""
        ed = self.tab_widget.widget(index)
        if ed and ed.isModified():
            path = self._tab_paths.get(ed, "")
            fname = os.path.basename(path) if path else "untitled"
            msg = QMessageBox(self)
            msg.setWindowTitle("Unsaved Changes")
            msg.setText(f"<b>{fname}</b> has unsaved changes.")
            msg.setInformativeText("Do you want to save before closing?")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setStandardButtons(
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            msg.setDefaultButton(QMessageBox.StandardButton.Save)
            msg.setStyleSheet("""
                QMessageBox { background-color: #1e1e2e; color: #cdd6f4; }
                QLabel { color: #cdd6f4; font-family: Consolas; }
                QPushButton { background-color: #313244; color: #cdd6f4;
                    border: 1px solid #45475a; padding: 5px 16px; font-family: Consolas; }
                QPushButton:hover { background-color: #45475a; }
                QPushButton:default { border: 1px solid #89b4fa; color: #89b4fa; }
            """)
            result = msg.exec()
            if result == QMessageBox.StandardButton.Cancel:
                return
            if result == QMessageBox.StandardButton.Save:
                # Temporarily activate this tab to save it correctly
                self.tab_widget.setCurrentIndex(index)
                self.save_current_file()

        self._tab_paths.pop(ed, None)
        self.tab_widget.removeTab(index)

    def _on_tab_changed(self, index: int):
        """Updates toolbar labels and re-arms the engine when the active tab changes."""
        if index == -1 or not hasattr(self, 'lbl_current_file'):
            return
        ed = self.tab_widget.widget(index)
        if ed is None:
            return
        path = self._tab_paths.get(ed, "")
        fname = os.path.basename(path) if path else "untitled"
        modified = ed.isModified()
        display = f"  {fname} *" if modified else f"  {fname}"
        colour = "#f1fa8c" if modified else "#6272a4"
        self.lbl_current_file.setText(display)
        self.lbl_current_file.setStyleSheet(
            f"color: {colour}; font-family: Consolas; font-size: 12px; padding: 3px 6px;")
        base = "Ophir Desktop - Quant Developer IDE"
        self.setWindowTitle(f"{base}  —  {fname} *" if modified else f"{base}  —  {fname}")
        if path and hasattr(self, 'alpha_engine'):
            self._load_active_strategy(path)

    def _initialize_sandbox(self):
        """Ensures the sandbox environment is set up and loads the alpha into the editor."""
        sandbox_dir = "./strategies"
        template_path = os.path.join(sandbox_dir, "template_alpha.py")
        alpha_path = os.path.join(sandbox_dir, "alpha.py")

        # 1. Ensure the directory exists
        if not os.path.exists(sandbox_dir):
            os.makedirs(sandbox_dir)

        # 2. Ensure the template exists (in case they clone an empty repo)
        if not os.path.exists(template_path):
            with open(template_path, 'w', encoding='utf-8') as f:
                f.write(
                    'class CustomAlpha:\n'
                    '    """OphirTrade - Blank Alpha Template"""\n'
                    '    def __init__(self):\n'
                    '        self.REQUIRED_BUFFER = 200\n\n'
                    '    def evaluate(self, raw_candles: list, use_trend: bool = True, use_range: bool = True) -> dict:\n'
                    '        """USER: Write your custom quantitative logic here."""\n'
                    '        return {"action": 0, "confidence": 0.0, "direction": "FLAT", "level": 0.0, "type": "NONE"}\n'
                )

        # 3. If the working alpha file doesn't exist, duplicate the template
        if not os.path.exists(alpha_path):
            shutil.copy(template_path, alpha_path)
            print("[SYSTEM] Created new untracked alpha.py from template.")

        # 4. Load the working alpha into a tab
        with open(alpha_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self._open_in_tab(content, alpha_path)

    def _build_market_explorer(self):
        dock = QDockWidget("Market Explorer", self)
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        # Instantiate our new native file explorer
        self.file_explorer = OphirFileExplorer(workspace_dir="./strategies")

        # When the user double clicks a file, catch the signal and load it
        self.file_explorer.file_loaded.connect(self.load_file_to_editor)

        dock.setWidget(self.file_explorer)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        # --- Build the Dashboard Dock ---
        dashboard_dock = QDockWidget("Strategy Performance", self)
        dashboard_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        self.dashboard = OphirPerformanceDashboard()
        dashboard_dock.setWidget(self.dashboard)

        # Snap it directly beneath the file explorer
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dashboard_dock)

    def _load_active_strategy(self, file_path: str):
        """Syntax-checks then dynamically loads the strategy class from the given file."""
        # While a live stream is running, only the currently armed file may be
        # hot-reloaded (e.g. Ctrl+S on the active strategy). Switching to a
        # different file would put the position manager in an undefined state.
        if getattr(self, 'streamer_thread', None) is not None:
            incoming = os.path.abspath(file_path)
            if incoming != self._armed_strategy_path:
                self.append_log(
                    f"[ENGINE] Locked — disconnect the live feed before switching strategies "
                    f"({os.path.basename(file_path)}).")
                return

        fname = os.path.basename(file_path)

        # --- PHASE 1: COMPILE CHECK ---
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            ast.parse(source, filename=fname)
        except SyntaxError as e:
            self.alpha_engine = None
            self.lbl_strategy_name.setText(f"Strategy: SYNTAX ERROR")
            self.lbl_strategy_name.setStyleSheet(
                "color: #ff5555; font-weight: bold; font-family: Consolas; padding: 5px;")
            self.lbl_strategy_name.setToolTip(str(e))
            self.append_error(f"[ENGINE] Syntax error in {fname} — line {e.lineno}: {e.msg}")
            return

        # --- PHASE 2: LOAD & INSTANTIATE ---
        try:
            self.alpha_engine = load_strategy(file_path)
            self._armed_strategy_path = os.path.abspath(file_path)
            strat_name = getattr(self.alpha_engine, 'STRATEGY_NAME', type(self.alpha_engine).__name__)
            strat_desc = getattr(self.alpha_engine, 'STRATEGY_DESCRIPTION', 'No description provided.')
            self.lbl_strategy_name.setText(f"Strategy: {strat_name}")
            self.lbl_strategy_name.setStyleSheet(
                "color: #50fa7b; font-weight: bold; font-family: Consolas; padding: 5px;")
            self.lbl_strategy_name.setToolTip(strat_desc)
            self.append_log(f"[ENGINE] ✓ Strategy armed: {strat_name}")
            self.append_log(f"[ENGINE] {strat_desc}")
        except Exception as e:
            self.alpha_engine = None
            self.lbl_strategy_name.setText("Strategy: LOAD ERROR")
            self.lbl_strategy_name.setStyleSheet(
                "color: #ff5555; font-weight: bold; font-family: Consolas; padding: 5px;")
            self.lbl_strategy_name.setToolTip(str(e))
            self.append_error(f"[ENGINE ERROR] Failed to load {fname}: {e}")

    def load_file_to_editor(self, file_path, content):
        """Triggered by the file explorer double-click."""
        self._open_in_tab(content, file_path)
        self.terminal.append(f"[SYSTEM] Loaded {os.path.basename(file_path)}")
        self._load_active_strategy(file_path)

    def save_current_file(self):
        """Triggered by Ctrl+S or the Save button."""
        if self.current_file_path:
            with open(self.current_file_path, 'w', encoding='utf-8') as f:
                f.write(self.editor.text())
            fname = os.path.basename(self.current_file_path)
            self.editor.setModified(False)
            self.tab_widget.setTabText(self.tab_widget.currentIndex(), fname)
            self._add_to_recent(self.current_file_path)
            self.terminal.append(f"[SYSTEM] Saved {fname}")
            self._load_active_strategy(self.current_file_path)
        else:
            self.action_save_as()

    def _build_chart_dock(self):
        self.dock_chart = QDockWidget(f"Live {self.active_symbol}", self)
        self.dock_chart.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.BottomDockWidgetArea)

        # Make the chart an instance variable so we can feed it data later
        self.chart_widget = OphirTradeChart()

        self.dock_chart.setWidget(self.chart_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_chart)

    def _build_terminal(self):
        # We modify this slightly so we can tab the terminal and blotter together
        self.terminal_dock = QDockWidget("Execution Logs", self)
        self.terminal_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)

        self.terminal = QTextEdit()
        # ... (Keep your terminal setup) ...

        self.terminal_dock.setWidget(self.terminal)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.terminal_dock)

        # --- NEW: Build the Blotter Dock ---
        self.blotter_dock = QDockWidget("Order Blotter", self)
        self.blotter = OphirOrderBlotter()
        self.blotter_dock.setWidget(self.blotter)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.blotter_dock)

        # Stack them on top of each other into tabs (Very PyCharm/VS Code!)
        self.tabifyDockWidget(self.terminal_dock, self.blotter_dock)
        self.blotter_dock.raise_()  # Bring Blotter to the front initially

    def _build_position_manager(self):
        """Constructs the sidebar dock for live account metrics."""
        self.dock_positions = QDockWidget("PORTFOLIO MATRIX", self)
        self.dock_positions.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        container = QWidget()
        layout = QVBoxLayout(container)

        # -- Styling --
        label_style = "color: #f8f8f2; font-family: Consolas; font-size: 14px; padding: 5px;"
        header_style = "color: #bd93f9; font-family: Consolas; font-size: 16px; font-weight: bold; margin-top: 10px;"

        # -- Metrics Labels --
        self.lbl_net_liq = QLabel("Net Liq:        $ --")
        self.lbl_net_liq.setStyleSheet(header_style)

        self.lbl_bp = QLabel("Buying Power:   $ --")
        self.lbl_bp.setStyleSheet(label_style)

        self.lbl_positions = QLabel("Open Inventory:\nFLAT (0 Positions)")
        self.lbl_positions.setStyleSheet(label_style)

        # -- Refresh Button --
        self.btn_refresh_portfolio = QPushButton("⟳ Sync with Exchange")
        self.btn_refresh_portfolio.setStyleSheet(
            "background-color: #44475a; color: #f8f8f2; border: 1px solid #6272a4; padding: 5px;")
        self.btn_refresh_portfolio.clicked.connect(self.refresh_portfolio)

        # Add to layout
        layout.addWidget(self.lbl_net_liq)
        layout.addWidget(self.lbl_bp)
        layout.addWidget(self.lbl_positions)
        layout.addSpacing(20)
        layout.addWidget(self.btn_refresh_portfolio)
        layout.addStretch()  # Pushes everything to the top

        self.dock_positions.setWidget(container)

        # Snap the dock to the right side of the IDE
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_positions)

    def refresh_portfolio(self):
        """Pulls the latest ledger data and updates the UI."""
        if not self.live_broker:
            self.append_log("[SYSTEM] Broker offline. Click 'Connect Live Data Feed' to authenticate first.")
            return

        self.append_log("[SYSTEM] Syncing portfolio ledgers with Wall Street...")
        balances, positions = self.live_broker.get_portfolio_status()

        if isinstance(balances, str):
            self.append_log(f"[PORTFOLIO ERROR] {balances}")
            return

        # 1. Update Account Balances
        if balances:
            # Safely extract the exact Decimal values Tastytrade provides
            net_liq = getattr(balances, 'net_liquidating_value', 0)
            bp = getattr(balances, 'equity_buying_power', 0)

            self.lbl_net_liq.setText(f"Net Liq:        ${float(net_liq):,.5f}")
            self.lbl_bp.setText(f"Buying Power:   ${float(bp):,.5f}")

        # 2. Update Open Positions
        if positions is not None:
            if len(positions) == 0:
                self.lbl_positions.setText("Open Inventory:\n> FLAT (0 Positions)")
            else:
                pos_text = "Open Inventory:\n"
                for p in positions:
                    sym = getattr(p, 'symbol', 'UNKNOWN')
                    qty = getattr(p, 'quantity', 0)
                    pos_text += f"> {sym} : {qty} shares\n"

                self.lbl_positions.setText(pos_text)

        self.append_log("[SYSTEM] Portfolio Sync Complete.")

    def _build_top_toolbar(self):
        """Constructs the main execution toolbar at the top of the IDE."""
        toolbar = QToolBar("Main Execution Toolbar")
        toolbar.setMovable(False)  # Lock it to the top so it doesn't float away
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        # --- Button 1: Run Backtest ---
        btn_backtest = QPushButton("▶️ Run Backtest")
        btn_backtest.setStyleSheet("""
            QPushButton { background-color: #2b5c3a; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #3e8e53; }
        """)
        # Connect the click event to our Python function
        btn_backtest.clicked.connect(self.action_run_backtest)
        toolbar.addWidget(btn_backtest)

        # --- DYNAMIC SYMBOL SELECTOR ---
        lbl_symbol = QLabel("TICKER:")
        lbl_symbol.setStyleSheet("color: #8be9fd; font-weight: bold; font-family: Consolas;")
        toolbar.addWidget(lbl_symbol)

        # 1. CREATE THE TEXT BOX FIRST
        self.txt_symbol = QLineEdit("SPY")  # "SPY" is the default text
        self.txt_symbol.setFixedWidth(80)
        self.txt_symbol.setStyleSheet(
            "background-color: #44475a; "
            "color: #f8f8f2; "
            "border: 1px solid #6272a4; "
            "padding: 5px; "
            "font-weight: bold; "
            "font-family: Consolas;"
        )
        self.txt_symbol.textChanged.connect(lambda text: self.txt_symbol.setText(text.upper()))
        toolbar.addWidget(self.txt_symbol)

        # --- TIMEFRAME DROPDOWN ---
        self.combo_timeframe = QComboBox()
        self.combo_timeframe.addItems(["1 Minute", "5 Minutes", "15 Minutes", "1 Hour"])
        self.combo_timeframe.setStyleSheet(
            "background-color: #2b2b2b; color: #f8f8f2; border: 1px solid #6272a4; padding: 5px;")

        # Add it to your toolbar layout (Example:)
        toolbar.addWidget(self.combo_timeframe)

        # 2. NOW SET THE VARIABLE
        # Because self.txt_symbol exists now, we can safely read it.
        self.active_symbol = self.txt_symbol.text().strip()

        # --- Live Data Toggle ---
        self.btn_live_data = QPushButton("Connect Live Data Feed")
        self.btn_live_data.setStyleSheet("background-color: #2b2b2b; color: #50fa7b; border: 1px solid #50fa7b;")
        self.btn_live_data.clicked.connect(self.toggle_live_stream)
        toolbar.addWidget(self.btn_live_data)

        # Keep track of the streamer state
        self.streamer_thread = None
        self.live_broker = None

        # --- Strategy Name Readout ---
        self.lbl_strategy_name = QLabel("Strategy: --")
        self.lbl_strategy_name.setStyleSheet("color: #ffb86c; font-weight: bold; font-family: Consolas; padding: 5px;")
        toolbar.addWidget(self.lbl_strategy_name)

        # --- AI Telemetry Readout ---
        self.lbl_ai_confidence = QLabel("AI State: Awaiting Data...")
        self.lbl_ai_confidence.setStyleSheet("color: #8be9fd; font-weight: bold; font-family: Consolas; padding: 5px;")
        toolbar.addWidget(self.lbl_ai_confidence)

        # --- Button 2: Deploy Live ---
        btn_live = QPushButton("⚡ Deploy Live")
        btn_live.setStyleSheet("""
            QPushButton { background-color: #007acc; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #0098ff; }
        """)
        btn_live.clicked.connect(self.action_deploy_live)
        toolbar.addWidget(btn_live)

        # Add a visual spacer
        spacer = QWidget()
        spacer.setFixedSize(20, 20)
        toolbar.addWidget(spacer)

        # --- NEW: EMERGENCY HALT BUTTON ---
        self.btn_halt = QPushButton("🛑 HALT ALL")
        self.btn_halt.setStyleSheet(
            "background-color: #ff5555; "
            "color: #ffffff; "
            "font-weight: bold; "
            "border: 2px solid #ff0000; "
            "padding: 5px 15px;"
        )
        self.btn_halt.clicked.connect(self.halt_all_trading)
        toolbar.addWidget(self.btn_halt)

        # --- 3-WAY ENVIRONMENT TOGGLE ---
        self.combo_env = QComboBox()
        self.combo_env.addItems([
            "SANDBOX (Cert Data & Exec)",
            "PAPER (Live Data & Local Exec)",
            "LIVE (Live Data & Real Money)"
        ])
        self.combo_env.setStyleSheet("""
                    QComboBox { background-color: #44475a; color: #f1fa8c; font-weight: bold; border: 1px solid #f1fa8c; padding: 5px; }
                """)
        self.combo_env.currentTextChanged.connect(self._on_env_changed)
        toolbar.addWidget(self.combo_env)

        self.db = OphirDatabase()
        self.append_log("[SYSTEM] SQLite Storage online.")

    def _build_editor_toolbar(self):
        """Constructs a menu-bar style file operations row below the main toolbar."""
        toolbar = QToolBar("Editor Menu Bar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        menu_style = """
            QToolButton {
                background-color: transparent;
                color: #cccccc;
                font-family: Consolas;
                font-size: 12px;
                padding: 3px 12px;
                border: none;
            }
            QToolButton:hover {
                background-color: #2d2d44;
                color: #ffffff;
            }
            QToolButton:pressed, QToolButton[popupMode="2"] {
                background-color: #1a1a2e;
            }
            QMenu {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #313244;
                font-family: Consolas;
                font-size: 12px;
            }
            QMenu::item {
                padding: 5px 28px 5px 20px;
            }
            QMenu::item:selected {
                background-color: #45475a;
                color: #cdd6f4;
            }
            QMenu::item:disabled {
                color: #585b70;
            }
            QMenu::separator {
                height: 1px;
                background: #313244;
                margin: 3px 8px;
            }
            QMenu::right-arrow {
                image: none;
                width: 8px;
            }
        """

        # --- FILE MENU ---
        self.menu_file = QMenu("File", self)
        self.menu_file.setStyleSheet(menu_style)

        act_new = QAction("New File\tCtrl+N", self)
        act_new.triggered.connect(self.action_new_file)

        act_open = QAction("Open File\tCtrl+O", self)
        act_open.triggered.connect(self.action_open_file)

        # Recent Files flyout — populated dynamically on aboutToShow
        self.menu_recent = QMenu("Recent Files", self)
        self.menu_recent.setStyleSheet(menu_style)
        self.menu_recent.aboutToShow.connect(self._populate_recent_menu)

        act_save = QAction("Save\tCtrl+S", self)
        act_save.triggered.connect(self.save_current_file)

        act_save_as = QAction("Save As\tCtrl+Shift+S", self)
        act_save_as.triggered.connect(self.action_save_as)

        self.menu_file.addAction(act_new)
        self.menu_file.addAction(act_open)
        self.menu_file.addMenu(self.menu_recent)
        self.menu_file.addSeparator()
        self.menu_file.addAction(act_save)
        self.menu_file.addAction(act_save_as)

        btn_file = QToolButton()
        btn_file.setText("File")
        btn_file.setMenu(self.menu_file)
        btn_file.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn_file.setStyleSheet(menu_style)
        toolbar.addWidget(btn_file)

        # --- EDIT MENU ---
        menu_edit = QMenu("Edit", self)
        menu_edit.setStyleSheet(menu_style)

        act_undo = QAction("Undo\tCtrl+Z", self)
        act_undo.triggered.connect(lambda: self.editor.undo() if self.editor else None)

        act_redo = QAction("Redo\tCtrl+Y", self)
        act_redo.triggered.connect(lambda: self.editor.redo() if self.editor else None)

        menu_edit.addAction(act_undo)
        menu_edit.addAction(act_redo)

        btn_edit = QToolButton()
        btn_edit.setText("Edit")
        btn_edit.setMenu(menu_edit)
        btn_edit.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn_edit.setStyleSheet(menu_style)
        toolbar.addWidget(btn_edit)

        # --- CURRENT FILE LABEL ---
        toolbar.addSeparator()
        self.lbl_current_file = QLabel("  No file open")
        self.lbl_current_file.setStyleSheet(
            "color: #585b70; font-family: Consolas; font-size: 12px; padding: 3px 6px;")
        toolbar.addWidget(self.lbl_current_file)

    def _populate_recent_menu(self):
        """Rebuilds the Recent Files flyout from the current recent_files list."""
        self.menu_recent.clear()
        if not self.recent_files:
            placeholder = QAction("No recent files", self)
            placeholder.setEnabled(False)
            self.menu_recent.addAction(placeholder)
            return
        for path in self.recent_files:
            action = QAction(os.path.basename(path), self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked, p=path: self._open_recent(p))
            self.menu_recent.addAction(action)

    def _open_recent(self, path: str):
        """Opens a file from the Recent Files list in a new tab."""
        if not os.path.exists(path):
            self.append_error(f"[FILE] File no longer exists: {path}")
            self.recent_files = [p for p in self.recent_files if p != path]
            return
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self._open_in_tab(content, path)
        self.append_log(f"[FILE] Opened: {os.path.basename(path)}")
        self._load_active_strategy(path)

    def _add_to_recent(self, path: str):
        """Pushes a path to the top of the recent files list (max 8, no duplicates)."""
        path = os.path.abspath(path)
        self.recent_files = [p for p in self.recent_files if p != path]
        self.recent_files.insert(0, path)
        self.recent_files = self.recent_files[:8]

    def _on_editor_modified(self, modified: bool):
        """Updates tab title, window title, and file label for the tab that fired the signal."""
        ed = self.sender()
        idx = self.tab_widget.indexOf(ed)
        if idx == -1:
            return

        path = self._tab_paths.get(ed, "")
        fname = os.path.basename(path) if path else "untitled"
        self.tab_widget.setTabText(idx, f"{fname} *" if modified else fname)

        # Only update the window chrome if this is the active tab
        if idx != self.tab_widget.currentIndex():
            return

        base = "Ophir Desktop - Quant Developer IDE"
        if modified:
            self.setWindowTitle(f"{base}  —  {fname} *")
            self.lbl_current_file.setText(f"  {fname} *")
            self.lbl_current_file.setStyleSheet(
                "color: #f1fa8c; font-family: Consolas; font-size: 12px; padding: 3px 6px;")
        else:
            self.setWindowTitle(f"{base}  —  {fname}")
            self.lbl_current_file.setText(f"  {fname}")
            self.lbl_current_file.setStyleSheet(
                "color: #6272a4; font-family: Consolas; font-size: 12px; padding: 3px 6px;")

    def _confirm_discard_changes(self) -> bool:
        """
        If the editor has unsaved changes, shows a blocking Save / Discard / Cancel modal.
        Returns True if it is safe to proceed, False if the user chose Cancel.
        """
        if not self.editor.isModified():
            return True

        fname = os.path.basename(self.current_file_path) if self.current_file_path else "untitled"
        msg = QMessageBox(self)
        msg.setWindowTitle("Unsaved Changes")
        msg.setText(f"<b>{fname}</b> has unsaved changes.")
        msg.setInformativeText("Do you want to save before continuing?")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Save)
        msg.setStyleSheet("""
            QMessageBox { background-color: #1e1e2e; color: #cdd6f4; }
            QLabel { color: #cdd6f4; font-family: Consolas; }
            QPushButton {
                background-color: #313244; color: #cdd6f4;
                border: 1px solid #45475a; padding: 5px 16px;
                font-family: Consolas;
            }
            QPushButton:hover { background-color: #45475a; }
            QPushButton:default { border: 1px solid #89b4fa; color: #89b4fa; }
        """)

        result = msg.exec()

        if result == QMessageBox.StandardButton.Save:
            self.save_current_file()
            return True
        elif result == QMessageBox.StandardButton.Discard:
            self.editor.setModified(False)
            return True
        else:  # Cancel
            return False

    def closeEvent(self, event):
        """Intercepts the window close and checks for unsaved changes first."""
        if self._confirm_discard_changes():
            event.accept()
        else:
            event.ignore()

    def action_new_file(self):
        """Prompts for a filename, creates it from the template, and opens it in the editor."""
        if not self._confirm_discard_changes():
            return

        name, ok = QInputDialog.getText(self, "New Strategy File", "File name (without .py):")
        if not ok or not name.strip():
            return

        name = name.strip()
        if not name.endswith(".py"):
            name += ".py"

        new_path = os.path.join("./strategies", name)

        if os.path.exists(new_path):
            self.append_error(f"[FILE] '{name}' already exists. Open it from the explorer.")
            return

        template_path = os.path.join("./strategies", "template_alpha.py")
        if os.path.exists(template_path):
            shutil.copy(template_path, new_path)
        else:
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write("class CustomAlpha:\n    STRATEGY_NAME = \"Custom Alpha\"\n"
                        "    STRATEGY_DESCRIPTION = \"Describe your strategy here.\"\n\n"
                        "    def __init__(self):\n        self.REQUIRED_BUFFER = 200\n\n"
                        "    def evaluate(self, raw_candles: list, **kwargs) -> dict:\n"
                        "        return {\"action\": 0, \"confidence\": 0.0, "
                        "\"direction\": \"FLAT\", \"level\": 0.0, \"type\": \"NONE\"}\n")

        with open(new_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.current_file_path = new_path
        self.editor.blockSignals(True)
        self.editor.setText(content)
        self.editor.setModified(False)
        self.editor.blockSignals(False)
        self._add_to_recent(new_path)
        self.append_log(f"[FILE] Created new strategy file: {name}")
        self._load_active_strategy(new_path)

    def action_open_file(self):
        """Opens a file picker and loads the selected .py file into the editor."""
        if not self._confirm_discard_changes():
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Open Strategy File",
            os.path.abspath("./strategies"),
            "Python Files (*.py)"
        )
        if not path:
            return

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.current_file_path = path
        self.editor.blockSignals(True)
        self.editor.setText(content)
        self.editor.setModified(False)
        self.editor.blockSignals(False)
        self._add_to_recent(path)
        self.append_log(f"[FILE] Opened: {os.path.basename(path)}")
        self._load_active_strategy(path)

    def action_save_as(self):
        """Saves the current editor content to a new file path."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Strategy As",
            os.path.abspath("./strategies"),
            "Python Files (*.py)"
        )
        if not path:
            return

        if not path.endswith(".py"):
            path += ".py"

        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.editor.text())

        self.current_file_path = path
        self.editor.setModified(False)
        self._add_to_recent(path)
        self.append_log(f"[FILE] Saved as: {os.path.basename(path)}")
        self._load_active_strategy(path)

    def halt_all_trading(self):
        """The Master Kill Switch: Severs data, stops the AI, and flattens all positions."""
        self.append_log("\n[EMERGENCY] =========================================")
        self.append_log("[EMERGENCY] HALT ALL PROTOCOL INITIATED.")

        # 1. SEVER THE DATA FIREHOSE
        if self.streamer_thread and self.streamer_thread.isRunning():
            self.streamer_thread.stop()
            self.streamer_thread.wait()
            self.streamer_thread = None
            self.txt_symbol.setEnabled(True)  # Unlock the text box

            # Reset the Live Data button UI
            self.btn_live_data.setText("Connect Live Data Feed")
            self.btn_live_data.setStyleSheet("background-color: #2b2b2b; color: #50fa7b; border: 1px solid #50fa7b;")
            self.append_log("[EMERGENCY] WebSocket data stream severed. AI is blind.")

            # Update the AI label
            self.lbl_ai_confidence.setText("AI State: SYSTEM HALTED")
            self.lbl_ai_confidence.setStyleSheet(
                "color: #ff5555; font-weight: bold; font-family: Consolas; padding: 5px;")

        # 2. FLATTEN THE MARKET POSITION
        target_symbol = self.active_symbol

        if self.market_position == 1:
            self.append_log(f"[EMERGENCY] Liquidating LONG position on {target_symbol}...")
            if self.live_broker:
                try:
                    # Fire a Market SELL order to close out the 1 share
                    response = self.live_broker.route_order(symbol=target_symbol, side="SELL", qty=1, price=None)
                    self.append_log(f"[BROKER] {response}")
                except Exception as e:
                    self.append_log(f"[BROKER FATAL] Failed to route liquidation order: {str(e)}")

            self.market_position = 0

        elif self.market_position == 0:
            self.append_log("[EMERGENCY] Market position is currently FLAT. No liquidation required.")

        self.append_log("[EMERGENCY] =========================================\n")

    # --- The Action Slots (Where the magic will happen) ---

    def action_run_backtest(self):
        if hasattr(self, 'engine_thread') and self.engine_thread.isRunning():
            self.terminal.append("[WARN] Engine is already running a backtest!")
            return

        self.terminal.append("\n" + "=" * 40)
        self.terminal.append("[SYSTEM] Initiating Background Execution...")

        raw_code = self.editor.text()
        self.engine_thread = OphirExecutionEngine(raw_code)

        self.engine_thread.log_signal.connect(self.append_log)
        self.engine_thread.error_signal.connect(self.append_error)
        self.engine_thread.finished_signal.connect(self.on_execution_finished)
        self.engine_thread.data_ready_signal.connect(self.chart_widget.set_real_data)

        # --- Connect the Blotter Signal ---
        self.engine_thread.order_signal.connect(self.blotter.add_order)

        # --- Connect the Indicator Signal ---
        self.engine_thread.indicator_signal.connect(self.chart_widget.add_indicator)

        # --- Connect the Stats Signal ---
        self.engine_thread.stats_signal.connect(self.dashboard.update_stats)

        self.engine_thread.start()

    def action_deploy_live(self):
        self.terminal.append("\n[WARNING] Waking Live Citadel Agent!")
        self.terminal.append("[NETWORK] Connecting to tastytrade WebSocket...")
        self.terminal.append("[SYSTEM] Awaiting market ticks...")

    def action_halt_execution(self):
        self.terminal.append("\n[KILL SWITCH] 🛑 EXECUTION HALTED.")
        self.terminal.append("[SYSTEM] Flattening all open positions.")
        self.terminal.append("[SYSTEM] Disconnected from brokerage.")

    def append_log(self, text):
        self.terminal.append(f"> {text}")

    def append_error(self, text):
        # Print errors in red
        self.terminal.append(f"<span style='color: #f23645;'>{text}</span>")

    def on_execution_finished(self):
        self.terminal.append("[SYSTEM] Background execution terminated gracefully.")
        self.terminal.append("=" * 40 + "\n")

    def toggle_live_stream(self):
        # Block connection if no strategy is armed
        if getattr(self, 'streamer_thread', None) is None and self.alpha_engine is None:
            self.append_error("[ENGINE] Cannot connect — no strategy loaded. Open a strategy file and save it first.")
            return

        # Check if the object exists, completely ignoring its .isRunning() state
        if getattr(self, 'streamer_thread', None) is not None:
            # Disconnect
            self.append_log("[SYSTEM] Initiating streamer shutdown sequence...")
            self.streamer_thread.stop()

            # Give the thread 1 second to exit gracefully.
            # If it refuses because it is blocked by network I/O, execute it.
            if not self.streamer_thread.wait(1000):
                self.append_log("[SYSTEM] Network thread unresponsive. Forcing termination.")
                self.streamer_thread.terminate()  # Brutally sever the C++ wrapper
                self.streamer_thread.wait()  # Confirm the kill

            self.streamer_thread = None
            self.btn_live_data.setText("Connect Live Data Feed")
            self.btn_live_data.setStyleSheet("background-color: #2b2b2b; color: #50fa7b; border: 1px solid #50fa7b;")
            self.txt_symbol.setEnabled(True)  # Unlock the text box
            self.combo_timeframe.setEnabled(True) # Unlock the timeframe combobox
            self.append_log("[SYSTEM] Live WebSocket feed severed successfully.")
        else:
            # Connect
            self.append_log("[SYSTEM] Initializing secure OAuth session for live data...")
            self.btn_live_data.setText("Connecting...")
            self.btn_live_data.setStyleSheet("background-color: #f1fa8c; color: #282a36;")

            # We initialize the broker purely to grab the authenticated session
            try:
                # --- PREPARE THE CHART FOR LIVE DATA ---
                # Clear any existing backtest candlesticks
                # 1. Grab the active symbol from the UI
                raw_symbol = self.txt_symbol.text().strip().upper()
                tf_text = self.combo_timeframe.currentText()

                if not raw_symbol:
                    self.append_error("[SYSTEM] Ticker symbol cannot be empty.")
                    return

                # --- NEW: AUTO-FORMAT FUTURES SYMBOLS ---
                # If it looks like a future (e.g. MESH6) and doesn't have a slash, add it
                if re.match(r'^[A-Z]+[FGHJKMNQUVXZ]\d{1,2}$', raw_symbol) and not raw_symbol.startswith('/'):
                    self.active_symbol = f"/{raw_symbol}"
                    self.txt_symbol.setText(self.active_symbol)  # Update the UI visually
                    self.append_log(f"[SYSTEM] Auto-formatted futures contract to {self.active_symbol}")
                else:
                    self.active_symbol = raw_symbol
                # ----------------------------------------

                if not self.active_symbol:
                    self.append_error("[SYSTEM] Ticker symbol cannot be empty.")
                    return

                # Map UI Text to Engine Variables
                if tf_text == "1 Minute":
                    self.timeframe_minutes = 1
                    yf_interval = '1m'
                elif tf_text == "5 Minutes":
                    self.timeframe_minutes = 5
                    yf_interval = '5m'
                elif tf_text == "15 Minutes":
                    self.timeframe_minutes = 15
                    yf_interval = '15m'
                elif tf_text == "1 Hour":
                    self.timeframe_minutes = 60
                    yf_interval = '1h'

                # Lock the UI inputs
                self.txt_symbol.setEnabled(False)
                self.combo_timeframe.setEnabled(False)

                # Inject the dynamic UI state into the networking engines
                self.live_broker = OphirBroker(is_live=self.is_live_mode)

                # 2. Lock the input box so the user can't change it mid-stream
                self.txt_symbol.setEnabled(False)

                # --- UPDATE THE UI TITLES ---
                # Update the Dock Widget Title
                # (Note: Change 'self.dock_chart' to whatever you actually named your chart dock variable!)
                if hasattr(self, 'dock_chart'):
                    self.dock_chart.setWindowTitle(f"MARKET MATRIX: {self.active_symbol}")

                # Update the pyqtgraph internal title (if you want the text directly on the grid)
                if hasattr(self.chart_widget, 'graph'):
                    self.chart_widget.plot_widget.setTitle(
                        f"<span style='color: #8be9fd; font-size: 14pt;'>{self.active_symbol} Live Tape</span>")
                # ---------------------------------

                # Create the live line with a vibrant Neon Blue/Purple
                live_pen = pg.mkPen(color='#bd93f9', width=2.5)

                # Use your custom wrapper methods (Optional: update your create_live_line to take a name!)
                self.chart_widget.clear_chart()
                self.live_curve = self.chart_widget.create_live_line(pen=live_pen, name=f"Live {self.active_symbol}")

                # --- NEW: VISUAL OVERLAYS ---
                # 1. The SMA 200 Line (Golden)
                self.sma_curve = self.chart_widget.plot_widget.plot(
                    pen=pg.mkPen('#f1fa8c', width=2, style=Qt.PenStyle.DashLine))

                # 2. Execution Markers (Scatter Plots)
                # symbol 't1' is an Up-Arrow, 't' is a Down-Arrow
                self.buy_scatter = pg.ScatterPlotItem(symbol='t1', size=14, brush='#50fa7b', pen='w')
                self.sell_scatter = pg.ScatterPlotItem(symbol='t', size=14, brush='#ff5555', pen='w')

                self.chart_widget.plot_widget.addItem(self.buy_scatter)
                self.chart_widget.plot_widget.addItem(self.sell_scatter)

                # Memory arrays for the markers
                self.buy_x, self.buy_y = [], []
                self.sell_x, self.sell_y = [], []
                self.sma_data = []
                # ---------------------------------------

                # Reset the memory buffers
                self.live_price_buffer.clear()
                self.live_time_buffer.clear()
                self.tick_count = 0
                # ---------------------------------------

                # Start the background firehose, locked onto the S&P 500 ETF
                # Pass the authenticated live session directly to the data firehose
                self.streamer_thread = MarketDataStreamer(
                    symbol=self.active_symbol,
                    is_live=self.is_live_mode
                )
                self.streamer_thread.tick_signal.connect(self.process_live_tick)
                self.streamer_thread.error_signal.connect(self.append_error)
                self.streamer_thread.start()

                self.btn_live_data.setText("Disconnect Live Feed")
                self.btn_live_data.setStyleSheet(
                    "background-color: #ff5555; color: #f8f8f2; border: 1px solid #ff5555;")
            except Exception as e:
                self.append_error(f"[NETWORK ERROR] Failed to authenticate stream: {str(e)}")

    def process_live_tick(self, data):
        # 1. Handle Status Messages
        if data.get("type") == "status":
            self.append_log(data["msg"])
            return

        # 2. Handle Historical Seed Payload
        if data.get("type") == "history":
            self.live_candles.clear()
            for c in data["data"]:
                self.live_candles.append(c)
            self.append_log(
                f"[SYSTEM] DXLink Seeder perfectly aligned {len(self.live_candles)} native candles. Engine ARMED.")
            return

        # 3. Handle Live Ticks (Your existing code starts here...)
        if data.get("type") == "tick":
            event = data.get('event_type')

            if event == 'Quote':
                bid = data.get('bid')
                ask = data.get('ask')
                symbol = data.get('symbol')

                if bid and ask:
                    mid_price = float(bid + ask) / 2.0

                    # --- 1. LIVE RISK MANAGER EVALUATION ---
                    if self.active_trade is not None:
                        t = self.active_trade
                        tp_dist = abs(t['tp'] - t['entry_price'])

                        if t['direction'] == 'LONG':
                            # Update Peak & Ratcheting Stop
                            if mid_price > t['peak']: t['peak'] = mid_price
                            progress = t['peak'] - t['entry_price']

                            # Trail Stop Trigger
                            if progress >= 0.75 * tp_dist:
                                trail_sl = t['peak'] - (t['risk'] * 0.50)
                                if trail_sl > t['sl']:
                                    t['sl'] = trail_sl
                                    t['stage'] = 2
                            # Breakeven Trigger
                            elif progress >= 0.50 * tp_dist and t['stage'] < 1:
                                t['sl'] = t['entry_price']
                                t['stage'] = 1

                            # Exit Conditions
                            if mid_price <= t['sl'] or mid_price >= t['tp']:
                                if mid_price >= t['tp']:
                                    status = "WIN"
                                elif t['sl'] == t['entry_price']:
                                    status = "SCRATCH"
                                else:
                                    status = "LOSS"

                                pnl = t['tp'] - t['entry_price'] if status == "WIN" else t['sl'] - t['entry_price']
                                exit_price = t['tp'] if status == "WIN" else t['sl']
                                self._close_active_trade(exit_price, pnl, status)

                        elif t['direction'] == 'SHORT':
                            # Update Peak & Ratcheting Stop
                            if mid_price < t['peak']: t['peak'] = mid_price
                            progress = t['entry_price'] - t['peak']

                            # Trail Stop Trigger
                            if progress >= 0.75 * tp_dist:
                                trail_sl = t['peak'] + (t['risk'] * 0.50)
                                if trail_sl < t['sl']:
                                    t['sl'] = trail_sl
                                    t['stage'] = 2
                            # Breakeven Trigger
                            elif progress >= 0.50 * tp_dist and t['stage'] < 1:
                                t['sl'] = t['entry_price']
                                t['stage'] = 1

                            # Exit Conditions
                            if mid_price >= t['sl'] or mid_price <= t['tp']:
                                if mid_price <= t['tp']:
                                    status = "WIN"
                                elif t['sl'] == t['entry_price']:
                                    status = "SCRATCH"
                                else:
                                    status = "LOSS"

                                pnl = t['entry_price'] - t['tp'] if status == "WIN" else t['entry_price'] - t['sl']
                                exit_price = t['tp'] if status == "WIN" else t['sl']
                                self._close_active_trade(exit_price, pnl, status)
                    # ---------------------------------------

                    self.tick_count += 1
                    self.live_time_buffer.append(self.tick_count)
                    self.live_price_buffer.append(mid_price)

                    if self.live_curve:
                        self.live_curve.setData(
                            x=list(self.live_time_buffer),
                            y=list(self.live_price_buffer)
                        )

                    if self.tick_count % 25 == 0:
                        self.append_log(f"[LIVE MARKET] {symbol} | MID: {mid_price:.5f}")

                    # --- 1. BUILD THE OHLCV CANDLE ---
                    if self.current_candle['open'] is None:
                        self.current_candle['open'] = mid_price
                        self.current_candle['high'] = mid_price
                        self.current_candle['low'] = mid_price

                    self.current_candle['high'] = max(self.current_candle['high'], mid_price)
                    self.current_candle['low'] = min(self.current_candle['low'], mid_price)
                    self.current_candle['close'] = mid_price
                    self.current_candle['volume'] += 1

                    self.tick_counter += 1

                    # --- 2. TIME-BASED CANDLE AGGREGATOR ---
                    now = datetime.datetime.now()

                    # Floor the time to the nearest timeframe interval
                    minute_floored = (now.minute // self.timeframe_minutes) * self.timeframe_minutes
                    interval_time = now.replace(minute=minute_floored, second=0, microsecond=0)

                    if self.current_candle_time is None:
                        # First tick initializes the clock
                        self.current_candle_time = interval_time
                        self.current_candle['open'] = mid_price
                        self.current_candle['high'] = mid_price
                        self.current_candle['low'] = mid_price
                        self.current_candle['close'] = mid_price

                    if interval_time > self.current_candle_time:
                        # THE MINUTE HAS ROLLED OVER. SEAL THE CANDLE.
                        sealed_candle = self.current_candle.copy()
                        self.live_candles.append(sealed_candle)

                        # Log to the SQLite database
                        self.db.insert_candle(symbol, sealed_candle, self.current_candle_time.timestamp())

                        # Trigger the Engine (if loaded and warmed up)
                        if self.alpha_engine is None:
                            self.lbl_ai_confidence.setText("Engine: No strategy loaded")
                            self.lbl_ai_confidence.setStyleSheet("color: #ff5555; font-weight: bold; padding: 5px;")
                        else:
                            required = getattr(self.alpha_engine, 'REQUIRED_BUFFER', 200)
                            if len(self.live_candles) >= required:
                                intent = self.alpha_engine.evaluate(
                                    raw_candles=list(self.live_candles)
                                )
                                action_val = intent["action"]
                                strat_type = intent.get("type", "NONE")

                                if action_val == 0:
                                    self.lbl_ai_confidence.setText(f"Engine ({self.timeframe_minutes}m): SCANNING...")
                                    self.lbl_ai_confidence.setStyleSheet("color: #8be9fd; font-weight: bold; padding: 5px;")
                                elif action_val == 1:
                                    self.lbl_ai_confidence.setText(f"Engine: {strat_type} BULL @ {intent['level']:.5f}")
                                    self.lbl_ai_confidence.setStyleSheet("color: #50fa7b; font-weight: bold; padding: 5px;")
                                elif action_val == 2:
                                    self.lbl_ai_confidence.setText(f"Engine: {strat_type} BEAR @ {intent['level']:.5f}")
                                    self.lbl_ai_confidence.setStyleSheet("color: #ff5555; font-weight: bold; padding: 5px;")

                                self._process_quant_action(intent, symbol, mid_price)
                            else:
                                candles_needed = required - len(self.live_candles)
                                self.lbl_ai_confidence.setText(
                                    f"Engine: WARMING UP ({candles_needed} candles remaining)")
                                self.lbl_ai_confidence.setStyleSheet("color: #f1fa8c; font-weight: bold; padding: 5px;")

                        # RESET FOR THE NEW INTERVAL
                        self.current_candle = {
                            'open': mid_price, 'high': mid_price, 'low': mid_price, 'close': mid_price, 'volume': 0
                        }
                        self.current_candle_time = interval_time
                    else:
                        # WE ARE STILL IN THE CURRENT MINUTE. UPDATE THE ACTIVE CANDLE.
                        if self.current_candle['open'] is None:
                            self.current_candle['open'] = mid_price

                        self.current_candle['close'] = mid_price
                        if mid_price > (self.current_candle['high'] or mid_price):
                            self.current_candle['high'] = mid_price
                        if mid_price < (self.current_candle['low'] or mid_price):
                            self.current_candle['low'] = mid_price
                    # ---------------------------------------

    def _process_quant_action(self, intent: dict, symbol: str, current_price: float):
        """Translates Alpha signals into strict risk-managed orders based on strategy type."""

        action = intent.get("action", 0)
        strat_type = intent.get("type", "NONE")
        current_x = self.tick_count

        if self.active_trade is not None or action == 0:
            return

        signal_candle = self.live_candles[-1]

        # DYNAMIC RISK MULTIPLIERS
        # Swings get a wider 1:2 R:R target. Scalps get a rapid 1:1 R:R target.
        reward_multiplier = 2.0 if strat_type == "SWING" else 1.0

        if action == 1 and self.market_position == 0:
            self.append_log(f"[QUANT GHOST] {strat_type} BULL setup detected on {symbol}. Initiating LONG sequence.")

            self.buy_x.append(current_x)
            self.buy_y.append(current_price)
            self.buy_scatter.setData(self.buy_x, self.buy_y)

            sl = signal_candle['low']
            risk = current_price - sl

            min_variance = 0.005
            if risk < min_variance:
                risk = min_variance
                sl = current_price - risk

            tp = current_price + (risk * reward_multiplier)

            self.active_trade = {
                'symbol': symbol, 'direction': 'LONG', 'entry_price': current_price,
                'sl': sl, 'tp': tp, 'risk': risk, 'stage': 0, 'peak': current_price,
                'entry_time': time.time(), 'strategy': strat_type
            }

            if self.live_broker:
                if self.paper_trade:
                    self.append_log(f"[PAPER] Simulated BUY order locked locally. Wall Street bypassed.")
                else:
                    response = self.live_broker.route_order(symbol, "BUY", 1)
                    self.market_position = 1
                    self.append_log(f"[RISK MGR] LONG {symbol} | Entry: {current_price:.5f} | SL: {sl:.5f} | TP: {tp:.5f}")
                    self.append_log(f"[BROKER] {response}")

        elif action == 2 and self.market_position == 0:
            self.append_log(f"[QUANT GHOST] {strat_type} BEAR setup detected on {symbol}. Initiating SHORT sequence.")

            self.sell_x.append(current_x)
            self.sell_y.append(current_price)
            self.sell_scatter.setData(self.sell_x, self.sell_y)

            sl = signal_candle['high']
            risk = sl - current_price

            min_variance = 0.005
            if risk < min_variance:
                risk = min_variance
                sl = current_price + risk

            tp = current_price - (risk * reward_multiplier)

            self.active_trade = {
                'symbol': symbol, 'direction': 'SHORT', 'entry_price': current_price,
                'sl': sl, 'tp': tp, 'risk': risk, 'stage': 0, 'peak': current_price,
                'entry_time': time.time(), 'strategy': strat_type
            }

            if self.live_broker:
                if self.paper_trade:
                    self.append_log(f"[PAPER] Simulated SELL_SHORT order locked locally. Wall Street bypassed.")
                else:
                    response = self.live_broker.route_order(symbol, "SELL_SHORT", 1)
                    self.market_position = -1
                    self.append_log(f"[RISK MGR] SHORT {symbol} | Entry: {current_price:.5f} | SL: {sl:.5f} | TP: {tp:.5f}")
                    self.append_log(f"[BROKER] {response}")

    def _on_env_changed(self, text):
        """Safety interlock for Data and Execution environments."""
        if "LIVE (Live Data" in text:
            # STATE 3: FULL PRODUCTION (DANGER)
            reply = QMessageBox.warning(
                self,
                "DANGER: LIVE TRADING ARMED",
                "You are switching the execution engine to FULL LIVE mode.\n\n"
                "The Alpha Engine will now trade REAL CAPITAL on the production Tastytrade servers.\n\n"
                "Are you absolutely sure you want to proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.No:
                self.combo_env.blockSignals(True)
                self.combo_env.setCurrentIndex(1)  # Default back to safe Paper mode
                self.combo_env.blockSignals(False)
                return

            self.is_live_mode = True
            self.paper_trade = False
            self.combo_env.setStyleSheet(
                "QComboBox { background-color: #ff5555; color: #ffffff; font-weight: bold; border: 2px solid #ff5555; padding: 5px; }")
            self.append_log("[EMERGENCY] WARNING: LIVE MONEY TRADING ARMED. PRODUCTION CLEARINGHOUSE ACTIVE.")

        elif "PAPER" in text:
            # STATE 2: PRODUCTION DATA + LOCAL PAPER EXECUTION (SAFE)
            self.is_live_mode = True
            self.paper_trade = True
            # Style it a cool blue to indicate active data but safe execution
            self.combo_env.setStyleSheet(
                "QComboBox { background-color: #8be9fd; color: #282a36; font-weight: bold; border: 2px solid #8be9fd; padding: 5px; }")
            self.append_log("[SYSTEM] Data switched to Production. Execution bypassed (Paper Mode Active).")

        else:
            # STATE 1: CERT DATA + CERT EXECUTION (SAFE)
            self.is_live_mode = False
            self.paper_trade = False
            self.combo_env.setStyleSheet(
                "QComboBox { background-color: #44475a; color: #f1fa8c; font-weight: bold; border: 1px solid #f1fa8c; padding: 5px; }")
            self.append_log("[SYSTEM] Matrix reverted to secure Sandbox Simulation.")

    def _close_active_trade(self, exit_price: float, pnl: float, status: str):
        """Flattens the position and records the financial outcome to SQLite."""
        t = self.active_trade
        t['exit_price'] = exit_price
        t['pnl'] = pnl
        t['status'] = status
        t['exit_time'] = time.time()

        current_x = self.tick_count

        if t['direction'] == 'LONG':
            # Closing a Long is a Sell (Red Down Arrow)
            self.sell_x.append(current_x)
            self.sell_y.append(exit_price)
            self.sell_scatter.setData(self.sell_x, self.sell_y)
        else:
            # Closing a Short is a Buy (Green Up Arrow)
            self.buy_x.append(current_x)
            self.buy_y.append(exit_price)
            self.buy_scatter.setData(self.buy_x, self.buy_y)

        # Fire closing order to the clearinghouse
        if self.live_broker:
            # To close a Long, we SELL. To close a Short, we BUY_TO_COVER.
            action = "SELL" if t['direction'] == 'LONG' else "BUY_TO_COVER"

            if self.paper_trade:
                self.append_log(f"[PAPER FLATTEN] Simulated {action} order filled locally. Wall Street bypassed.")
            else:
                response = self.live_broker.route_order(t['symbol'], action, 1)
                self.append_log(f"[BROKER FLATTEN] {response}")

        # Log to Database
        self.db.log_closed_trade(t)

        self.append_log(f"[RISK MGR] Trade Closed: {status} | P&L: {pnl:.5f} pts | Exit: {exit_price:.5f}")

        # Reset state
        self.active_trade = None
        self.market_position = 0