# Presentation Assets

The best existing file for each part of the talk. Figures are in `results/figures/`, tables in `results/metrics/`.
Nothing here is a finished slide. It is a menu to pick from.

**Which numbers are "validation" and which are "test"?** Validation figures come from the internal split of `train.csv` used to choose settings. Test figures come from the single final evaluation on `test.csv`. Label the source on any slide that shows numbers.

---

## DATA EXPLORATION

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/figures/class_distribution.png` | "The data: fraud is rare" | Shows how few job postings are fraudulent compared with legitimate ones, which is why accuracy alone is misleading. |
| `results/figures/fraud_rate_by_binary_features.png` | "What the data looks like" (optional) | Compares the fraud rate for simple yes/no features such as having a company logo or screening questions. |

## PREPROCESSING

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/metrics/preprocessing_summary.csv` (as a small table) | "Cleaning the data: 17,880 to 16,066" | Shows how duplicate rows and repeated text were removed before splitting, to prevent leakage. |
| `results/figures/train_test_fraud_percentage.png` | "Stratified train/test split" | Shows that train and test keep the same fraud share (about 4.5%). |
| `results/metrics/split_summary.csv` (as a small table) | Same slide as above | Gives exact row counts: 12,852 train and 3,214 test. |

## LOGISTIC REGRESSION

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/figures/logistic_top_terms.png` | "What the simple model learned" | Lists the words that push a posting toward fraudulent or legitimate in the selected Logistic Regression model. |
| `results/metrics/logistic_regression_validation_selection.csv` (as a small table) | "Does class weighting help?" | On validation data, balanced weighting raised fraud recall from 0.2609 to 0.9043 and F1 from 0.4138 to 0.7298. |
| `results/figures/final_logistic_confusion_matrix.png` | Final-test detail for this model | Final locked Logistic Regression on the test set: 118 scams caught, 73 false alarms. |

**Careful:** `results/figures/logistic_model_comparison.png`, `logistic_confusion_matrix.png` and `logistic_balanced_confusion_matrix.png` come from the early Milestone 4 experiment, which was evaluated on **test** data before the validation-only method was adopted. If you use them, label them "test set, early experiment" and keep the methodology caveat in `docs/presentation_facts.md`. Preferred for slides: the validation table above and `final_logistic_confusion_matrix.png`.

## NAIVE BAYES

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/metrics/naive_bayes_validation_results.csv` (as a small table) | "Tuning one setting (alpha)" | Six settings compared on validation; `alpha=0.1, fit_prior=True` won. |
| `results/figures/naive_bayes_validation_confusion_matrix.png` | Naive Bayes detail | Validation confusion matrix of the selected setting: few false alarms, but many missed scams. |
| `results/figures/traditional_models_validation_comparison.png` | Compare LR and NB so far | Compares the two classical models side by side on validation data. |
| `results/figures/final_naive_bayes_confusion_matrix.png` | Final-test detail for this model | Final locked Naive Bayes on the test set: 91 scams caught, 19 false alarms. |

## XGBOOST

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/metrics/xgboost_validation_results.csv` (as a small table) | "Class weighting can backfire" | Baseline, full weight and moderate weight on validation: full weight dropped precision to 0.4051, moderate weight gave the best F1 (0.7476). |
| `results/figures/xgboost_validation_confusion_matrix.png` | XGBoost detail | Validation confusion matrix of the selected moderate-weight model. |
| `results/figures/xgboost_top_features.png` | "What the tree model relies on" | Shows the words XGBoost found most useful. |
| `results/figures/model_comparison_through_xgboost.png` | "Three classical models compared" | Validation precision, recall and F1 for LR, NB and XGBoost in one chart. |
| `results/figures/final_xgboost_confusion_matrix.png` | Final-test detail for this model | Final locked XGBoost on the test set: 99 scams caught, 21 false alarms. |

## DISTILBERT

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/figures/distilbert_training_history.png` | "How the model trained" | Shows how validation scores changed across the training epochs for the baseline and weighted versions. |
| `results/metrics/distilbert_validation_results.csv` (as a small table) | "Baseline vs class-weighted" | The baseline had the better validation F1 (0.7678 against 0.7364), so it was kept. |
| `results/figures/distilbert_validation_confusion_matrix.png` | DistilBERT validation detail | Validation confusion matrix of the selected baseline model. |
| `results/metrics/distilbert_colab_run_info.csv` | "Training setup" | Records the GPU (Tesla T4), settings (2 epochs, learning rate 2e-5, batch size 16, `max_length` 256) and the training times. |
| `results/metrics/distilbert_token_length_summary.csv` | "Limitation: truncation" | Median posting is 530 tokens and 88.7% are longer than the 256-token limit. |
| `results/figures/final_distilbert_confusion_matrix.png` | See FINAL RESULTS | Final locked DistilBERT on the test set. |

