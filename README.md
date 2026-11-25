# Olist CSV processing tool

This project reads every CSV in `data/raw/`, applies configurable column names, validates rows, writes clean outputs and rejected rows, and records completed inputs in a manifest.

## Set up

1. Install Python 3.10 or newer and Jupyter Notebook from the official [Python](https://www.python.org/downloads/) and [Jupyter](https://jupyter.org/install) sites.
2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

3. Download the Olist dataset CSV files from Kaggle and place them in `data/raw/`. The tool accepts any CSVs in that folder; it does not require every Olist table.
4. Review `config.json`. Add source-to-standard column mappings under `column_mappings` using the CSV filename as the key. List required standardized columns under `required_columns`.

## Run

From the project root:

```powershell
jupyter notebook notebooks/run_pipeline.ipynb
```

Run the notebook cells in order. Or run the same pipeline from a terminal:

```powershell
python -m src.olist_tool --config config.json
```

Outputs are written to `data/processed/`, invalid rows to `data/processed/bad_records.csv`, logs to `logs/olist_tool.log`, and the idempotency manifest to `data/processed/manifest.json`. To deliberately reprocess a file, remove its entry from the manifest or delete the manifest.

## Add a column or file during review

The default configuration preserves unmapped columns (`keep_unmapped_columns: true`), so an extra column is retained automatically. To rename it, add its source and standard name in that file's `column_mappings` entry. For a newly added CSV, add its filename and mapping there as needed. Rerun the notebook; the file will be processed based on its content hash.

## Git workflow

Create a repository and feature branches locally, commit each coherent change, push branches, and open PRs on GitHub for review. Example:

```powershell
git init
git add .
git commit -m "Add Olist CSV processing tool"
git switch -c feature/configurable-mappings
# make and commit a focused change
git push -u origin feature/configurable-mappings
```

Create and merge the PR in GitHub. Repeat with separate branches for validation, logging, and tests. A clean history and actual PRs require a GitHub repository and remote; this folder does not contain a remote or pre-existing PR history.

## Tests

Run the unit tests with `python -m unittest discover -s tests -v`.
