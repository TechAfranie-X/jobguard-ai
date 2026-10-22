# Presentation Code Snippets

Ten short excerpts for the presentation. Every excerpt is copied from the real project files, with only blank lines or comments trimmed.
Each snippet lists the **file**, its **purpose**, and **what to explain on the slide**.
These are Markdown excerpts only. Turn them into slide screenshots later.

Rule of thumb for slides: show 8 to 15 lines at a time and say one idea per snippet.

---

## 1. `combined_text` preprocessing

**File:** `src/preprocessing.py`
**Purpose:** Turns the five text columns of a job posting into one string that every model reads.

```python
TEXT_COLUMNS = ["title", "company_profile", "description", "requirements", "benefits"]

def create_combined_text(df):
    return (
        "TITLE: " + df["title"] + "\n"
        + "COMPANY PROFILE: " + df["company_profile"] + "\n"
        + "DESCRIPTION: " + df["description"] + "\n"
        + "REQUIREMENTS: " + df["requirements"] + "\n"
        + "BENEFITS: " + df["benefits"]
    )
```

**Explain:**
- A posting is spread over five columns. We join them into one labeled text so a model sees the whole posting at once.
- **Training/inference consistency:** the backend (`backend/main.py`) builds the text in this same format. A model trained on one text format and fed another at prediction time would silently perform worse, so the format is the same everywhere.
- Missing fields become empty text, so the labels stay in a fixed order.

---

## 2. TF-IDF: fit on training data only

**File:** `notebooks/03_logistic_regression.ipynb` (same pattern in notebooks 04 and 05)
**Purpose:** Converts text into numbers for the three classical models.

```python
tfidf_settings = dict(lowercase=True, stop_words="english", ngram_range=(1, 2), min_df=2, max_features=20000)
tfidf = TfidfVectorizer(**tfidf_settings)
X_train_tfidf = tfidf.fit_transform(X_train)   # learn vocabulary + convert training text
X_test_tfidf = tfidf.transform(X_test)         # only convert test text (no fitting!)
```

**Explain:**
- TF-IDF gives a word a high score when it is frequent in one posting but rare overall. Single words and two-word phrases count, with a 20,000-feature cap.
- **Why fit only on training data:** the vocabulary and word statistics are *learned*. If they were learned from the test set, information from the test set would leak into training and the results would look better than they really are.
- `fit_transform` on training data, `transform` only on new data. That one line difference is the leakage guard.

---

## 3. Logistic Regression with `class_weight="balanced"`

**File:** `notebooks/03_logistic_regression.ipynb`
**Purpose:** Tests whether making fraud mistakes more costly helps with the imbalanced data (about 4.5% fraud).

```python
LogisticRegression(max_iter=1000, random_state=42, class_weight="balanced")
```

**Explain:**
- Only about 1 in 22 postings is fraudulent, so a model can look accurate while ignoring fraud.
- `class_weight="balanced"` makes a mistake on a fraudulent posting count more during training.
- **Why we tested it:** on the validation split the standard model found only 26.1% of fraud (recall 0.2609, F1 0.4138), while the balanced one found 90.4% (recall 0.9043, F1 0.7298). Source: `results/metrics/logistic_regression_validation_selection.csv`.
- Trade-off to mention: balanced LR raises recall but also raises false alarms (precision 0.6118 on validation).

---

## 4. Multinomial Naive Bayes, `alpha=0.1`

**File:** `notebooks/04_naive_bayes.ipynb`
**Purpose:** The simple, fast probabilistic baseline.

```python
nb_selected = MultinomialNB(alpha=selected_alpha, fit_prior=selected_fit_prior)   # selected: alpha=0.1, fit_prior=True
nb_selected.fit(X_model_train_tfidf, y_model_train)
```

