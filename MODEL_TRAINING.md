# Model Training

Run commands from the repository root with the backend requirements installed (`python -m pip install -r backend/requirements.txt`). Scikit-learn, Pandas, NumPy, and Joblib are required.

## Train API Failure and Rejection Models

```powershell
python -m ml.training.train_intelligence_models
```

This creates seeded scenario datasets and performs stratified 70/15/15 train/validation/test splits. Vectorizers and encoders are fit only on the training partition through Scikit-learn pipelines. It writes:

- `ml/datasets/synthetic_failure_classification.csv`
- `ml/datasets/synthetic_rejection_classification.csv`
- `ml/models/api_failure_classifier.joblib`
- `ml/models/api_failure_classifier_metrics.json`
- `ml/models/order_rejection_classifier.joblib`
- `ml/models/order_rejection_classifier_metrics.json`
- `ml/models/rejection_fixability.joblib`
- `ml/models/rejection_fixability_metrics.json`

The dataset generators are in `ml/datasets/generate_synthetic.py`. Seeds are explicit and fixed for reproducibility. Model versions are recorded in each artifact's metadata. Prediction probabilities are not calibrated.

## Train Delay Models

```powershell
python -m ml.training.train_delay_model
```

This produces a seeded 5,000-row dataset, a stratified 80/20 train/test split, a breach classifier, a remaining-time regressor, and reports under `ml/datasets/synthetic_delay_training.csv`, `ml/models/delay_predictor.joblib`, and `ml/models/delay_metrics.json`.

## Running the Application

```powershell
python -m pip install -r backend/requirements.txt
Set-Location backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

The trained artifacts must exist at `ml/models/` before starting the API for model-backed endpoints to report available. If model artifacts are unavailable, prediction endpoints fail explicitly instead of fabricating a result.
