import matplotlib.pyplot as plt
import numpy as np
import os

def plot_roc_curve(fpr, tpr, output_path):
    plt.figure()
    plt.plot(fpr, tpr, color='darkorange', lw=2, label='ROC curve')
    plt.plot([0, 1], [0, 1], color='navy', lw=2, linestyle='--')
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel('False Positive Rate (FAR)')
    plt.ylabel('True Positive Rate (TAR)')
    plt.title('Receiver Operating Characteristic')
    plt.legend(loc="lower right")
    plt.savefig(output_path)
    plt.close()

def plot_det_curve(fpr, fnr, output_path):
    """
    Plot Detection Error Tradeoff (DET) curve.
    Normally uses normal deviate scale, but standard log scale is also acceptable.
    """
    import matplotlib.pyplot as plt
    plt.figure()
    
    # Add a tiny epsilon to avoid log(0) and empty arrays on perfect separation
    epsilon = 1e-6
    fpr_clean = fpr + epsilon
    fnr_clean = fnr + epsilon
    
    plt.plot(fpr_clean, fnr_clean, color='blue', lw=2, label='DET curve')
    plt.xscale('log')
    plt.yscale('log')
    plt.xlabel('False Acceptance Rate (FAR)')
    plt.ylabel('False Rejection Rate (FRR)')
    plt.title('DET Curve')
    plt.grid(True, which="both", ls="-", alpha=0.5)
    plt.legend(loc="upper right")
    plt.savefig(output_path)
    plt.close()

def plot_score_distributions(genuine_scores, impostor_scores, output_path):
    plt.figure()
    plt.hist(genuine_scores, bins=50, alpha=0.5, label='Genuine', color='green', density=True)
    plt.hist(impostor_scores, bins=50, alpha=0.5, label='Impostor', color='red', density=True)
    plt.xlabel('Cosine Similarity Score')
    plt.ylabel('Density')
    plt.title('Score Distribution (Genuine vs Impostor)')
    plt.legend(loc='upper right')
    plt.savefig(output_path)
    plt.close()

def plot_threshold_vs_error(threshold_df, output_path):
    plt.figure()
    plt.plot(threshold_df['threshold'], threshold_df['FAR'], label='FAR', color='red')
    plt.plot(threshold_df['threshold'], threshold_df['FRR'], label='FRR', color='blue')
    plt.xlabel('Cosine Similarity Threshold')
    plt.ylabel('Error Rate')
    plt.title('FAR and FRR vs. Threshold')
    plt.legend(loc='best')
    plt.savefig(output_path)
    plt.close()
