#!/usr/bin/env bash
set -e
git -C /home/yassin/FPCC pull --ff-only
git -C /home/yassin/FPCC push origin main
