"""Shared evaluation code, so every model is judged in exactly the same way.

The fraudulent class (label 1) is treated as the "positive" class.
"""

import matplotlib.pyplot as plt
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score)


def calculate_metrics(y_true, y_pred):
    """Return the main metrics (and confusion-matrix counts) as a dictionary."""
    true_neg, false_pos, false_neg, true_pos = confusion_matrix(y_true, y_pred).ravel()
    return {
        "Accuracy": accuracy_score(y_true, y_pred),
        "Fraud Precision": precision_score(y_true, y_pred, pos_label=1, zero_division=0),
        "Fraud Recall": recall_score(y_true, y_pred, pos_label=1, zero_division=0),
        "Fraud F1": f1_score(y_true, y_pred, pos_label=1, zero_division=0),
        "True Negatives": int(true_neg),
        "False Positives": int(false_pos),
        "False Negatives": int(false_neg),
        "True Positives": int(true_pos),
    }


def plot_confusion_matrix(y_true, y_pred, title, save_path):
    """Draw a confusion matrix with the count written in each cell, and save it."""
    matrix = confusion_matrix(y_true, y_pred)

    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    image = ax.imshow(matrix, cmap="Blues")
    fig.colorbar(image, ax=ax)

    for row in range(2):
        for col in range(2):
            # white text on dark cells, black text on light cells
            text_color = "white" if matrix[row, col] > matrix.max() / 2 else "black"
            ax.text(col, row, f"{matrix[row, col]:,}", ha="center", va="center",
                    fontsize=14, color=text_color)

    ax.set_xticks([0, 1], labels=["Predicted Legitimate", "Predicted Fraudulent"])
    ax.set_yticks([0, 1], labels=["Actual Legitimate", "Actual Fraudulent"])
    ax.set_title(title)
    fig.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()
