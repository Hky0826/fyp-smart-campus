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
            import shutil
            
            # Check if the dataset is already present in our local data folder
            protocol_path = os.path.join(self.data_dir, "Protocol")
            if os.path.exists(protocol_path):
                return
                
            print("\nDownloading CFP dataset using kagglehub...")
            path = kagglehub.dataset_download("chinafax/cfpw-dataset")
            print(f"CFP dataset downloaded to cache: {path}")
            
            print(f"Copying dataset to local project directory: {self.data_dir}")
            os.makedirs(self.data_dir, exist_ok=True)
            
            for item in os.listdir(path):
                s = os.path.join(path, item)
                d = os.path.join(self.data_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)
            
            print(f"Successfully moved to {self.data_dir}")

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
            print(f"Indexing images in {image_dir}...")
            image_map = {}
            for r, d, f_names in os.walk(image_dir):
                for f in f_names:
                    if not f.startswith('.'):
                        basename = os.path.splitext(f)[0]
                        image_map[basename] = os.path.join(r, f)
            print(f"Indexed {len(image_map)} images.")
            
            # DIAGNOSTIC: Print a few files to see what they look like
            print(f"DIAGNOSTIC: A few indexed files: {list(image_map.keys())[:5]}")
            print(f"DIAGNOSTIC: Top level contents of {image_dir}:")
            try:
                for item in os.listdir(image_dir)[:10]:
                    path = os.path.join(image_dir, item)
                    size = os.path.getsize(path) if os.path.isfile(path) else 'DIR'
                    print(f"  - {item} ({size})")
            except Exception as e:
                print(f"  Failed to list dir: {e}")
            
            def resolve_path(p):
                # Clean up the parsed string
                p = str(p).strip().replace("'", "").replace('"', '')
                basename = os.path.splitext(os.path.basename(p))[0]
                if basename in image_map:
                    return image_map[basename]
                return os.path.join(image_dir, p)
                
            for split_idx in range(1, 11):
                # The chinafax/cfpw-dataset has structure Split/FP/01/same.txt
                split_dir = os.path.join(protocol_dir, "Split", "FP", f"{split_idx:02d}")
                gen_file = os.path.join(split_dir, "same.txt")
                imp_file = os.path.join(split_dir, "diff.txt")
                
                # Parse genuine
                if os.path.exists(gen_file):
                    with open(gen_file, 'r') as f:
                        for line in f:
                            parts = line.strip().split(',')
                            if len(parts) >= 2:
                                img1 = resolve_path(parts[0].strip())
                                img2 = resolve_path(parts[1].strip())
                                self.pairs.append((img1, img2, True))
                                
                # Parse impostor
                if os.path.exists(imp_file):
                    with open(imp_file, 'r') as f:
                        for line in f:
                            parts = line.strip().split(',')
                            if len(parts) >= 2:
                                img1 = resolve_path(parts[0].strip())
                                img2 = resolve_path(parts[1].strip())
                                self.pairs.append((img1, img2, False))
        if len(self.pairs) == 0 and os.path.exists(protocol_dir):
            print(f"DEBUG: Found Protocol dir at {protocol_dir} but loaded 0 pairs.")
            print(f"DEBUG: Let's see what is inside {protocol_dir}:")
            for root, dirs, files in os.walk(protocol_dir):
                print(f"  {root}")
                for f in files[:5]: # Print first 5 files in each dir
                    print(f"    - {f}")
            print("Warning: CFP Protocol text files not found in expected Split/XX/FP format.")
            # Dummy generation logic for testing if dataset is missing
            self.pairs = [
                ("dummy1.jpg", "dummy2.jpg", True),
                ("dummy1.jpg", "dummy3.jpg", False)
            ]
        elif len(self.pairs) == 0:
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