## FINAL RESULTS

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/figures/final_four_model_comparison.png` | **The main results slide** | Precision, recall and F1 of all four models on the same untouched test set. |
| `results/metrics/final_test_model_comparison.csv` (as a table) | Results table next to the chart | Exact numbers for all four models, including false positives and false negatives. |
| `results/figures/final_distilbert_confusion_matrix.png` | "The chosen model in detail" | 107 scams caught, 37 missed, 14 false alarms, 3,056 legitimate postings correctly cleared. |
| `results/figures/final_four_confusion_matrices_overview.png` | "All four models side by side" | The four confusion matrices in one picture, to compare the kinds of mistakes. |
| `results/figures/validation_vs_test_fraud_f1.png` | "Do the results hold up?" | Compares each model's validation F1 with its test F1 to show the ranking did not change. |
| `results/metrics/final_model_decision.csv` | "Why DistilBERT" | Records the selected model and the reason it was chosen. |

## APPLICATION

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/figures/jobguard_v2_homepage.png` | "The product" | The paste-first page: one large box, the Analyze Job button and the two example chips. |
| `results/figures/jobguard_v2_paste_filled.png` | "Paste, and it understands the posting" | A pasted posting with the Detected details summary. |
| `results/figures/jobguard_v2_extracted_details.png` | "Smart intake" (optional) | The optional review panel showing the five fields the parser filled in, editable. |
| `results/figures/jobguard_v2_legitimate_result.png` | "A legitimate result" | The professional example classified as Likely Legitimate (about 0.1% fraud risk). |
| `results/figures/jobguard_v2_fraudulent_result.png` | "A suspicious result" | The suspicious example classified as Potentially Fraudulent (about 98.9% fraud risk). |
| `results/figures/jobguard_v2_mobile.png` | "Works on a phone-sized screen" (optional) | The result as shown at 390 px wide. |
| `docs/productization_notes.md` | "From a dataset form to a product" | Why the five-field form was replaced by a paste box and how the rule-based parser works. |
| `results/figures/jobguard_homepage.png` and the other `jobguard_*.png` app screenshots | Not for slides | Old five-field interface from Milestone 10, kept for history. |
| `results/figures/backend_swagger_docs.png` | "The backend API" (optional) | The auto-generated FastAPI documentation page for `/predict` and `/health`. |
| `docs/live_demo_script.md` | Rehearsal | The 12-step live demo and the screenshot backup plan. |

## ARCHITECTURE

| File | Recommended slide use | One-sentence explanation |
|---|---|---|
| `results/figures/jobguard_system_architecture.png` | "How it works end to end" | Shows the request path from the browser through FastAPI and DistilBERT and back to the result card, with the offline model-selection flow on the right. |
| `docs/make_architecture_diagram.py` | Editing the diagram | The script that draws the diagram, in case a label needs changing. |

---

## Other files for the presentation

- `docs/presentation_facts.md`: every verified number, the limitations, the tech stack, and "Challenges and Solutions".
- `docs/presentation_code_snippets.md`: ten code excerpts with what to say about each.
- `docs/project_freeze.md`: the frozen configuration. Use it to answer "what exactly did you submit?".
