

import importlib.util
import os

# __file__ ja esta dentro de pcbot/plugins/ — nao juntar "plugins" de novo
# (bug anterior fazia PLUGINS_DIR apontar pra pcbot/plugins/plugins, que
# nunca existe, entao list_plugins() sempre voltava vazio).
PLUGINS_DIR = os.path.dirname(__file__)

def _load_plugin(name):
    path = os.path.join(PLUGINS_DIR, f"{name}.py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location(f"pcbot.plugins.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def list_plugins():
    """Lista plugins disponiveis no diretorio de plugins."""
    if not os.path.isdir(PLUGINS_DIR):
        return []
    out = []
    for fname in sorted(os.listdir(PLUGINS_DIR)):
        if fname.endswith(".py") and not fname.startswith("_"):
            out.append(fname[:-3])
    return out