import logging
import yaml
import threading
import os
import time
from mido import get_input_names, open_input
from modalapi import mod as modapi
import pistomp.config
from logging.handlers import RotatingFileHandler

# Configure log output to file
LOG_FILE = "/tmp/midi_snapshot_plugin.log"
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=500_000, backupCount=3),
        logging.StreamHandler()
    ]
)

plugin_instance = None

def register_plugin(handler):
    global plugin_instance
    plugin_instance = MidiSnapshotPlugin(handler)
    plugin_instance.start()
    logging.info("[plugin:midi_snapshot] ✅ Plugin MIDI snapshot chargé")
    return plugin_instance

class MidiSnapshotPlugin:
    def __init__(self, handler):
        self.handler = handler
        self.config = self.load_config()
        self.snapshot_map = self.config.get('midi', {}).get('snapshot', {})
        self.verbose = self.config.get('verbose', False)
        self.running = False
        self.active_ports = {}  # port_name -> thread

    def load_config(self):
        try:
            config_file = os.path.join(pistomp.config.data_dir, "midi_snapshot_plugin.yml")
            with open(config_file, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logging.warning("[plugin:midi_snapshot] Aucun fichier config.yaml trouvé.")
            return {}

    def start(self):
        self.running = True
        threading.Thread(target=self.listen_to_all_midi_ports, daemon=True).start()
        threading.Thread(target=self.monitor_midi_devices, daemon=True).start()

    def listen_to_all_midi_ports(self):
        input_names = set(get_input_names())
        if self.verbose or not input_names:
            logging.info(f"[plugin:midi_snapshot] Ports MIDI détectés: {input_names}")
        for port_name in input_names:
            self.start_listening_to_port(port_name)

    def start_listening_to_port(self, port_name):
        thread = self.active_ports.get(port_name)
        if thread and thread.is_alive():
            return
        self.active_ports.pop(port_name, None)
        thread = threading.Thread(target=self.listen_to_port, args=(port_name,), daemon=True)
        thread.start()
        self.active_ports[port_name] = thread
        logging.info(f"[plugin:midi_snapshot] 🎧 Démarrage de l'écoute du port MIDI: {port_name}")

    def monitor_midi_devices(self, interval=5):
        logging.info("[plugin:midi_snapshot] 🔁 Surveillance des périphériques MIDI lancée.")
        previous_ports = set(get_input_names())
        while self.running:
            current_ports = set(get_input_names())
            if self.verbose:
            	logging.debug(f"[plugin:midi_snapshot] 🔎 Scan périodique - Ports actuels: {current_ports}")
            new_ports = current_ports - previous_ports
            removed_ports = previous_ports - current_ports

            for port in new_ports:
                logging.info(f"[plugin:midi_snapshot] 🔌 Nouveau port MIDI détecté: {port}")
                self.start_listening_to_port(port)

            for port in removed_ports:
                logging.info(f"[plugin:midi_snapshot] ❌ Port MIDI déconnecté: {port}")
                self.active_ports.pop(port, None)

            previous_ports = current_ports
            time.sleep(interval)

    def listen_to_port(self, port_name):
        try:
            with open_input(port_name) as inport:
                logging.info(f"[plugin:midi_snapshot] ✅ Écoute active sur : {port_name}")
                for msg in inport:
                    if not self.running:
                        break
                    self.handle_midi_message(msg)
        except Exception as e:
            logging.warning(f"[plugin:midi_snapshot] ❌ Erreur sur {port_name}: {e}")
        finally:
            logging.info(f"[plugin:midi_snapshot] ⛔ Arrêt de l'écoute du port: {port_name}")

    def handle_midi_message(self, msg):
        if msg.type == 'control_change':
            chan = msg.channel + 1
            cc = msg.control
            action = self.snapshot_map.get('cc', {}).get(f"{chan}:{cc}")
        elif msg.type == 'program_change':
            chan = msg.channel + 1
            pc = msg.program
            action = self.snapshot_map.get('pc', {}).get(f"{chan}:{pc}")
        else:
            return

        if not action:
            return

        try:
            if action == 'next':
                self.handler.preset_incr_and_change()
            elif action == 'previous':
                self.handler.preset_decr_and_change()
            elif action.startswith("load:"):
                index = int(action.split(":")[1])
                self.handler.preset_set_and_change(index)
        except Exception as e:
            logging.error(f"[plugin:midi_snapshot] Échec exécution de l'action {action}: {e}")

    def load_snapshot(self, index):
        logging.info(f"[plugin:midi_snapshot] Chargement snapshot index: {index}")
        modapi.load_snapshot(index)

    def load_next_snapshot(self):
        current_name = modapi.get_current_snapshot_name()
        snapshot_list = modapi.get_snapshot_list()
        names = list(snapshot_list.values())
        keys = list(snapshot_list.keys())
        if current_name in names:
            idx = names.index(current_name)
            next_idx = (idx + 1) % len(names)
            logging.info(f"[plugin:midi_snapshot] Snapshot suivant: index {keys[next_idx]} -> {names[next_idx]}")
            self.load_snapshot(int(keys[next_idx]))

    def load_previous_snapshot(self):
        current_name = modapi.get_current_snapshot_name()
        snapshot_list = modapi.get_snapshot_list()
        names = list(snapshot_list.values())
        keys = list(snapshot_list.keys())
        if current_name in names:
            idx = names.index(current_name)
            prev_idx = (idx - 1 + len(names)) % len(names)
            logging.info(f"[plugin:midi_snapshot] Snapshot précédent: index {keys[prev_idx]} -> {names[prev_idx]}")
            self.load_snapshot(int(keys[prev_idx]))
