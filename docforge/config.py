import hashlib
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")


LOCAL = ROOT / "settings.local.yaml"   # GUI ki settings (git mein nahi jati)
ENV = ROOT / ".env"


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config():
    load_env()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    if LOCAL.exists():
        over = yaml.safe_load(LOCAL.read_text()) or {}
        over.pop("master_prompt", None)  # lock GUI se override nahi ho sakta
        _merge(cfg, over)
    cfg["_root"] = ROOT
    return cfg


def save_local(updates: dict):
    cur = (yaml.safe_load(LOCAL.read_text()) if LOCAL.exists() else None) or {}
    _merge(cur, updates)
    LOCAL.write_text(yaml.safe_dump(cur, sort_keys=False, allow_unicode=True))


def save_keys(deploy=None, eleven=None, ai33=None):
    vals = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    if deploy:
        vals["DEPLOY_API_KEY"] = deploy.strip()
        os.environ["DEPLOY_API_KEY"] = deploy.strip()
    if eleven:
        vals["ELEVENLABS_API_KEY"] = eleven.strip()
        os.environ["ELEVENLABS_API_KEY"] = eleven.strip()
    if ai33:
        vals["AI33_API_KEY"] = ai33.strip()
        os.environ["AI33_API_KEY"] = ai33.strip()
    ENV.write_text("".join(f"{k}={v}\n" for k, v in vals.items()))
    try:
        ENV.chmod(0o600)
    except Exception:
        pass


def mask(key):
    v = os.environ.get(key, "")
    return f"{v[:4]}…{v[-4:]}  (saved)" if len(v) > 10 else ("(not set)" if not v else "(saved)")


def master_prompt_text(cfg, verify=True):
    p = ROOT / cfg["master_prompt"]["path"]
    data = p.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if verify and digest != cfg["master_prompt"]["sha256"]:
        raise RuntimeError(
            "Master prompt LOCK fail: prompts/master_prompt.txt badal gaya hai.\n"
            f"  expected {cfg['master_prompt']['sha256']}\n  found    {digest}\n"
            "Jaan boojh kar badla hai to:  python run.py relock"
        )
    return data.decode("utf-8")


def relock():
    cfgp = ROOT / "config.yaml"
    cfg = yaml.safe_load(cfgp.read_text())
    digest = hashlib.sha256((ROOT / cfg["master_prompt"]["path"]).read_bytes()).hexdigest()
    txt = cfgp.read_text()
    old = cfg["master_prompt"]["sha256"]
    cfgp.write_text(txt.replace(old, digest))
    return digest
