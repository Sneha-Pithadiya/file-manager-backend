import os
import random
from pathlib import Path

UPLOAD_DIR = Path("./uploads")

EXTENSIONS = [".txt", ".pdf", ".jpg", ".zip", ".docx", ".mp3", ".csv"]

def create_dummy_file(path):
    """Creates a small dummy file with random content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(f"This is a test file: {path.name}\nRandom ID: {random.randint(1000, 9999)}")

def generate_structure():
    print(f"Starting test data generation in: {UPLOAD_DIR.absolute()}")
    
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    top_folders = ["Documents", "Images", "Work_Project", "Archive", "Empty_Folder"]
    for folder in top_folders:
        folder_path = UPLOAD_DIR / folder
        folder_path.mkdir(exist_ok=True)
        print(f"Created folder: {folder}")

    nested_path = UPLOAD_DIR / "Work_Project" / "2024" / "Q1" / "Drafts"
    nested_path.mkdir(parents=True, exist_ok=True)
    create_dummy_file(nested_path / "project_plan.docx")
    create_dummy_file(nested_path / "budget.csv")
    print("Created nested structure: Work_Project > 2024 > Q1 > Drafts")

    for i in range(1, 15):
        ext = random.choice(EXTENSIONS)
        create_dummy_file(UPLOAD_DIR / "Documents" / f"report_{i}{ext}")

    for i in range(1, 10):
        create_dummy_file(UPLOAD_DIR / "Images" / f"photo_{i}.jpg")

    for i in range(1, 20):
        ext = random.choice(EXTENSIONS)
        create_dummy_file(UPLOAD_DIR / f"root_file_{i}{ext}")

    print("\nSuccess! Created ~50 items (files/folders).")
    print("👉 Now go to your File Manager and run 'Sync Disk to DB' to see them.")

if __name__ == "__main__":
    generate_structure()