**Explain:**
- `alpha` is smoothing: how much a never-seen word is allowed to count. Small `alpha` means rare, specific words matter more.
- We compared six settings on the validation split only. `alpha=0.1, fit_prior=True` won (F1 0.7320, precision 0.8987). Larger alpha collapsed recall (alpha 1.0 gave recall 0.1217). Source: `results/metrics/naive_bayes_validation_results.csv`.
- Among the three selected classical configurations, Naive Bayes had the highest validation precision (0.8987 against 0.8462 for XGBoost and 0.6118 for balanced Logistic Regression), but it missed more fraud than balanced LR (recall 0.6174 against 0.9043).

---

## 5. XGBoost selected configuration

**File:** `notebooks/05_xgboost.ipynb`
**Purpose:** The strongest of the three TF-IDF models, using a moderate fraud weight.

```python
xgb_params = dict(
    objective="binary:logistic", eval_metric="logloss",
    n_estimators=200, max_depth=4, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1,
)

moderate_weight = float(np.sqrt(negative_count / positive_count))     # about 4.63 on the training subset
xgb_moderate = XGBClassifier(**xgb_params, scale_pos_weight=moderate_weight)
```

**Explain:**
- XGBoost builds 200 small trees, each fixing the mistakes of the previous ones.
- `scale_pos_weight` tells it how much more a fraud mistake costs. The full ratio (about 21.4) was too aggressive: recall rose to 0.8348 but precision fell to 0.4051.
- **The moderate-weight idea:** use the square root of the ratio (about 4.63). It was chosen on the validation split, before the test set was used: precision 0.8462, recall 0.6696, F1 0.7476. Source: `results/metrics/xgboost_validation_results.csv`.
- For the final model, retrained on all of `train.csv`, the weight is recomputed from that data (about 4.625).

---

## 6. DistilBERT tokenization

**File:** `backend/model_service.py` (the same call is used in `notebooks/06_distilbert_colab.ipynb` during training)
**Purpose:** Turns the posting text into token IDs that DistilBERT understands.

```python
MAX_LENGTH = 256          # same truncation length as during fine-tuning

inputs = self.tokenizer(combined_text, truncation=True, max_length=MAX_LENGTH, padding=True,
                        return_tensors="pt", return_token_type_ids=False)
```

**Explain:**
- The tokenizer splits text into word pieces and maps each to an ID.
- `truncation=True, max_length=256` keeps only the first 256 tokens. This is faster and fits the memory limits of the free Colab GPU.
- **Honest limitation:** most postings are longer than 256 tokens. Measured on `train.csv` with the saved tokenizer: median 530 tokens, 88.7% longer than 256. Because `combined_text` starts with the title and description, the beginning of every posting is kept and the end (often benefits) is cut off.
- Training and the live app use the same value (256), which is what keeps them consistent.

---

## 7. DistilBERT model loading and fine-tuning configuration

**File:** `notebooks/06_distilbert_colab.ipynb`
**Purpose:** Loads the pretrained model and sets how it is fine-tuned.

```python
CHECKPOINT = "distilbert-base-uncased"
MAX_LENGTH = 256
SEED = 42

LEARNING_RATE = 2e-5
EPOCHS = 2
TRAIN_BATCH_SIZE = 16
WEIGHT_DECAY = 0.01

model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT, num_labels=2)

arguments = TrainingArguments(
    learning_rate=LEARNING_RATE,
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=TRAIN_BATCH_SIZE,
    weight_decay=WEIGHT_DECAY,
    warmup_steps=warmup_steps,          # 10% of all steps
    seed=SEED,
)
```

(The notebook passes more arguments, such as evaluation and logging settings. They are left out here for readability.)

**Explain:**
- DistilBERT is a smaller, faster version of BERT already trained on a large amount of English text. We add a 2-class output layer (legitimate or fraudulent) and **fine-tune** all of it on our postings.
- Small learning rate (2e-5), 2 epochs, batch size 16. These are common, conservative defaults, not the result of a big search.
- Trained on a Colab **Tesla T4** GPU. Training on all 12,852 training rows took about 9.3 minutes (`results/metrics/distilbert_colab_run_info.csv`). On the local Mac it was too slow.
- The only variant compared against baseline was class-weighted loss, and the baseline won on validation F1 (0.7678 against 0.7364).

