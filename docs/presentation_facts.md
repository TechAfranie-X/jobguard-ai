# Presentation Facts

One page of verified facts for building the slides. **Every number below comes from a saved results file or the project code.**
Source files are named so a claim can be checked. If a number is not on this page, do not put it on a slide without checking it first.

---

## PROJECT

- **Title:** JobGuard AI: Detecting Fraudulent Job Postings Using Machine Learning and NLP
- **Goal:** Given the text of a job posting, estimate how likely it is to be a fraudulent posting, and show it in a simple web app.
- **Final model:** fine-tuned `distilbert-base-uncased`, decision threshold 0.5, `max_length=256`.
- **Final product:** React + Vite frontend, FastAPI backend, locked DistilBERT model (see `results/figures/jobguard_system_architecture.png`).
- **Positioning:** a risk signal that supports a human decision. It is not proof that a posting is a scam.

---

## DATASET

- **Dataset:** EMSCAD (Employment Scam Aegean Dataset), one public dataset of job postings. Target column: `fraudulent` (1 = fraudulent).
- **Original rows:** 17,880 (`results/metrics/preprocessing_summary.csv`).
- **After removing duplicate rows (ignoring `job_id`):** 17,599.
- **After removing repeated `combined_text`:** **16,066 unique postings** (1,533 repeated-text copies removed: 1,395 legitimate, 138 fraudulent). No identical text had conflicting labels (0 conflicting groups).
- **Fraud share:** 718 of 16,066 = **4.47%** (`results/metrics/split_summary.csv`). Heavy class imbalance.

| Split | Rows | Legitimate | Fraudulent | Fraud % |
|---|---|---|---|---|
| All (cleaned) | 16,066 | 15,348 | 718 | 4.47 |
| Train (`train.csv`) | 12,852 | 12,278 | 574 | 4.47 |
| Test (`test.csv`) | 3,214 | 3,070 | 144 | 4.48 |

Split: stratified 80/20 so both parts keep the same fraud share.

**Leakage-prevention steps**
1. Removed duplicate rows, then removed repeated `combined_text` **before** the train/test split, so the same text cannot appear on both sides. Overlap was verified to be zero.
2. Stratified train/test split with a fixed seed (42).
3. TF-IDF is fitted on training data only, then applied to other data.
4. Model and setting selection used a **validation split carved out of `train.csv`** (10,281 train / 2,571 validation, seed 42, stratified). `test.csv` was not used for selection.
5. After selection, each model was retrained on all of `train.csv` and evaluated **once** on `test.csv`.
6. File fingerprints (MD5) of the data and model files were recorded and re-checked, to prove nothing changed after the lock (`results/metrics/final_model_lock.csv`).

---

## MODELS

All four models read the same `combined_text` (TITLE / COMPANY PROFILE / DESCRIPTION / REQUIREMENTS / BENEFITS).

| Model | Input to model | Selected configuration (chosen on validation only) | Validation fraud F1 |
|---|---|---|---|
| Logistic Regression | TF-IDF (1-2 word phrases, 20,000 features) | `class_weight="balanced"` | 0.7298 |
| Multinomial Naive Bayes | TF-IDF | `alpha=0.1`, `fit_prior=True` | 0.7320 |
| XGBoost | TF-IDF | 200 trees, depth 4, learning rate 0.05, moderate `scale_pos_weight` (about 4.63) | 0.7476 |
| DistilBERT | Raw text tokens (max 256) | Baseline, no class weights; 2 epochs, lr 2e-5, batch 16, weight decay 0.01, seed 42 | 0.7678 |

Sources: `logistic_regression_validation_selection.csv`, `naive_bayes_validation_results.csv`, `xgboost_validation_results.csv`, `distilbert_validation_results.csv`, `validation_vs_test_comparison.csv` (all in `results/metrics/`).

DistilBERT was fine-tuned on a Google Colab **Tesla T4** GPU (`distilbert_colab_run_info.csv`): the final model on all 12,852 training rows took about 9.3 minutes.

---

## FINAL TEST RESULTS

Evaluated once on `test.csv` (3,214 postings: 3,070 legitimate, 144 fraudulent). "Fraud" metrics are about the fraudulent class. Source: `results/metrics/final_test_model_comparison.csv`.

| Model | Accuracy | Fraud Precision | Fraud Recall | Fraud F1 | False Positives | False Negatives |
|---|---|---|---|---|---|---|
| Logistic Regression | 0.9692 | 0.6178 | 0.8194 | 0.7045 | 73 | 26 |
| Multinomial Naive Bayes | 0.9776 | 0.8273 | 0.6319 | 0.7165 | 19 | 53 |
| XGBoost | 0.9795 | 0.8250 | 0.6875 | 0.7500 | 21 | 45 |
| **DistilBERT** | **0.9841** | **0.8843** | 0.7431 | **0.8075** | **14** | **37** |

Plain-language meaning:
- **Precision:** of the postings flagged as fraud, how many really were.
- **Recall:** of the real fraud postings, how many were caught.
- **F1:** a single score that balances precision and recall.

Figures: `final_four_model_comparison.png`, `final_four_confusion_matrices_overview.png`.

---

## FINAL DISTILBERT CONFUSION MATRIX

Read from `final_test_model_comparison.csv` and re-computed from `final_test_predictions.csv` (the two agree).

|  | Predicted legitimate | Predicted fraudulent |
|---|---|---|
| **Actually legitimate (3,070)** | 3,056 (true negatives) | 14 (false positives) |
| **Actually fraudulent (144)** | 37 (false negatives) | 107 (true positives) |

