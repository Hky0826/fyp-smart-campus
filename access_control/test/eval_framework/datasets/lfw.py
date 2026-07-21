import os
import random
from .base import BaseDataset

class LFWDataset(BaseDataset):
    def __init__(self, data_dir, sample_size=None, seed=42):
        super().__init__("LFW", data_dir, sample_size, seed)
        self.kaggle_id = "jessicali9530/lfw-dataset"
        
    def download(self):
        if not os.path.exists(os.path.join(self.data_dir, "lfw-deepfunneled")):
            self._download_kaggle_dataset(self.kaggle_id)
            
    def prepare(self):
        # We need pairs.txt
        # Kaggle's lfw-dataset contains 'pairs.csv' or 'pairs.txt'.
        # Let's assume standard pairs.txt format or a fallback logic.
        pairs_file = os.path.join(self.data_dir, "pairs.txt")
        if not os.path.exists(pairs_file):
            pairs_file = os.path.join(self.data_dir, "lfw_allnames.csv") # Alternate check
        
        # Mock logic to generate pairs if pairs.txt is missing from kaggle download
        # A standard LFW pairs.txt has:
        # 10 300
        # name1 id1 id2
        # name1 id1 name2 id2
        
        self.pairs = []
        lfw_dir = os.path.join(self.data_dir, "lfw-deepfunneled", "lfw-deepfunneled")
        if not os.path.exists(lfw_dir):
            lfw_dir = os.path.join(self.data_dir, "lfw-deepfunneled") # Try alternative path
            
        if not os.path.exists(lfw_dir):
            # Try root if lfw-deepfunneled not there
            lfw_dir = self.data_dir

        if os.path.exists(pairs_file) and pairs_file.endswith(".txt"):
            with open(pairs_file, 'r') as f:
                lines = f.readlines()
                for line in lines[1:]: # Skip header
                    parts = line.strip().split()
                    if len(parts) == 3: # Genuine: name, id1, id2
                        img1 = os.path.join(lfw_dir, parts[0], f"{parts[0]}_{int(parts[1]):04d}.jpg")
                        img2 = os.path.join(lfw_dir, parts[0], f"{parts[0]}_{int(parts[2]):04d}.jpg")
                        self.pairs.append((img1, img2, True))
                    elif len(parts) == 4: # Impostor: name1, id1, name2, id2
                        img1 = os.path.join(lfw_dir, parts[0], f"{parts[0]}_{int(parts[1]):04d}.jpg")
                        img2 = os.path.join(lfw_dir, parts[2], f"{parts[2]}_{int(parts[3]):04d}.jpg")
                        self.pairs.append((img1, img2, False))
        else:
            # Fallback: create random pairs from directory structure
            print("Warning: pairs.txt not found. Generating random synthetic pairs from directories.")
            persons = [d for d in os.listdir(lfw_dir) if os.path.isdir(os.path.join(lfw_dir, d))]
            images = {}
            for p in persons:
                imgs = [os.path.join(lfw_dir, p, f) for f in os.listdir(os.path.join(lfw_dir, p)) if f.endswith('.jpg')]
                if len(imgs) > 0:
                    images[p] = imgs
            
            # Generate genuine
            gen_pairs = []
            for p, imgs in images.items():
                if len(imgs) >= 2:
                    gen_pairs.append((imgs[0], imgs[1], True))
                    
            # Generate impostor
            imp_pairs = []
            p_keys = list(images.keys())
            for i in range(len(gen_pairs)):
                p1, p2 = random.sample(p_keys, 2)
                imp_pairs.append((images[p1][0], images[p2][0], False))
                
            self.pairs = gen_pairs + imp_pairs

        # Shuffle and sample
        random.seed(self.seed)
        random.shuffle(self.pairs)
        if self.sample_size and self.sample_size < len(self.pairs):
            self.pairs = self.pairs[:self.sample_size]