---

## 8. FastAPI `/predict` core logic

**File:** `backend/main.py`
**Purpose:** The one endpoint the frontend calls.

```python
@app.post("/predict", response_model=JobPredictionResponse)
def predict(posting: JobPostingRequest, request: Request):
    service = getattr(request.app.state, "model_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="The model is not loaded.")

    combined_text = build_combined_text(posting.title, posting.company_profile, posting.description,
                                        posting.requirements, posting.benefits)
    fraud_probability = service.predict(combined_text)

    is_fraud = fraud_probability >= THRESHOLD       # locked decision rule
    return JobPredictionResponse(
        prediction="fraudulent" if is_fraud else "legitimate",
        label="Potentially Fraudulent" if is_fraud else "Likely Legitimate",
        fraud_probability=round(fraud_probability, 4),
        fraud_percentage=round(fraud_probability * 100, 2),
        model=MODEL_NAME, threshold=THRESHOLD, disclaimer=DISCLAIMER,
    )
```

(The real function also wraps the model call in `try/except` so errors become a safe message with no stack trace; that part is left out here.)

**Explain:**
- The request is validated automatically (title and description required).
- The text is built exactly as in training, then the model returns the probability of the "fraud" class.
- **The decision rule lives only here:** fraud if probability is at least 0.5. The threshold is locked and was not tuned on test data.
- The response always carries the disclaimer, because the number is a risk signal, not proof.
- The model is loaded once at server startup, not on every request.

---

## 9. React `fetch` POST to `/predict`

**File:** `frontend/src/services/api.js`
**Purpose:** Sends the form data to the backend and checks the reply.

```javascript
export async function analyzePosting(posting) {
  const response = await request("/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(posting),
  });

  const body = await readJson(response);

  if (response.status === 422) throw new ApiError(validationMessage(body), "validation");
  if (!response.ok) throw new ApiError(GENERIC_MESSAGE, "server");
  if (!isValidPrediction(body)) {
    throw new ApiError("JobGuard received an unexpected response from the server. Please try again.", "malformed");
  }
  return body;
}
```

**Explain:**
- The frontend sends the form fields as JSON and waits for the reply.
- It handles three failure cases (bad input, server error, unexpected reply) with friendly messages instead of crashing.
- It does no machine learning. It only sends text and receives a result. The `request()` helper adds a 30-second timeout.
- React and FastAPI run on different ports, so the backend explicitly allows the frontend origin (CORS).

---

## 10. React result rendering uses `response.prediction`

**File:** `frontend/src/components/PredictionResult.jsx`
**Purpose:** Shows the result. It never makes its own fraud decision.

```jsx
// Shows the backend's prediction. Nothing here decides fraud: `result.prediction` comes from FastAPI.
const isFraud = result.prediction === "fraudulent";
const percentText = `${result.fraud_percentage.toFixed(1)}%`;

<h2 id="result-heading">{result.label}</h2>
<p className="score-label">Fraud Risk</p>
<p className="score-value">{percentText}</p>
<div className="risk-bar-fill" style={{ width: `${result.fraud_percentage}%` }} />
<p className="result-disclaimer">{result.disclaimer}</p>
```

(Simplified from the component. Icons, accessibility attributes and the model name are left out.)

**Explain:**
- The frontend only *displays* what the backend decided. There is no `if (probability > 0.5)` anywhere in the React code.
- That separation matters: the model, the threshold and the decision rule live in one place, so the UI cannot drift out of sync with the model.
- The wording says "Fraud Risk" and "not a certainty", and the disclaimer is always shown.
- The label also appears as text and icon, so the result never depends on color alone.
