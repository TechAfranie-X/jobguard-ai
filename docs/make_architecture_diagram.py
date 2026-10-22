"""Draws results/figures/jobguard_system_architecture.png (16:9, slide-ready).

Run from the project root:   python docs/make_architecture_diagram.py

Only the numbers that appear in the project's saved results are written on the picture
(17,880 raw postings, 16,066 unique texts, 3,214 held-out test postings, fraud F1 80.75%).
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to a file, no window needed
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUTPUT = Path(__file__).resolve().parent.parent / "results" / "figures" / "jobguard_system_architecture.png"

# Colors that match the web app
NAVY = "#0f1b33"
MUTED = "#4a5775"
ACCENT = "#1d4ed8"
ACCENT_SOFT = "#e8eefc"
BORDER = "#c3cde3"
PANEL = "#f5f7fb"
WHITE = "#ffffff"
GREY_BOX = "#eef1f7"

fig = plt.figure(figsize=(16, 9))
ax = fig.add_axes([0, 0, 1, 1])  # use the whole picture, no margins
ax.set_xlim(0, 16)
ax.set_ylim(0, 9)
ax.axis("off")
fig.patch.set_facecolor(WHITE)


def panel(x0, x1, title):
    """Light background panel with a heading."""
    ax.add_patch(FancyBboxPatch((x0, 0.35), x1 - x0, 7.6, boxstyle="round,pad=0,rounding_size=0.18",
                                facecolor=PANEL, edgecolor=BORDER, linewidth=1.2))
    ax.text((x0 + x1) / 2, 7.62, title, ha="center", va="center", fontsize=13, fontweight="bold", color=MUTED)


def box(x0, x1, y0, y1, title, subtitle="", style="app"):
    """A rounded box with a bold title and a smaller description."""
    face, edge, text_color = {
        "app": (WHITE, ACCENT, NAVY),
        "highlight": (ACCENT, ACCENT, WHITE),
        "dev": (WHITE, BORDER, NAVY),
        "client": (ACCENT_SOFT, ACCENT, NAVY),
    }[style]
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=0.12",
                                facecolor=face, edgecolor=edge, linewidth=1.8))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if subtitle:
        ax.text(cx, cy + 0.16, title, ha="center", va="center", fontsize=13, fontweight="bold", color=text_color)
        sub_color = "#dbe5ff" if style == "highlight" else MUTED
        ax.text(cx, cy - 0.17, subtitle, ha="center", va="center", fontsize=9.5, color=sub_color)
    else:
        ax.text(cx, cy, title, ha="center", va="center", fontsize=13, fontweight="bold", color=text_color)


def arrow(x0, y0, x1, y1, color=ACCENT, dashed=False, width=2.0):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=width, shrinkA=0, shrinkB=0,
                                linestyle="--" if dashed else "-", mutation_scale=18))


def label(x, y, text, color=ACCENT, size=10.5, ha="center", weight="bold"):
    ax.text(x, y, text, ha=ha, va="center", fontsize=size, fontweight=weight, color=color,
            bbox=dict(boxstyle="round,pad=0.2", facecolor=WHITE, edgecolor="none"))


# ---------- Title ----------
ax.text(8, 8.5, "JobGuard AI: System Architecture", ha="center", va="center", fontsize=22,
        fontweight="bold", color=NAVY)

# ---------- Column 1: browser ----------
C1 = (0.7, 3.9)
panel(0.4, 4.2, "Browser")
box(*C1, 6.35, 7.2, "User", "pastes a job posting", style="client")
box(*C1, 3.45, 4.9, "React + Vite Frontend", "form · local validation\nlocalhost:5173", style="client")
box(*C1, 0.6, 1.45, "React Result Card", "label · fraud risk % · disclaimer", style="client")
arrow(2.3, 6.35, 2.3, 4.9)                       # user -> React
ax.plot([2.3, 2.3], [3.45, 1.45], color=ACCENT, lw=1.6, linestyle=":")   # same React app (no arrowhead)
label(2.3, 2.45, "same React app", color=MUTED, size=9, weight="normal")

# ---------- Column 2: FastAPI backend ----------
C2 = (5.6, 10.2)
panel(5.3, 10.5, "FastAPI Backend (Python)")
steps = [
    ("Input Validation", "title + description required, text trimmed"),
    ("combined_text Preprocessing", "five text fields joined exactly as in training"),
    ("DistilBERT Tokenizer", "truncation=True, max_length=256"),
    ("Fine-tuned DistilBERT", "PyTorch model, loaded once at startup"),
    ("Fraud Probability + Prediction", "softmax, fraudulent if probability >= 0.5"),
    ("FastAPI JSON Response", "prediction · label · fraud % · model · disclaimer"),
]
tops = [7.2 - i * 1.15 for i in range(6)]
for i, ((title, sub), top) in enumerate(zip(steps, tops)):
    style = "highlight" if title == "Fine-tuned DistilBERT" else "app"
    box(*C2, top - 0.85, top, title, sub, style=style)
    if i < len(steps) - 1:
        arrow(7.9, top - 0.85, 7.9, tops[i + 1])

# request: React -> first backend step (elbow)
y_req = 4.2
x_mid = 4.75
ax.plot([C1[1], x_mid], [y_req, y_req], color=ACCENT, lw=2.0)
ax.plot([x_mid, x_mid], [y_req, 6.78], color=ACCENT, lw=2.0)
arrow(x_mid, 6.78, C2[0], 6.78)
label(x_mid, 5.5, "POST\n/predict", size=10)

# response: last backend step -> result card
arrow(C2[0], 1.025, C1[1], 1.025)
label(4.75, 1.45, "JSON\nresponse", size=10)

# ---------- Column 3: model development (offline) ----------
C3 = (11.8, 15.3)
panel(11.5, 15.6, "Model development (offline)")
box(*C3, 6.6, 7.2, "EMSCAD Dataset", "17,880 postings → 16,066 unique texts", style="dev")

# models box with four chips
ax.add_patch(FancyBboxPatch((C3[0], 4.95), C3[1] - C3[0], 1.35, boxstyle="round,pad=0,rounding_size=0.12",
                            facecolor=WHITE, edgecolor=BORDER, linewidth=1.8))
ax.text(13.55, 6.08, "Model Development", ha="center", va="center", fontsize=13, fontweight="bold", color=NAVY)
chips = [("Logistic Regression", 12.65, 5.62), ("Naive Bayes", 14.45, 5.62),
         ("XGBoost", 12.65, 5.18), ("DistilBERT", 14.45, 5.18)]
for name, cx, cy in chips:
    selected = name == "DistilBERT"
    ax.add_patch(FancyBboxPatch((cx - 0.8, cy - 0.15), 1.6, 0.3, boxstyle="round,pad=0,rounding_size=0.08",
                                facecolor=ACCENT if selected else GREY_BOX, edgecolor="none"))
    ax.text(cx, cy, name, ha="center", va="center", fontsize=9.5, fontweight="bold",
            color=WHITE if selected else NAVY)

box(*C3, 4.0, 4.65, "Final Evaluation", "held-out test set: 3,214 postings", style="dev")
box(*C3, 2.9, 3.75, "DistilBERT Selected", "best fraud F1: 80.75% on test set", style="highlight")

arrow(13.55, 6.6, 13.55, 6.3, color=MUTED, width=1.6)
arrow(13.55, 4.95, 13.55, 4.65, color=MUTED, width=1.6)
arrow(13.55, 4.0, 13.55, 3.75, color=MUTED, width=1.6)

# the saved, selected model is what the backend loads
arrow(C3[0], 3.325, C2[1], 3.325, color=ACCENT, dashed=True)
label(10.95 + 0.4, 3.75, "saved\nmodel", size=10)

# ---------- Footer ----------
ax.text(8, 0.12, "The web app runs only the final DistilBERT model; the other three models were used for comparison. "
        "The probability is a risk signal, not proof.", ha="center", va="center", fontsize=10, color=MUTED, style="italic")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUTPUT, dpi=200, facecolor=WHITE, bbox_inches=None)
print("Saved:", OUTPUT)
