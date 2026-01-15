#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install Tesseract OCR for scanned PDF support
apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
