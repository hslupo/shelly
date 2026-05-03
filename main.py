"""Shelly Desktop-App – Hauptfenster mit PyQt6."""

import json
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QMessageBox,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from shelly_api import ShellyStatus, discover_devices, fetch_device

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "devices": [
        {"name": "Steckdose 1", "ip": "192.168.1.100", "gen": None},
        {"name": "Steckdose 2", "ip": "192.168.1.101", "gen": None},
    ],
    "refresh_interval": 10,
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Geräte-Karte
# ---------------------------------------------------------------------------

class DeviceCard(QGroupBox):
    """Zeigt Status-Daten eines einzelnen Shelly-Geräts."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._build_ui()

    def _build_ui(self):
        layout = QGridLayout(self)
        layout.setSpacing(6)

        def make_label(text="—", bold=False) -> QLabel:
            lbl = QLabel(text)
            if bold:
                f = lbl.font()
                f.setBold(True)
                lbl.setFont(f)
            return lbl

        self._status_indicator = QLabel("●")
        self._status_indicator.setFont(QFont("Segoe UI", 18))
        self._status_text = make_label("Unbekannt", bold=True)

        self._power_val = make_label()
        self._energy_val = make_label()
        self._voltage_val = make_label()
        self._current_val = make_label()
        self._temp_val = make_label()
        self._ip_val = make_label()
        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color: #e74c3c;")
        self._error_lbl.setWordWrap(True)

        self._toggle_btn = QPushButton("Ein/Aus")
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.clicked.connect(self._on_toggle)

        row = 0
        layout.addWidget(self._status_indicator, row, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_text, row, 1, 1, 3)
        row += 1

        for label_text, value_widget in [
            ("Leistung:", self._power_val),
            ("Verbrauch:", self._energy_val),
            ("Spannung:", self._voltage_val),
            ("Strom:", self._current_val),
            ("Temperatur:", self._temp_val),
            ("IP:", self._ip_val),
        ]:
            layout.addWidget(QLabel(label_text), row, 0, 1, 1, Qt.AlignmentFlag.AlignRight)
            layout.addWidget(value_widget, row, 1, 1, 3)
            row += 1

        layout.addWidget(self._error_lbl, row, 0, 1, 4)
        row += 1
        layout.addWidget(self._toggle_btn, row, 0, 1, 4)

        self._current_status: ShellyStatus | None = None
        self._device_cfg: dict = {}

    def set_device_config(self, cfg: dict):
        self._device_cfg = cfg

    def update_status(self, status: ShellyStatus):
        self._current_status = status

        if not status.online:
            self._status_indicator.setStyleSheet("color: #95a5a6;")
            self._status_text.setText("Offline")
            self._toggle_btn.setEnabled(False)
            self._error_lbl.setText(status.error)
            self._power_val.setText("—")
            self._energy_val.setText("—")
            self._voltage_val.setText("—")
            self._current_val.setText("—")
            self._temp_val.setText("—")
            self._ip_val.setText(status.ip)
            return

        self._error_lbl.setText("")
        self._toggle_btn.setEnabled(True)
        self._ip_val.setText(status.ip)

        if status.relay_on:
            self._status_indicator.setStyleSheet("color: #2ecc71;")
            self._status_text.setText("EIN")
        else:
            self._status_indicator.setStyleSheet("color: #e74c3c;")
            self._status_text.setText("AUS")

        self._power_val.setText(f"{status.power_w:.1f} W")
        self._energy_val.setText(f"{status.total_kwh:.3f} kWh")
        self._voltage_val.setText(
            f"{status.voltage_v:.1f} V" if status.voltage_v is not None else "—"
        )
        self._current_val.setText(
            f"{status.current_a:.3f} A" if status.current_a is not None else "—"
        )
        self._temp_val.setText(
            f"{status.temperature_c:.1f} °C" if status.temperature_c is not None else "—"
        )

    def _on_toggle(self):
        if self._current_status is None:
            return
        ip = self._current_status.ip
        gen = self._device_cfg.get("gen") or self._current_status.gen
        new_state = "off" if self._current_status.relay_on else "on"
        try:
            import requests
            if gen >= 2:
                requests.get(
                    f"http://{ip}/rpc/Switch.Set",
                    params={"id": 0, "on": "true" if new_state == "on" else "false"},
                    timeout=5,
                )
            else:
                requests.get(f"http://{ip}/relay/0", params={"turn": new_state}, timeout=5)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Einstellungs-Dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(400)
        self._config = json.loads(json.dumps(config))  # deep copy
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        for i, dev in enumerate(self._config["devices"]):
            grp = QGroupBox(f"Gerät {i + 1}")
            form = QFormLayout(grp)
            name_edit = QLineEdit(dev.get("name", ""))
            ip_edit = QLineEdit(dev.get("ip", ""))
            name_edit.setObjectName(f"name_{i}")
            ip_edit.setObjectName(f"ip_{i}")
            form.addRow("Name:", name_edit)
            form.addRow("IP-Adresse:", ip_edit)
            layout.addWidget(grp)

        grp_refresh = QGroupBox("Aktualisierung")
        form_r = QFormLayout(grp_refresh)
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(2, 300)
        self._interval_spin.setSuffix(" Sekunden")
        self._interval_spin.setValue(self._config.get("refresh_interval", 10))
        form_r.addRow("Intervall:", self._interval_spin)
        layout.addWidget(grp_refresh)

        grp_discovery = QGroupBox("Gerätesuche")
        discovery_layout = QVBoxLayout(grp_discovery)
        self._discover_btn = QPushButton("Shelly-Geräte automatisch finden")
        self._discover_btn.clicked.connect(self._on_find_devices)
        self._discover_info = QLabel("")
        self._discover_info.setWordWrap(True)
        discovery_layout.addWidget(self._discover_btn)
        discovery_layout.addWidget(self._discover_info)
        layout.addWidget(grp_discovery)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        for i in range(len(self._config["devices"])):
            name_w: QLineEdit = self.findChild(QLineEdit, f"name_{i}")
            ip_w: QLineEdit = self.findChild(QLineEdit, f"ip_{i}")
            old_ip = self._config["devices"][i].get("ip", "").strip()
            new_ip = ip_w.text().strip()
            self._config["devices"][i]["name"] = name_w.text().strip()
            self._config["devices"][i]["ip"] = new_ip
            if new_ip != old_ip:
                self._config["devices"][i]["gen"] = None  # neu erkennen
        self._config["refresh_interval"] = self._interval_spin.value()
        self.accept()

    def _on_find_devices(self):
        self._discover_btn.setEnabled(False)
        self._discover_info.setText("Suche läuft im lokalen Netzwerk …")
        QApplication.processEvents()

        try:
            found = discover_devices()
        except Exception as exc:
            self._discover_info.setText(f"Fehler bei der Suche: {exc}")
            self._discover_btn.setEnabled(True)
            return

        if not found:
            self._discover_info.setText("Keine Shelly-Geräte gefunden.")
            self._discover_btn.setEnabled(True)
            return

        slots = len(self._config["devices"])
        applied = 0
        for idx, dev in enumerate(found[:slots]):
            self._config["devices"][idx]["name"] = dev.get("name") or f"Shelly {idx + 1}"
            self._config["devices"][idx]["ip"] = dev.get("ip", "")
            self._config["devices"][idx]["gen"] = dev.get("gen")

            name_w: QLineEdit = self.findChild(QLineEdit, f"name_{idx}")
            ip_w: QLineEdit = self.findChild(QLineEdit, f"ip_{idx}")
            name_w.setText(self._config["devices"][idx]["name"])
            ip_w.setText(self._config["devices"][idx]["ip"])
            applied += 1

        extra = max(0, len(found) - slots)
        if extra:
            self._discover_info.setText(
                f"{len(found)} Geräte gefunden, {applied} übernommen (maximal {slots})."
            )
            QMessageBox.information(
                self,
                "Weitere Geräte gefunden",
                f"Es wurden {len(found)} Geräte gefunden, aber nur {slots} können hier übernommen werden.",
            )
        else:
            self._discover_info.setText(f"{applied} Gerät(e) gefunden und übernommen.")

        self._discover_btn.setEnabled(True)

    def get_config(self) -> dict:
        return self._config


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shelly Monitor")
        self.setMinimumSize(700, 350)
        self._config = load_config()
        self._cards: list[DeviceCard] = []
        self._build_ui()
        self._setup_timer()
        self._refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 8)

        # Toolbar-Bereich
        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("Aktualisieren")
        self._refresh_btn.clicked.connect(self._refresh)
        settings_btn = QPushButton("Einstellungen")
        settings_btn.clicked.connect(self._open_settings)
        toolbar.addWidget(self._refresh_btn)
        toolbar.addStretch()
        toolbar.addWidget(settings_btn)
        main_layout.addLayout(toolbar)

        # Geräte-Karten
        cards_layout = QHBoxLayout()
        for dev in self._config["devices"]:
            card = DeviceCard(dev.get("name", "Gerät"))
            card.set_device_config(dev)
            self._cards.append(card)
            cards_layout.addWidget(card)
        main_layout.addLayout(cards_layout)

        # Statusleiste
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage("Bereit")

    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        interval_ms = self._config.get("refresh_interval", 10) * 1000
        self._timer.start(interval_ms)

    def _refresh(self):
        self._refresh_btn.setEnabled(False)
        self._statusbar.showMessage("Aktualisiere …")

        from PyQt6.QtCore import QThread, pyqtSignal

        class Worker(QThread):
            done = pyqtSignal(list)

            def __init__(self, devices):
                super().__init__()
                self._devices = devices

            def run(self):
                results = []
                for dev in self._devices:
                    status = fetch_device(
                        ip=dev["ip"],
                        name=dev.get("name", ""),
                        gen=dev.get("gen"),
                    )
                    results.append(status)
                self.done.emit(results)

        self._worker = Worker(self._config["devices"])
        self._worker.done.connect(self._on_results)
        self._worker.start()

    def _on_results(self, results: list[ShellyStatus]):
        for card, status in zip(self._cards, results):
            card.update_status(status)
        from PyQt6.QtCore import QDateTime
        now = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._statusbar.showMessage(f"Zuletzt aktualisiert: {now}")
        self._refresh_btn.setEnabled(True)

    def _open_settings(self):
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.get_config()
            save_config(self._config)
            # Karten-Titel aktualisieren
            for card, dev in zip(self._cards, self._config["devices"]):
                card.setTitle(dev.get("name", "Gerät"))
                card.set_device_config(dev)
            # Timer neu starten
            self._timer.stop()
            self._timer.start(self._config.get("refresh_interval", 10) * 1000)
            self._refresh()


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dunkles Farbschema
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button, QColor(60, 60, 65))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
