import os
import yaml
import json
import numpy as np
import pandas as pd
from tqdm import tqdm
from pathlib import Path

from datasets.lfw import LFWDataset
from datasets.cfp import CFPDataset
from model_interface import ModelInterface
from metrics import calculate_eer, evaluate_thresholds, get_tar_at_far
from visualize import plot_roc_curve, plot_det_curve, plot_score_distributions, plot_threshold_vs_error

def load_config(config_path="config.yaml"):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

def run_evaluation(dataset, model_interface, thresholds, far_targets, results_dir):
    os.makedirs(results_dir, exist_ok=True)
    
    # 1. Download and Prepare Data
    dataset.download()
    dataset.prepare()
    pairs = dataset.get_pairs()
    
    if len(pairs) == 0:
        print(f"\n[!] Skipping {dataset.name} evaluation: No valid image pairs were found.")
        print("This usually means the dataset was not downloaded correctly or the folder structure is missing.")
        return None
        
    print(f"\nEvaluating {dataset.name} on {len(pairs)} pairs...")
    
    labels = []
    scores = []
    
    # 2. Extract Embeddings and Compute Scores
    for img1, img2, is_same in tqdm(pairs, desc=f"Processing {dataset.name}"):
        try:
            emb1 = model_interface.extract_embedding(img1)
            emb2 = model_interface.extract_embedding(img2)
            score = model_interface.compute_similarity(emb1, emb2)
            
            labels.append(is_same)
            scores.append(score)
        except Exception as e:
            # Skip invalid images
            pass
            
    if len(scores) == 0:
        print(f"No valid scores computed for {dataset.name}.")
        return None

    # 3. Compute Metrics
    eer, eer_threshold, fpr, tpr, roc_thresholds = calculate_eer(labels, scores)
    threshold_df = evaluate_thresholds(labels, scores, thresholds)
    tar_at_far = get_tar_at_far(fpr, tpr, far_targets)
    
    genuine_scores = [s for l, s in zip(labels, scores) if l]
    impostor_scores = [s for l, s in zip(labels, scores) if not l]
    
    # 4. Generate Visualizations
    plot_roc_curve(fpr, tpr, os.path.join(results_dir, "roc_curve.png"))
    plot_det_curve(fpr, 1 - tpr, os.path.join(results_dir, "det_curve.png"))
    plot_score_distributions(genuine_scores, impostor_scores, os.path.join(results_dir, "score_dist.png"))
    plot_threshold_vs_error(threshold_df, os.path.join(results_dir, "threshold_vs_error.png"))
    
    # 5. Export Data
    pd.DataFrame({'genuine_scores': genuine_scores}).to_csv(os.path.join(results_dir, "genuine_scores.csv"), index=False)
    pd.DataFrame({'impostor_scores': impostor_scores}).to_csv(os.path.join(results_dir, "impostor_scores.csv"), index=False)
    threshold_df.to_csv(os.path.join(results_dir, "threshold_results.csv"), index=False)
    
    metrics = {
        "Dataset": dataset.name,
        "Total_Pairs": len(scores),
        "EER": float(eer),
        "EER_Threshold": float(eer_threshold)
    }
    metrics.update({k: float(v) for k, v in tar_at_far.items()})
    
    with open(os.path.join(results_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=4)
        
    pd.DataFrame([metrics]).to_csv(os.path.join(results_dir, "metrics.csv"), index=False)
    
    return metrics

def main():
    config = load_config()
    
    detector_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "facial_recognition", "models", "surveillance", "scrfd_10g.hef"))
    embedder_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "facial_recognition", "models", "surveillance", "arcface_r50.hef"))

    model_interface = ModelInterface(
        detector_path=detector_path,
        embedder_path=embedder_path,
        device="cpu"
    )
    
    t_start = config['thresholds']['start']
    t_end = config['thresholds']['end']
    t_step = config['thresholds']['step']
    thresholds = np.arange(t_start, t_end + t_step, t_step)
    
    far_targets = config['far_targets']
    
    results_base = "./results"
    
    datasets_to_run = [
        LFWDataset(
            data_dir=config['datasets']['lfw']['data_dir'],
            sample_size=config['datasets']['lfw'].get('sample_size'),
            seed=config['random_seed']
        ),
        CFPDataset(
            data_dir=config['datasets']['cfp']['data_dir'],
            sample_size=config['datasets']['cfp'].get('sample_size'),
            seed=config['random_seed']
        )
    ]
    
    all_metrics = []
    
    for ds in datasets_to_run:
        ds_results_dir = os.path.join(results_base, ds.name.lower())
        metrics = run_evaluation(ds, model_interface, thresholds, far_targets, ds_results_dir)
        if metrics:
            all_metrics.append(metrics)
            
    # Combined Summary
    if all_metrics:
        combined_dir = os.path.join(results_base, "combined_summary")
        os.makedirs(combined_dir, exist_ok=True)
        combined_df = pd.DataFrame(all_metrics)
        combined_df.to_csv(os.path.join(combined_dir, "combined_metrics.csv"), index=False)
        print("\nEvaluation Complete! Combined Metrics:")
        print(combined_df.to_markdown(index=False))

if __name__ == "__main__":
    main()
