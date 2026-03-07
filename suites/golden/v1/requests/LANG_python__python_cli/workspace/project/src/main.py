#!/usr/bin/env python3
import argparse

def main():
    parser = argparse.ArgumentParser(description='CLI application')
    parser.add_argument("command", choices=["golden-python-cli"], help="Command to run")
    args = parser.parse_args()
    if args.command == "golden-python-cli":
        print('Hello, World!')
if __name__ == "__main__":
    main()
