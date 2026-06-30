# Lake Michigan Coffee Packing Report

Simple desktop app for pulling WooCommerce processing orders, creating a printable packing/product PDF, and marking all processing orders completed.

## First run

The Mac app will ask for the WooCommerce Consumer Key and Consumer Secret once, then save them locally on that Mac in:

`~/Library/Application Support/LakeMichiganOrderManager/config.json`

The keys are not stored in this public GitHub repository.

## Build on GitHub Actions

Push this repo to GitHub, then open the **Actions** tab and run **Build Mac App**. The build produces zipped macOS `.app` artifacts.

Artifacts:

- `LakeMichiganOrderManager-mac-apple-silicon.zip`
- `LakeMichiganOrderManager-mac-intel.zip`

## Local dev run

```bash
python3 -m pip install -r requirements.txt
python3 order_manager.py
```
