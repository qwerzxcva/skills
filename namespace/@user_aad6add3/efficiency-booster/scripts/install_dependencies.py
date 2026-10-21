#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Install dependencies for efficiency-booster skill
"""

import subprocess
import sys


def install_package(package):
    """Install a single package"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])
        print(f"[OK] Installed: {package}")
        return True
    except subprocess.CalledProcessError:
        print(f"[FAIL] Failed to install: {package}")
        return False


def main():
    """Main function"""
    print("Installing efficiency-booster skill dependencies...")
    print("-" * 50)
    
    packages = [
        "python-docx",
    ]
    
    success_count = 0
    for package in packages:
        if install_package(package):
            success_count += 1
    
    print("-" * 50)
    print(f"Completed: {success_count}/{len(packages)} packages")
    
    if success_count == len(packages):
        print("[OK] All dependencies installed successfully!")
    else:
        print("[WARN] Some dependencies failed to install")


if __name__ == '__main__':
    main()
