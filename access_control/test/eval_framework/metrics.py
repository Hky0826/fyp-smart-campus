import numpy as np
from sklearn.metrics import roc_curve, auc
import pandas as pd

def calculate_metrics(labels, scores, threshold):
    """
    Calculate FAR, FRR, TAR, TRR for a specific threshold.
    labels: array of booleans (1/True for genuine, 0/False for impostor)
    scores: array of floats (cosine similarity scores)
    threshold: float
    
    Returns: dict of metrics
    """
    labels = np.array(labels, dtype=bool)
    scores = np.array(scores)
    
    # Predictions
    preds = scores >= threshold
    
    # True Positives (Genuine accepted)
    tp = np.sum((preds == True) & (labels == True))
    # False Negatives (Genuine rejected)
    fn = np.sum((preds == False) & (labels == True))
    # True Negatives (Impostor rejected)
    tn = np.sum((preds == False) & (labels == False))
    # False Positives (Impostor accepted)
    fp = np.sum((preds == True) & (labels == False))
    
    far = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    frr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    tar = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    trr = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    
    return {
        "threshold": threshold,
        "FAR": far,
        "FRR": frr,
        "TAR": tar,
        "TRR": trr
    }

def calculate_eer(labels, scores):
    """
    Calculate the Equal Error Rate (EER) and the threshold where it occurs.
    """
    labels = np.array(labels, dtype=int)
    scores = np.array(scores)
    
    if len(np.unique(labels)) < 2:
        print("Warning: Only one class present in labels (no negative or positive samples). Cannot compute ROC curve.")
        # Return dummy arrays to prevent downstream crash
        return float('nan'), float('nan'), np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([0.0, 1.0])
        
    fpr, tpr, thresholds = roc_curve(labels, scores)
    fnr = 1 - tpr
    
    # EER is where FPR (FAR) == FNR (FRR)
    # The absolute difference is minimized
    diff = np.abs(fpr - fnr)
    eer_index = np.argmin(diff)
    
    eer = (fpr[eer_index] + fnr[eer_index]) / 2.0
    eer_threshold = thresholds[eer_index]
    if np.isinf(eer_threshold):
        eer_threshold = float(np.max(scores)) if len(scores) > 0 else 0.0
    
    return eer, eer_threshold, fpr, tpr, thresholds


def evaluate_thresholds(labels, scores, thresholds):
    """
    Evaluate multiple thresholds and return a DataFrame.
    """
    results = []
    for t in thresholds:
        results.append(calculate_metrics(labels, scores, t))
    return pd.DataFrame(results)

def get_tar_at_far(fpr, tpr, target_fars):
    """
    Interpolate TAR (TPR) at specific FAR (FPR) targets.
    fpr, tpr are from roc_curve.
    """
    results = {}
    for far_target in target_fars:
        # We need to find the TAR at the largest FPR <= target_far
        # Or interpolate. Since ROC points are discrete, interpolation is best.
        tar = np.interp(far_target, fpr, tpr)
        results[f"TAR_at_FAR_{far_target}"] = tar
    return results
