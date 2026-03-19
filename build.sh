#!/usr/bin/env bash
set -e

echo "=== Installing backend dependencies ==="
cd backend
pip install -r requirements.txt

echo "=== Installing frontend dependencies ==="
cd ../frontend
npm install

echo "=== Building React frontend ==="
npm run build

echo "=== Build complete ==="