- 107 of 144 scams caught (recall 74.31%).
- 14 legitimate postings wrongly flagged out of 3,070 (about 0.46%).
- Of the 121 postings DistilBERT flagged, 107 were real fraud (precision 88.43%).
- 37 scams missed (25.7% of the 144).

Figure: `final_distilbert_confusion_matrix.png`.

---

## IMPORTANT FINDINGS

1. **Accuracy alone was misleading.** All four models scored between 96.9% and 98.4% accuracy, yet their fraud recall ranged from 63.2% to 81.9%. A model that predicted "legitimate" for everything would score about 95.5% accuracy and catch no fraud at all, because about 95.5% of postings are legitimate. (The "predict everything legitimate" figure follows directly from the 144 of 3,214 fraud rate: 3,070 / 3,214 = 95.5%.) This is why the project is judged on fraud precision, recall and F1, plus confusion matrices.
2. **Logistic Regression had the highest recall of the four** (0.8194, 118 of 144 scams caught), but at the cost of the lowest precision (0.6178) and the most false alarms (73).
3. **DistilBERT had the best F1 (0.8075) and the best precision (0.8843)**, with the fewest false positives (14) and false negatives (37).
4. **XGBoost was the strongest TF-IDF model** (F1 0.7500), ahead of Naive Bayes (0.7165) and Logistic Regression (0.7045).
5. **Class weighting did not help every model.**
   - Logistic Regression: it helped a lot on validation (F1 0.4138 to 0.7298; recall 0.2609 to 0.9043).
   - XGBoost: the full-ratio weight (about 21.4) hurt (precision 0.9344 baseline to 0.4051; F1 0.5455). A moderate weight (square root of the ratio, about 4.63) worked best (F1 0.7476).
   - DistilBERT: class-weighted loss did not help (validation F1 0.7364 against 0.7678 for the baseline), so the baseline was kept.
6. **Validation and test results were broadly consistent, and the model ranking did not change.** Validation fraud F1 versus test fraud F1 per model is in `validation_vs_test_comparison.csv` (LR 0.7298 to 0.7045, NB 0.7320 to 0.7165, XGBoost 0.7476 to 0.7500, DistilBERT 0.7678 to 0.8075).

---

## LIMITATIONS

- **One dataset.** EMSCAD is a single, older public dataset. These scores do not guarantee the same performance on new kinds of scams or on postings from other sites.
- **Fraud is a minority class** (about 4.5%), so metrics move a lot when a few postings change.
- **Only 144 fraudulent postings in the test set.** Differences of a few points between models are uncertain.
- **`max_length=256` truncates long postings.** Measured on `train.csv` with the saved tokenizer (`results/metrics/distilbert_token_length_summary.csv`): median length 530 tokens, 88.7% of postings longer than 256 tokens, 52.7% longer than 512. Because `combined_text` starts with the title and description, the end of a long posting is not seen by the model.
- **37 scams missed.** Of 144 fraudulent test postings, DistilBERT did not flag 37 (about one in four).
- **The probability is a risk signal, not proof.** It is the model's score, not a verified fact about the employer.
- **Short, plain postings can still look fraudulent to the model.** In the live app a short hand-written Data Entry example scored 98.8% fraud risk. This was observed on one hand-written example. It is not a measured error rate, and the model was intentionally not changed.
- **DistilBERT was trained once** (single seed), so run-to-run variation is not measured.
- **Early Logistic Regression methodology caveat.** In Milestone 4 Logistic Regression was evaluated on `test.csv` once, before the validation-only protocol was adopted. For the final comparison its configuration was re-selected using validation data only and retrained, so the final choice does not depend on that early result. The test set was nevertheless inspected once at that early stage, and this should be stated honestly (see `notebooks/07_final_model_evaluation.ipynb`).
- The app does not give reasons for its answer (no explainability) and has no authentication or database. It is a classroom demo, not a production service.

---

## TECH STACK

- **Language and data:** Python, Pandas
- **Classical ML:** scikit-learn (TF-IDF, Logistic Regression, Naive Bayes), XGBoost
- **Deep learning:** PyTorch, Hugging Face Transformers, DistilBERT (`distilbert-base-uncased`)
- **Training hardware:** Google Colab GPU (Tesla T4)
- **Backend:** FastAPI (with Pydantic validation)
- **Frontend:** React, Vite (plain JavaScript and CSS)
- **Charts:** Matplotlib

---

## CHALLENGES AND SOLUTIONS

1. **Class imbalance (about 4.5% fraud).**
   *Solution:* judge models by fraud precision, recall and F1 with confusion matrices instead of accuracy, and run class-weighting experiments.
2. **Duplicate and repeated text could leak into the test set.**
   *Solution:* removed duplicate rows and repeated `combined_text` before the split, then verified zero overlap between train and test.
3. **DistilBERT training was too slow on the local Mac.**
   *Solution:* moved training to a free Colab T4 GPU with the same methodology (about 8 to 9 minutes per run).
4. **Full class weighting hurt XGBoost precision** (precision fell to 0.4051 on validation).
   *Solution:* tried a moderate weight (square root of the class ratio), chosen on validation only, before looking at the test set.
5. **Class weighting did not improve DistilBERT.**
   *Solution:* compared baseline and weighted versions on the validation split and kept the baseline (validation F1 0.7678 against 0.7364).
6. **React and FastAPI run on different origins** (ports 5173 and 8000), so the browser blocks the request by default.
   *Solution:* configured CORS in FastAPI for the exact frontend origins (`http://localhost:5173` and `http://127.0.0.1:5173`) instead of allowing everything.
7. **Long postings exceed 256 tokens.**
   *Solution:* documented it as a limitation and measured how many postings are affected (88.7% of `train.csv`). The setting was not changed after the model was selected, so results stay comparable.
