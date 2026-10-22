"""Loads the final fine-tuned JobGuard DistilBERT model once and predicts on job postings.

Only the selected model (DistilBERT) is used. The other three models are never imported or loaded, and the
model is always loaded from the LOCAL folder models/distilbert/ (nothing is downloaded from Hugging Face).
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))          # so "from src..." works however the server is started

from src.preprocessing import create_combined_text    # the exact function used to prepare the training text

logger = logging.getLogger("jobguard")

# ---- Locked settings (decided in Milestones 7 and 8; do not change) ----
MODEL_NAME = "DistilBERT"
MAX_LENGTH = 256          # same truncation length as during fine-tuning
THRESHOLD = 0.5           # fraud if fraud_probability >= 0.5
CONFIG_PATH = PROJECT_ROOT / "src" / "final_model_config.json"
REQUIRED_FILES = ["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"]


def read_final_model_config(config_path=CONFIG_PATH):
    """Read the final-model configuration and make sure it really selects DistilBERT."""
    if not Path(config_path).exists():
        raise FileNotFoundError("Final model configuration file src/final_model_config.json was not found.")
    config = json.loads(Path(config_path).read_text())
    if config.get("selected_model") != MODEL_NAME or config.get("artifact_type") != "transformers_folder":
        raise RuntimeError(f"src/final_model_config.json does not select {MODEL_NAME} "
                           f"(found: {config.get('selected_model')!r}). This backend only serves {MODEL_NAME}.")
    if int(config.get("distilbert_max_length", MAX_LENGTH)) != MAX_LENGTH:
        raise RuntimeError(f"Configured max_length differs from the locked value {MAX_LENGTH}.")
    return config


def verify_model_directory(model_dir):
    """Fail early with a clear message if the saved model or tokenizer files are missing."""
    model_dir = Path(model_dir)
    if not model_dir.is_dir():
        raise FileNotFoundError("The saved model folder models/distilbert/ was not found. Copy the trained JobGuard "
                                "DistilBERT model there (it is not downloaded automatically).")
    missing = [name for name in REQUIRED_FILES if not (model_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"models/distilbert/ is missing required file(s): {', '.join(missing)}. "
                                "The trained JobGuard model must be present; a replacement is never downloaded.")


def choose_device():
    """CUDA if available, then Apple MPS, then CPU. Set JOBGUARD_DEVICE=cpu to force a device."""
    forced = os.environ.get("JOBGUARD_DEVICE", "").strip().lower()
    if forced:
        available = {"cuda": torch.cuda.is_available(), "mps": torch.backends.mps.is_available(), "cpu": True}
        if not available.get(forced, False):
            raise RuntimeError(f"JOBGUARD_DEVICE={forced!r} is not available on this machine.")
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def build_combined_text(title, company_profile, description, requirements, benefits):
    """Build the posting text in exactly the training format (TITLE / COMPANY PROFILE / DESCRIPTION / ...)."""
    row = pd.DataFrame([{"title": title, "company_profile": company_profile, "description": description,
                         "requirements": requirements, "benefits": benefits}])
    return create_combined_text(row).iloc[0]


class ModelService:
    """Holds the tokenizer and model in memory (loaded once) and turns text into a fraud probability."""

    load_count = 0      # how many times a model has been loaded in this process (should stay at 1)

    def __init__(self, tokenizer, model, device):
        self.tokenizer = tokenizer
        self.model = model
        self.device = device
        self._lock = threading.Lock()      # one prediction at a time keeps GPU/CPU memory use predictable

    @classmethod
    def load(cls):
        config = read_final_model_config()
        model_dir = PROJECT_ROOT / config["artifact_path"]
        verify_model_directory(model_dir)

        device = choose_device()
        logger.info("Loading the JobGuard %s model from models/distilbert/ (local files only) ...", MODEL_NAME)
        started = time.time()
        # local_files_only=True guarantees nothing is ever fetched from the internet
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(model_dir, local_files_only=True)
        model.to(device)
        model.eval()                       # inference mode: no dropout, no weight updates
        cls.load_count += 1
        logger.info("Model ready on device '%s' (loaded in %.1f s; load #%d in this process)",
                    device, time.time() - started, cls.load_count)
        return cls(tokenizer, model, device)

    def predict(self, combined_text):
        """Return the fraud probability (class 1) for one combined_text string."""
        with self._lock:
            inputs = self.tokenizer(combined_text, truncation=True, max_length=MAX_LENGTH, padding=True,
                                    return_tensors="pt", return_token_type_ids=False)   # DistilBERT takes no token types
            inputs = {name: tensor.to(self.device) for name, tensor in inputs.items()}
            with torch.no_grad():
                logits = self.model(**inputs).logits
            probabilities = torch.softmax(logits, dim=-1)[0]
        return float(probabilities[1])

    def close(self):
        self.model = None
        self.tokenizer = None
