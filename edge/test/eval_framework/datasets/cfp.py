import os
import random
if __name__ == '__main__':
    import sys, os
    # Add the parent directory of 'datasets' to sys.path
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from datasets.base import BaseDataset
else:
    from .base import BaseDataset

class CFPDataset(BaseDataset):
    def __init__(self, data_dir, sample_size=None, seed=42):
        super().__init__("CFP", data_dir, sample_size, seed)
        # Assuming a standard Kaggle CFP dataset upload (e.g. from users like sayhye or similar)
        # Update this identifier if a specific Kaggle CFP dataset is preferred
        self.kaggle_id = "abhinav1402/cfp-dataset" 
        
    def download(self):
        try:
            import kagglehub
            print("\nDownloading CFP dataset using kagglehub...")
            path = kagglehub.dataset_download("chinafax/cfpw-dataset")
            print(f"CFP dataset downloaded to: {path}")
            # Update data_dir to the kagglehub cache path so prepare() can find Protocol and Images
            self.data_dir = path
        except ImportError:
            print("\n[!] Error: 'kagglehub' is not installed.")
            print("Please run 'pip install kagglehub' to download the CFP dataset automatically.")
        except Exception as e:
            print(f"\n[!] Error downloading CFP dataset via kagglehub: {e}")
            
    def prepare(self):
        # CFP has Frontal-Profile (FP) and Frontal-Frontal (FF) protocols
        # usually 10 splits. We will aggregate them.
        protocol_dir = os.path.join(self.data_dir, "Protocol")
        image_dir = os.path.join(self.data_dir, "Images")
        if not os.path.exists(image_dir):
            image_dir = os.path.join(self.data_dir, "Data")
            
        # If not at the root, search for them in subdirectories (often datasets are nested)
        if not (os.path.exists(protocol_dir) and os.path.exists(image_dir)):
            for root, dirs, files in os.walk(self.data_dir):
                has_images = "Images" in dirs or "Data" in dirs
                if "Protocol" in dirs and has_images:
                    protocol_dir = os.path.join(root, "Protocol")
                    image_dir = os.path.join(root, "Images") if "Images" in dirs else os.path.join(root, "Data")
                    print(f"Found Protocol and image directory nested in: {root}")
                    break
        
        self.pairs = []
        
        if os.path.exists(protocol_dir) and os.path.exists(image_dir):
            for split_idx in range(1, 11):
                split_dir = os.path.join(protocol_dir, "Split", f"{split_idx:02d}")
                gen_file = os.path.join(split_dir, "FP", "same.txt")
                imp_file = os.path.join(split_dir, "FP", "diff.txt")
                
                # Parse genuine
                if os.path.exists(gen_file):
                    with open(gen_file, 'r') as f:
                        for line in f:
                            parts = line.strip().split(',')
                            if len(parts) >= 2:
                                # CFP format: 001/frontal/01.jpg,001/profile/01.jpg
                                img1 = os.path.join(image_dir, parts[0].strip())
                                img2 = os.path.join(image_dir, parts[1].strip())
                                self.pairs.append((img1, img2, True))
                                
                # Parse impostor
                if os.path.exists(imp_file):
                    with open(imp_file, 'r') as f:
                        for line in f:
                            parts = line.strip().split(',')
                            if len(parts) >= 2:
                                img1 = os.path.join(image_dir, parts[0].strip())
                                img2 = os.path.join(image_dir, parts[1].strip())
                                self.pairs.append((img1, img2, False))
        else:
            print("Warning: CFP Protocol/Images not found. Generating dummy pairs for testing.")
            # Dummy generation logic for testing if dataset is missing
            self.pairs = [
                ("dummy1.jpg", "dummy2.jpg", True),
                ("dummy1.jpg", "dummy3.jpg", False)
            ]
            
        # Shuffle and sample
        random.seed(self.seed)
        random.shuffle(self.pairs)
        if self.sample_size and self.sample_size < len(self.pairs):
            self.pairs = self.pairs[:self.sample_size]

if __name__ == '__main__':
    # Test the CFP dataset download and prepare logic
    import argparse
    parser = argparse.ArgumentParser(description="Test CFPDataset loading")
    parser.add_argument("--data-dir", type=str, default="./data/cfp", help="Path to store dataset")
    args = parser.parse_args()

    dataset = CFPDataset(data_dir=args.data_dir)
    print("Testing CFPDataset...")
    dataset.download()
    dataset.prepare()
    pairs = dataset.get_pairs()
    
    print(f"\nSuccessfully loaded {len(pairs)} pairs.")
    if len(pairs) > 0:
        print("First 2 pairs:")
        for p in pairs[:2]:
            print(f"  {p}")
