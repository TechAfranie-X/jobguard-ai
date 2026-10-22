# Live Demo Script

Total time: about 3 minutes. Say the lines in quotes in your own words; they are suggestions.

## Before you start (2 minutes, do this first)

From the project root, in two terminals:

```bash
# Terminal 1: backend (wait for "Application startup complete", the model takes a few seconds to load)
source .venv/bin/activate
uvicorn backend.main:app

# Terminal 2: frontend
cd frontend
npm run dev
```

Check before presenting:
1. `http://127.0.0.1:8000/health` shows `"status":"ok"` and `"model_loaded":true`.
2. `http://localhost:5173` loads and shows the "Check a job before you apply." page with the paste box.
3. Run each example once as a warm-up (the first prediction after startup is the slowest).
4. Browser zoom at 100%, full screen, notifications off.

Verified results for the two demo examples (real API output; the screen shows one decimal place):

| Example | Prediction | Fraud probability | Shown on screen |
|---|---|---|---|
| Professional posting (example chip) | Likely Legitimate | 0.0007 (0.07%) | 0.1% |
| Suspicious posting (example chip) | Potentially Fraudulent | 0.9891 (98.91%) | 98.9% |

---

## The 12 steps

1. **Open the homepage** at `http://localhost:5173`.
2. **One-sentence explanation.** "JobGuard AI reads a job posting and estimates how likely it is to be fraudulent, using a fine-tuned DistilBERT model."
3. **Click the "Professional posting" example.** The paste box fills with one block of text; nothing is submitted yet.
4. **Point out the Detected details line.** "I pasted one block of text. JobGuard found the title, company information, requirements and benefits by itself, with simple rules, no AI service. I can open Review extracted details if I want to check or edit them."
5. **Click "Analyze Job".**
6. **Show "Likely Legitimate" and the risk percentage.** Point at the Fraud Risk number (about 0.1%) and the bar. "The model gives this posting a very low fraud risk."
7. **Click "Analyze another posting"** (or "Clear") to reset the page.
8. **Click the "Suspicious posting" example.** "This one has the classic signs: big money, work from home, and a request for personal details."
9. **Click "Analyze Job".**
10. **Show "Potentially Fraudulent"** and the high Fraud Risk (about 98.9%).
11. **Say it clearly:** "This percentage is a risk score from the model, not proof. It should support a human decision, and the app says so in the note on the screen."
12. **Mention the model.** "Behind the page is a FastAPI backend running a fine-tuned DistilBERT. It scored the best fraud F1, 0.8075, of the four models we compared on held-out test data."

If asked about mistakes, be honest: the model missed 37 of 144 scams in the test set, and long postings are truncated to 256 tokens.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| The page says "We couldn't analyze this posting right now. Please try again." | The backend is not running or still loading. Restart Terminal 1, wait about 10 seconds, and click Analyze again. If it persists, switch to the BACKUP DEMO PLAN. |
| Analyze is slow the first time | The model is warming up. Wait a few seconds. Warm up before the audience arrives next time. |
| Wi-Fi is unreliable | Nothing in the demo needs the internet. The model, backend and frontend all run on this laptop. |

---

## BACKUP DEMO PLAN (screenshots, no live app needed)

Use this if the laptop, backend or browser fails. These are **real screenshots** from the running app. Say clearly that they are screenshots, and do not claim a live result.

1. **Homepage** → `results/figures/jobguard_v2_homepage.png`
   "This is the JobGuard AI web app. The user pastes a whole posting, or loads one of the examples."
   Optional: `jobguard_v2_paste_filled.png` (pasted posting with the detected summary) and `jobguard_v2_extracted_details.png` (the optional review panel).
2. **Legitimate result** → `results/figures/jobguard_v2_legitimate_result.png`
   "For the professional example the model reported Likely Legitimate with a fraud risk of about 0.1%."
3. **Fraudulent result** → `results/figures/jobguard_v2_fraudulent_result.png`
   "For the suspicious example it reported Potentially Fraudulent with a fraud risk of about 98.9%."
4. **Mobile view** → `results/figures/jobguard_v2_mobile.png`
   "The page also works on a phone-sized screen."
5. **Architecture** → `results/figures/jobguard_system_architecture.png`
   "Here is what happens behind the button: React sends the pasted text to FastAPI, which splits it into the five fields with simple rules, builds the combined text, tokenizes it, runs DistilBERT, and returns the probability."
6. **API documentation** (optional) → `results/figures/backend_swagger_docs.png`
   "The backend documents itself, so any other application could call the same model."

Then give the same take-aways as steps 11 and 12 above.
