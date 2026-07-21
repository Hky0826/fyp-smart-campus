from abc import ABC, abstractmethod
import os
import zipfile
import subprocess

class BaseDataset(ABC):
    def __init__(self, name, data_dir, sample_size=None, seed=42):
        self.name = name
        self.data_dir = data_dir
        self.sample_size = sample_size
        self.seed = seed
        self.pairs = [] # List of tuples: (img1_path, img2_path, is_same)
        
    @abstractmethod
    def download(self):
        """Download dataset if not exists"""
        pass
        
    @abstractmethod
    def prepare(self):
        """Parse dataset pairs/templates and populate self.pairs"""
        pass
        
    def get_pairs(self):
        return self.pairs
        
    def _download_kaggle_dataset(self, dataset_identifier, extract_dir=None):
        if extract_dir is None:
            extract_dir = self.data_dir
            
        os.makedirs(extract_dir, exist_ok=True)
        print(f"Downloading {dataset_identifier} from Kaggle into {extract_dir}...")
        
        try:
            # We use Kaggle CLI which needs to be authenticated.
            # Assuming user has kaggle credentials set up in ~/.kaggle/kaggle.json
            subprocess.run(
                ["kaggle", "datasets", "download", "-d", dataset_identifier, "-p", extract_dir, "--unzip"],
                check=True
            )
            print(f"Successfully downloaded and unzipped {dataset_identifier}")
        except FileNotFoundError:
            print(f"\n[!] Error: Kaggle CLI not found. Could not download {dataset_identifier}.")
            print("Please either 'pip install kaggle' and configure it, or download the dataset manually to the specified data directory.")
        except subprocess.CalledProcessError as e:
            print(f"\n[!] Error downloading {dataset_identifier}: Kaggle returned an error (perhaps the dataset is private or forbidden).")
            print("Please download it manually to the specified data directory.")
