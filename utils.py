import os
import hashlib
import pickle
import subprocess
import sys
from typing import Dict, List, Optional
import yaml
import glob

CACHE_FILE = "/tmp/hledger_query_cache.pkl"

def load_journal_directory() -> str:
    """Load the journal directory path from personal.yaml"""
    with open("hledger_parameters/personal.yaml", "r") as f:
        params = yaml.safe_load(f)
        journal_dir = params.get("journal_directory", "~/cloud/finance")
        return os.path.expanduser(journal_dir)

JOURNAL_DIR = load_journal_directory()

def hash_journal_dir(directory: str) -> str:
    """
    Create a hash representing the current state of all files in the journal directory.
    """
    sha = hashlib.sha256()
    for root, _, files in os.walk(directory):
        for f in sorted(files):
            path = os.path.join(root, f)
            try:
                stat = os.stat(path)
                sha.update(path.encode())
                sha.update(str(stat.st_mtime).encode())
                sha.update(str(stat.st_size).encode())
            except FileNotFoundError:
                continue  # In case file is deleted mid-walk
    return sha.hexdigest()

def load_cache() -> Dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "rb") as f:
                return pickle.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache: Dict):
    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(cache, f)
    except Exception:
        pass 

def parse_hledger_output(output: str) -> float:
    """
    Parse the output of an hledger command and extract the numeric total from the last line.
    """
    if not output.strip():
        return 0.0
    last_line = output.strip().splitlines()[-1]  # Get the last line of output
    total_str = last_line.split()[0].replace('$', '').replace(',', '')
    try:
        return abs(float(total_str))
    except ValueError:
        return 0.0

def run_hledger_command(args: list, year: Optional[int] = None, add_format: bool = True) -> float:
    """
    Run hledger bal and return the parsed result. Appends default format args unless add_format is False.
    """
    cmd = ["hledger", "bal"]
    if year is not None:
        cmd += ["-p", str(year)]
    cmd += args
    if add_format:
        cmd += ["-1"]

    cache_key = (tuple(args), year)
    journal_hash = hash_journal_dir(JOURNAL_DIR)

    cache = load_cache()
    if journal_hash in cache and cache_key in cache[journal_hash]:
        return cache[journal_hash][cache_key]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running {' '.join(cmd)}: {e}", file=sys.stderr)
        return 0.0
    result = parse_hledger_output(proc.stdout)
    if journal_hash not in cache:
        cache[journal_hash] = {}
    cache[journal_hash][cache_key] = result
    save_cache(cache)
    return result 

def load_tax_params(year: int) -> dict:
    def load_jurisdiction(jurisdiction: str, year: int):
        folder = f"tax_parameters/{jurisdiction.upper()}"
        year_file = f"{folder}/{year}.yaml"
        if os.path.exists(year_file):
            with open(year_file, "r") as f:
                return yaml.safe_load(f)
        # Use the latest year available
        year_files = glob.glob(f"{folder}/*.yaml")
        years = [int(os.path.splitext(os.path.basename(f))[0]) for f in year_files if os.path.basename(f)[:-5].isdigit()]
        if not years:
            raise FileNotFoundError(f"No tax parameter file found for {jurisdiction}")
        latest_year = max(years)
        with open(f"{folder}/{latest_year}.yaml", "r") as f:
            return yaml.safe_load(f)
    federal = load_jurisdiction("federal", year)
    ca = load_jurisdiction("ca", year)
    return {"federal": federal, "ca": ca}

def load_hledger_aliases() -> dict:
    with open("hledger_parameters/aliases.yaml", "r") as f:
        return yaml.safe_load(f)

def load_business_expenses() -> list:
    with open("hledger_parameters/business_income.yaml", "r") as f:
        return yaml.safe_load(f).get("business_expenses", [])

def load_home_office_info() -> dict:
    with open("hledger_parameters/personal.yaml", "r") as f:
        params = yaml.safe_load(f)
        return params.get("home_office", {})

def load_filing_status() -> str:
    with open("hledger_parameters/personal.yaml", "r") as f:
        return yaml.safe_load(f).get("filing_status", "joint")

def load_additional_federal_deduction() -> float:
    with open("hledger_parameters/personal.yaml", "r") as f:
        return yaml.safe_load(f).get("additional_federal_deduction", 0.0) 